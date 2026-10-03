from datetime import timedelta
import io
import ipaddress
import os
import threading
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

from PIL import Image
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.auth import Auth
from app.db import Asset, Chunk, Database, Document, Job, Principal, Quiz, new_id
from app.files import parse_document
from app.providers import Provider, ProviderError
from app.resources import Resources
from app.schemas import AssetRequest, Citation, GenerateRequest, GeneratedQuiz, Plan, SourceInfo
from app.services import bounded_call
from app.settings import Settings


def validate_url(url: str) -> None:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if len(url) > 2000 or parsed.scheme not in {"https", "http"} or not host or parsed.username or parsed.password:
        raise ProviderError("只支援公開 HTTP／HTTPS 網址")
    if host.lower() == "localhost" or "." not in host or host.lower().endswith((".local", ".internal", ".localhost")):
        raise ProviderError("不允許私有或本機網址")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise ProviderError("不允許私有或本機網址")


class Worker:
    def __init__(self, db: Database, auth: Auth, provider: Provider, settings: Settings):
        self.db, self.auth, self.provider, self.settings = db, auth, provider, settings
        self.resources = Resources(db, auth, provider, settings)

    def recover(self) -> int:
        with self.db.transaction() as session:
            candidates = list(session.execute(select(Job.id, Job.owner_id).where(
                Job.status == "running", Job.lease_until <= self.auth.now())))
        recovered = 0
        for job_id, owner_id in candidates:
            with self.db.transaction() as session:
                owner = session.get(Principal, owner_id, with_for_update=True)
                job = session.get(Job, job_id, with_for_update=True, populate_existing=True)
                if not owner or not job or job.owner_id != owner_id or job.status != "running" or not job.lease_until or job.lease_until > self.auth.now():
                    continue
                job.status, job.error, job.lease_until = "failed", "任務執行中斷，請明確重試", None
                job.version += 1
                if job.kind == "document":
                    doc = session.get(Document, job.payload["document_id"])
                    if doc and doc.status in {"pending", "processing"}:
                        doc.status, doc.error = "failed", job.error
                if job.kind == "image":
                    asset = session.get(Asset, job.payload["asset_id"])
                    if asset and asset.status in {"pending", "running"}:
                        asset.status, asset.error = "failed", job.error
                recovered += 1
        return recovered

    def claim(self) -> tuple[str, int, str, str, dict[str, Any]] | None:
        with self.db.transaction() as session:
            job = session.scalar(select(Job).where(Job.status == "pending").order_by(
                Job.created_at, Job.id).with_for_update(skip_locked=True).limit(1))
            if not job:
                return None
            job.status = "running"
            job.version += 1
            job.lease_until = self.auth.now() + timedelta(seconds=self.settings.job_lease_seconds)
            return job.id, job.version, job.owner_id, job.kind, job.payload

    def heartbeat(self, job_id: str, version: int) -> bool:
        with self.db.transaction() as session:
            job = session.get(Job, job_id, with_for_update=True)
            if not job or job.status != "running" or job.version != version or not job.lease_until or job.lease_until <= self.auth.now():
                return False
            job.lease_until = self.auth.now() + timedelta(seconds=self.settings.job_lease_seconds)
            return True

    def knowledge(self, body: GenerateRequest, owner: str) -> tuple[str, SourceInfo]:
        if body.source_mode == "document":
            return self.resources.retrieve(owner, body.document_id or "", body.topic)
        if body.source_mode == "text":
            return "", SourceInfo(mode="text")
        context: list[dict[str, str]] = []
        calls = 0
        try:
            if body.source_mode == "url":
                validate_url(body.url or "")
                context = bounded_call(lambda deadline: self.provider.extract(body.url or "", deadline=deadline),
                                       self.settings.provider_timeout_seconds)
            else:
                for round_number in range(self.settings.max_planner_rounds):
                    plan = Plan.model_validate(bounded_call(lambda deadline: self.provider.plan(
                        body.topic, "\n".join(row["text"] for row in context)[:5000], round_number, deadline=deadline),
                        self.settings.provider_timeout_seconds))
                    if plan.action == "finish":
                        break
                    if calls >= self.settings.max_search_tools:
                        raise ProviderError("搜尋已達工具次數上限")
                    calls += 1
                    if plan.action == "extract":
                        validate_url(plan.query)
                        rows = bounded_call(lambda deadline: self.provider.extract(plan.query, deadline=deadline), self.settings.provider_timeout_seconds)
                    else:
                        rows = bounded_call(lambda deadline: self.provider.search(plan.query[:500], deadline=deadline), self.settings.provider_timeout_seconds)
                    context.extend(rows[:10])
                else:
                    raise ProviderError("搜尋已達規劃輪數上限")
            if not context or not any(row.get("text", "").strip() for row in context):
                raise ProviderError("沒有搜尋結果")
            citations = [Citation(title=row["title"], url=row["url"]) for row in context[:10]]
            text = "\n\n".join(row["text"] for row in context)[:5000]
            return text, SourceInfo(mode=body.source_mode, citations=citations)
        except (ProviderError, ValidationError, KeyError):
            return "", SourceInfo(mode=body.source_mode, degraded=True,
                message="搜尋／網址提取不可用，本次改用模型一般知識；不是指定來源出題")

    def process(self, kind: str, owner: str, payload: dict[str, Any]) -> object:
        if kind == "quiz":
            body = GenerateRequest.model_validate(payload)
            context, source = self.knowledge(body, owner)
            raw = bounded_call(lambda deadline: self.provider.generate(body, context, deadline=deadline), self.settings.provider_timeout_seconds)
            quiz = GeneratedQuiz.model_validate(raw)
            if len(quiz.questions) != body.question_count or any(q.type not in body.question_types for q in quiz.questions):
                raise ProviderError("題數或題型與要求不一致")
            return (quiz, source)
        if kind == "document":
            with self.db.transaction() as session:
                doc = session.scalar(select(Document).where(Document.id == payload["document_id"], Document.owner_id == owner))
                if not doc or doc.status not in {"pending", "processing"}:
                    raise ProviderError("文件已刪除或不可處理")
                filename = doc.filename
            pieces = parse_document(filename, self.resources.path("documents", payload["document_id"]).read_bytes(), self.settings)
            return (pieces, self.resources.vectors(pieces))
        if kind == "image":
            with self.db.transaction() as session:
                asset = session.scalar(select(Asset).where(Asset.id == payload["asset_id"], Asset.owner_id == owner))
                if not asset or asset.status != "pending":
                    raise ProviderError("圖片已取消")
                prompt = asset.prompt
            raw_image = bounded_call(lambda deadline: self.provider.image(prompt, deadline=deadline), self.settings.provider_timeout_seconds)
            if len(raw_image) > 4 * 1024 * 1024:
                raise ProviderError("圖片超過大小限制")
            with Image.open(io.BytesIO(raw_image)) as image:
                if image.width > 2048 or image.height > 2048:
                    raise ProviderError("圖片超過尺寸限制")
                output = io.BytesIO()
                image.convert("RGB").save(output, format="PNG")
                return output.getvalue()
        raise ProviderError("未知任務類型")

    def finish(self, job_id: str, version: int, result: Any = None, error: str | None = None) -> bool:
        final_path = None
        staging = None
        try:
            with self.db.transaction() as session:
                snapshot = session.get(Job, job_id)
                if not snapshot:
                    return False
                owner = session.get(Principal, snapshot.owner_id, with_for_update=True)
                job = session.get(Job, job_id, with_for_update=True, populate_existing=True)
                if not owner or not job or job.owner_id != owner.id or job.status != "running" or job.version != version or not job.lease_until or job.lease_until <= self.auth.now():
                    return False
                if owner.kind == "guest" and (not owner.expires_at or owner.expires_at <= self.auth.now() or owner.claimed_by):
                    error = "訪客 session 已過期或轉移，請重新開始"
                if job.kind == "quiz" and not error:
                    quiz, source = result
                    record = Quiz(id=new_id(), owner_id=job.owner_id, topic=job.payload["topic"],
                        questions=[q.model_dump() for q in quiz.questions], source=source.model_dump(),
                        created_at=self.auth.now(), experience_awarded=0)
                    session.add(record)
                    if job.payload.get("include_images"):
                        try:
                            with session.begin_nested():
                                self.resources.reserve_image_in_transaction(session, job.owner_id,
                                    AssetRequest(quiz_id=record.id, prompt=job.payload["topic"][:4000]), f"auto:{record.id}")
                        except HTTPException:
                            source.image_message = "配圖額度不足或無法啟動，測驗仍可使用；稍後可手動生成配圖"
                            record.source = source.model_dump()
                    job.result_id = record.id
                elif job.kind == "document":
                    doc = session.get(Document, job.payload["document_id"], with_for_update=True)
                    if not doc or doc.owner_id != job.owner_id or doc.status not in {"pending", "processing"}:
                        error = "文件已刪除或停止處理"
                    elif error:
                        doc.status, doc.error = "failed", error
                    else:
                        pieces, vectors = result
                        for i, (text, vector) in enumerate(zip(pieces, vectors, strict=True)):
                            session.add(Chunk(document_id=doc.id, position=i, text=text, embedding=vector,
                                model=self.provider.embedding_model, dimension=len(vector)))
                        doc.status, doc.error, doc.chunk_count = "ready", None, len(pieces)
                        job.result_id = doc.id
                elif job.kind == "image":
                    asset = session.get(Asset, job.payload["asset_id"], with_for_update=True)
                    if not asset or asset.owner_id != job.owner_id or asset.status not in {"pending", "running"}:
                        error = "圖片已刪除或停止處理"
                    elif error:
                        asset.status, asset.error = "failed", error
                    else:
                        self.resources.lock_file(session, asset.id)
                        final_path = self.resources.path("images", asset.id)
                        final_path.parent.mkdir(parents=True, exist_ok=True)
                        staging = final_path.with_name(f"{asset.id}.{version}.staging")
                        staging.write_bytes(result)
                        os.replace(staging, final_path)
                        asset.status, asset.error, asset.charged = "completed", None, True
                        job.result_id = asset.id
                job.status, job.error, job.lease_until = ("failed" if error else "completed"), error, None
                return True
        except Exception:
            for path in (staging, final_path):
                if path:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass
            raise

    def run_once(self) -> bool:
        self.recover()
        claimed = self.claim()
        if not claimed:
            return False
        job_id, version, owner, kind, payload = claimed
        stop = threading.Event()
        deadline = monotonic() + 240

        def renew() -> None:
            while not stop.wait(max(1, self.settings.job_lease_seconds // 3)):
                if monotonic() >= deadline or not self.heartbeat(job_id, version):
                    return

        thread = threading.Thread(target=renew, daemon=True)
        thread.start()
        try:
            try:
                result = self.process(kind, owner, payload)
            except ProviderError as exc:
                self.finish(job_id, version, error=str(exc))
                return True
            except Exception:
                self.finish(job_id, version, error="處理失敗：請檢查輸入／服務後明確重試")
                return True
            try:
                if not self.finish(job_id, version, result=result):
                    return True
            except OSError:
                self.finish(job_id, version, error="資源轉存失敗，請稍後明確重試")
            return True
        finally:
            stop.set()
            thread.join(timeout=2)


def main() -> None:
    from app.providers import configured_provider
    from app.settings import from_environment
    settings = from_environment()
    db = Database(settings.database_url)
    auth = Auth(db, settings)
    worker = Worker(db, auth, configured_provider(settings.provider_mode), settings)
    try:
        count = 0
        while True:
            if not worker.run_once():
                threading.Event().wait(0.5)
            count += 1
            if count % 120 == 0:
                auth.cleanup()
                worker.resources.reconcile_files()
    except KeyboardInterrupt:
        pass
    finally:
        db.close()


if __name__ == "__main__":
    main()
