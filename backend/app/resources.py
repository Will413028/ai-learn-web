from datetime import timedelta
from pathlib import Path
import math
import re
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.orm import Session

from app.auth import Auth, digest
from app.db import Asset, Chunk, Database, Document, Job, Principal, Quiz, User, new_id
from app.files import FORMATS
from app.providers import FakeProvider, Provider, ProviderError
from app.schemas import AssetRequest, AssetResponse, Citation, DocumentResponse, SourceInfo
from app.services import bounded_call
from app.settings import Settings


def document_response(doc: Document) -> DocumentResponse:
    return DocumentResponse(id=doc.id, filename=doc.filename, status=doc.status, size=doc.size,
        chunk_count=doc.chunk_count, error=doc.error, created_at=doc.created_at.isoformat())


def asset_response(asset: Asset) -> AssetResponse:
    return AssetResponse(id=asset.id, status=asset.status, error=asset.error,
        url=f"/api/v1/assets/{asset.id}/content" if asset.status == "completed" else None)


class Resources:
    def __init__(self, db: Database, auth: Auth, provider: Provider, settings: Settings):
        self.db, self.auth, self.provider, self.settings = db, auth, provider, settings

    def path(self, kind: str, resource_id: str) -> Path:
        try:
            if str(UUID(resource_id)) != resource_id:
                raise ValueError
        except ValueError:
            raise HTTPException(404, "資源不存在") from None
        return self.settings.asset_directory / kind / resource_id

    @staticmethod
    def lock_file(session: Session, resource_id: str, wait: bool = True) -> bool:
        key = int(UUID(resource_id)) % (2**63)
        operation = "pg_advisory_xact_lock" if wait else "pg_try_advisory_xact_lock"
        result = session.scalar(text(f"SELECT {operation}(:key)"), {"key": key})
        return True if wait else bool(result)

    def reconcile_files(self, minimum_age_seconds: float = 86400) -> int:
        removed = 0
        cutoff = self.auth.now().timestamp() - minimum_age_seconds
        for kind in ("documents", "images"):
            directory = self.settings.asset_directory / kind
            if not directory.is_dir() or directory.is_symlink():
                continue
            for path in directory.iterdir():
                if path.is_symlink() or not path.is_file():
                    continue
                try:
                    modified = path.stat().st_mtime
                except OSError:
                    continue
                if modified > cutoff:
                    continue
                match = re.fullmatch(r"([0-9a-f-]{36})(?:\.([0-9]+)\.staging)?", path.name)
                if not match:
                    continue
                resource_id = match[1]
                try:
                    if str(UUID(resource_id)) != resource_id:
                        continue
                    with self.db.transaction() as session:
                        if not self.lock_file(session, resource_id, wait=False):
                            continue
                        if kind == "documents":
                            document = session.get(Document, resource_id)
                            retain = document is not None and document.status != "deleting"
                        else:
                            asset = session.get(Asset, resource_id)
                            retain = match[2] is None and asset is not None and asset.status == "completed"
                        if not retain:
                            path.unlink(missing_ok=True)
                            removed += 1
                except OSError:
                    continue
        return removed

    def upload(self, owner: str, filename: str, data: bytes) -> DocumentResponse:
        filename = Path(filename).name[:255]
        if Path(filename).suffix.lower() not in FORMATS:
            raise HTTPException(422, "只支援 PDF、docx、Markdown、txt")
        if not data or len(data) > self.settings.max_file_bytes:
            raise HTTPException(413, "檔案為空或超過大小限制")
        path: Path | None = None
        try:
            with self.db.transaction() as session:
                user = session.get(User, owner, with_for_update=True)
                if not user:
                    raise HTTPException(401, "請先登入")
                count = session.scalar(select(func.count()).select_from(Document).where(Document.owner_id == owner)) or 0
                if count >= self.settings.max_documents:
                    raise HTTPException(409, "已達文件數量上限，請先刪除文件")
                doc = Document(id=new_id(), owner_id=owner, filename=filename, size=len(data),
                    status="pending", created_at=self.auth.now(), embedding_model=self.provider.embedding_model)
                session.add(doc)
                session.flush()
                self.lock_file(session, doc.id)
                path = self.path("documents", doc.id)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                session.add(Job(owner_id=owner, request_scope_id=owner, request_key=f"document:{doc.id}", payload_hash=digest(doc.id),
                    payload={"document_id": doc.id}, kind="document", status="pending", created_at=self.auth.now()))
                return document_response(doc)
        except Exception:
            if path:
                path.unlink(missing_ok=True)
            raise

    def documents(self, owner: str) -> list[DocumentResponse]:
        with self.db.transaction() as session:
            return [document_response(doc) for doc in session.scalars(select(Document).where(
                Document.owner_id == owner).order_by(Document.created_at.desc()))]

    def document(self, owner: str, document_id: str) -> DocumentResponse:
        with self.db.transaction() as session:
            doc = session.scalar(select(Document).where(Document.id == document_id, Document.owner_id == owner))
            if not doc:
                raise HTTPException(404, "找不到文件")
            return document_response(doc)

    def delete_document(self, owner: str, document_id: str) -> None:
        with self.db.transaction() as session:
            session.get(Principal, owner, with_for_update=True)
            doc = session.scalar(select(Document).where(Document.id == document_id,
                Document.owner_id == owner).with_for_update())
            if not doc:
                raise HTTPException(404, "找不到文件")
            doc.status = "deleting"
            session.execute(delete(Chunk).where(Chunk.document_id == doc.id))
        try:
            self.path("documents", document_id).unlink(missing_ok=True)
        except OSError:
            raise HTTPException(503, "檔案刪除暫時失敗，可再次重試") from None
        with self.db.transaction() as session:
            session.get(Principal, owner, with_for_update=True)
            doc = session.scalar(select(Document).where(Document.id == document_id,
                Document.owner_id == owner).with_for_update())
            if doc:
                session.delete(doc)
            for job in session.scalars(select(Job).where(Job.owner_id == owner, Job.kind == "document")):
                if job.payload.get("document_id") == document_id and job.status in {"pending", "running"}:
                    job.status = "failed"
                    job.version += 1
                    job.error = "文件已刪除"
                    job.lease_until = None

    def retry_document(self, owner: str, document_id: str) -> DocumentResponse:
        with self.db.transaction() as session:
            session.get(Principal, owner, with_for_update=True)
            doc = session.scalar(select(Document).where(Document.id == document_id,
                Document.owner_id == owner).with_for_update())
            if not doc:
                raise HTTPException(404, "找不到文件")
            if doc.status != "failed":
                raise HTTPException(409, "只能重試失敗文件")
            doc.status, doc.error = "pending", None
            key = f"document-retry:{new_id()}"
            session.add(Job(owner_id=owner, request_scope_id=owner, request_key=key, payload_hash=digest(key),
                payload={"document_id": doc.id}, kind="document", status="pending", created_at=self.auth.now()))
            return document_response(doc)

    def vectors(self, texts: list[str]) -> list[list[float]]:
        vectors = bounded_call(lambda deadline: self.provider.embed(texts, deadline=deadline), self.settings.provider_timeout_seconds)
        if len(vectors) != len(texts) or any(len(v) != self.provider.embedding_dimensions or
                not all(isinstance(x, (int, float)) and math.isfinite(x) for x in v) or
                sum(x * x for x in v) == 0 for v in vectors):
            raise ProviderError("Embedding 格式無效")
        return vectors

    def retrieve(self, owner: str, document_id: str, query: str) -> tuple[str, SourceInfo]:
        with self.db.transaction() as session:
            doc = session.scalar(select(Document).where(Document.id == document_id, Document.owner_id == owner))
            if not doc or doc.status != "ready":
                raise ProviderError("指定文件不存在或尚未可檢索")
            if doc.embedding_model != self.provider.embedding_model:
                raise ProviderError("Embedding 模型已變更，請重新處理文件")
            title = doc.filename
        threshold = self.settings.rag_min_similarity
        if threshold is None:
            if not isinstance(self.provider, FakeProvider):
                raise ProviderError("真實檢索門檻尚未設定，請先完成 eval-rag 校準")
            threshold = 0.15
        if not math.isfinite(threshold) or not -1 <= threshold <= 1:
            raise ProviderError("檢索門檻設定無效")
        vector = self.vectors([query])[0]
        with self.db.transaction() as session:
            distance = Chunk.embedding.cosine_distance(vector)
            rows = session.execute(select(Chunk, distance.label("distance")).join(Document).where(
                Document.id == document_id, Document.owner_id == owner, Document.status == "ready",
                Chunk.model == self.provider.embedding_model, Chunk.dimension == len(vector)
            ).order_by(distance).limit(4)).all()
            matches = [(chunk, 1 - float(score)) for chunk, score in rows if 1 - float(score) >= threshold]
            if not matches:
                raise ProviderError("指定文件沒有足夠相關內容，請換主題後明確重試")
            context = "\n\n".join(chunk.text for chunk, _ in matches)[:4000]
            citations = [Citation(title=title, document_id=document_id, chunk_id=chunk.id, score=score)
                         for chunk, score in matches]
            return context, SourceInfo(mode="document", citations=citations)

    def reserve_image(self, owner: str, body: AssetRequest, key: str) -> AssetResponse:
        with self.db.transaction() as session:
            return self.reserve_image_in_transaction(session, owner, body, key)

    def reserve_image_in_transaction(self, session: Session, owner: str, body: AssetRequest, key: str) -> AssetResponse:
        if not 1 <= len(key) <= 100:
            raise HTTPException(422, "需要有效的 Idempotency-Key")
        user = session.get(User, owner, with_for_update=True)
        if not user:
            raise HTTPException(401, "請先登入")
        existing = session.scalar(select(Asset).where(Asset.owner_id == owner, Asset.request_key == key))
        if existing:
            if existing.quiz_id != body.quiz_id or existing.prompt != body.prompt:
                raise HTTPException(409, "request key 內容不一致")
            return asset_response(existing)
        if not session.scalar(select(Quiz.id).where(Quiz.id == body.quiz_id, Quiz.owner_id == owner)):
            raise HTTPException(404, "找不到測驗")
        day = self.auth.now().replace(hour=0, minute=0, second=0, microsecond=0)
        daily = session.scalar(select(func.count()).select_from(Asset).where(Asset.owner_id == owner,
            Asset.created_at >= day, Asset.created_at < day + timedelta(days=1),
            or_(Asset.status.in_(["pending", "running"]), Asset.charged.is_(True)))) or 0
        active = session.scalar(select(func.count()).select_from(Asset).where(Asset.owner_id == owner,
            Asset.status.in_(["pending", "running"]))) or 0
        if daily >= self.settings.image_daily_limit or active >= self.settings.image_concurrency_limit:
            raise HTTPException(429, "圖片額度已用完或仍有圖片生成中")
        asset = Asset(id=new_id(), owner_id=owner, quiz_id=body.quiz_id, request_key=key,
            prompt=body.prompt, status="pending", created_at=self.auth.now())
        session.add(asset)
        session.flush()
        session.add(Job(owner_id=owner, request_scope_id=owner, request_key=f"image:{asset.id}", payload_hash=digest(asset.id),
            payload={"asset_id": asset.id}, kind="image", status="pending", created_at=self.auth.now()))
        return asset_response(asset)

    def image(self, owner: str, asset_id: str) -> AssetResponse:
        with self.db.transaction() as session:
            asset = session.scalar(select(Asset).where(Asset.id == asset_id, Asset.owner_id == owner))
            if not asset or asset.status == "deleted":
                raise HTTPException(404, "圖片不存在")
            return asset_response(asset)

    def image_path(self, owner: str, asset_id: str) -> Path:
        if self.image(owner, asset_id).status != "completed":
            raise HTTPException(409, "圖片尚未完成")
        path = self.path("images", asset_id)
        if not path.is_file():
            raise HTTPException(503, "圖片暫時不可讀取")
        return path

    def delete_image(self, owner: str, asset_id: str) -> None:
        with self.db.transaction() as session:
            session.get(Principal, owner, with_for_update=True)
            asset = session.scalar(select(Asset).where(Asset.id == asset_id,
                Asset.owner_id == owner).with_for_update())
            if not asset:
                raise HTTPException(404, "圖片不存在")
            asset.status = "deleted"
            for job in session.scalars(select(Job).where(Job.owner_id == owner, Job.kind == "image")):
                if job.payload.get("asset_id") == asset_id and job.status in {"pending", "running"}:
                    job.status, job.error, job.lease_until = "failed", "圖片已刪除", None
                    job.version += 1
        try:
            self.path("images", asset_id).unlink(missing_ok=True)
        except OSError:
            raise HTTPException(503, "圖片刪除暫時失敗，可再次重試") from None
