from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from time import time
from typing import Annotated

from fastapi import FastAPI, File, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy import delete, func, select
from starlette.middleware.base import RequestResponseEndpoint
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth import Auth, GUEST_COOKIE, LOGIN_COOKIE, digest
from app.db import AuthSession, Database, Job, Quiz, User
from app.providers import Provider, ProviderError, configured_provider
from app.resources import Resources
from app.schemas import (AnswerRequest, AnswerResponse, AssetRequest, AssetResponse, ClaimResponse,
    DocumentResponse, EmptyRequest, GenerateRequest, HistoryResponse, JobResponse, LoginRequest,
    ProfileResponse, ProfileUpdate, QuizResponse, RegisterRequest, ReportResponse, ResourceId, SessionResponse)
from app.services import Learning
from app.settings import Settings, from_environment
from app.worker import Worker, validate_url


class BodyTooLarge(Exception):
    pass


class BodyLimit:
    def __init__(self, app: ASGIApp, limit: int):
        self.app, self.limit = app, limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        count = 0

        async def bounded_receive() -> Message:
            nonlocal count
            message = await receive()
            count += len(message.get("body", b""))
            if count > self.limit:
                raise BodyTooLarge
            return message

        try:
            await self.app(scope, bounded_receive, send)
        except BodyTooLarge:
            await JSONResponse({"detail": "請求超過大小限制"}, status_code=413)(scope, receive, send)


def create_app(provider: Provider | None = None, clock: Callable[[], float] = time,
               settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    config = settings or from_environment()
    db = database or Database(config.database_url)
    adapter = provider or configured_provider(config.provider_mode)
    auth = Auth(db, config, clock)
    learning = Learning(db, auth, adapter, config)
    resources = Resources(db, auth, adapter, config)
    worker = Worker(db, auth, adapter, config)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        yield
        if database is None:
            db.close()

    app = FastAPI(title="AI Learn Web", version="1.0.0", lifespan=lifespan)
    app.state.db, app.state.auth, app.state.learning = db, auth, learning
    app.state.resources, app.state.worker, app.state.settings = resources, worker, config
    app.add_middleware(BodyLimit, limit=config.max_file_bytes + 65536)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Validation errors must not echo passwords, private documents or prompts.
        return JSONResponse({"detail": [{"loc": list(error["loc"]), "type": error["type"],
                                         "msg": "輸入格式或欄位限制不符"}
                                        for error in exc.errors()]}, status_code=422)

    @app.middleware("http")
    async def csrf(request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("origin") not in config.origins:
                return JSONResponse({"detail": "不允許的請求來源"}, status_code=403)
            content_type = request.headers.get("content-type", "").split(";", 1)[0]
            upload = request.method == "POST" and request.url.path == "/api/v1/documents"
            if content_type != "application/json" and not (upload and content_type == "multipart/form-data"):
                return JSONResponse({"detail": "只接受 JSON；文件上傳使用 multipart"}, status_code=415)
        return await call_next(request)

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "provider": config.provider_mode}

    @app.get("/api/v1/session", response_model=SessionResponse)
    def session_info(request: Request, response: Response) -> SessionResponse:
        owner = auth.owner(request, response, create=True)
        with db.transaction() as session:
            user = session.get(User, owner) is not None
            guest = auth.resolve_cookie(session, request.cookies.get(GUEST_COOKIE), "guest")
            count = session.scalar(select(func.count()).select_from(Quiz).where(Quiz.owner_id == guest.id)) if guest else 0
            jobs = session.scalar(select(func.count()).select_from(Job).where(Job.owner_id == guest.id)) if guest else 0
        return SessionResponse(authenticated=user, profile=auth.profile(owner) if user else None,
            claimable_quizzes=count or 0, claimable_jobs=jobs or 0, provider_mode=config.provider_mode)

    @app.post("/api/v1/auth/register", response_model=ProfileResponse, status_code=201)
    def register(body: RegisterRequest, request: Request, response: Response) -> ProfileResponse:
        return auth.profile(auth.register(body, request, response))

    @app.post("/api/v1/auth/login", response_model=ProfileResponse)
    def login(body: LoginRequest, request: Request, response: Response) -> ProfileResponse:
        return auth.profile(auth.login(body, request, response))

    @app.post("/api/v1/auth/logout", status_code=204)
    def logout(body: EmptyRequest, request: Request, response: Response) -> None:
        token = request.cookies.get(LOGIN_COOKIE)
        if token:
            with db.transaction() as session:
                session.execute(delete(AuthSession).where(AuthSession.token_hash == digest(token)))
        response.delete_cookie(LOGIN_COOKIE, path="/api", httponly=True, samesite="lax", secure=config.secure_cookie)

    @app.post("/api/v1/auth/claim", response_model=ClaimResponse)
    def claim(body: EmptyRequest, request: Request, response: Response) -> ClaimResponse:
        result = auth.claim(auth.owner(request, require_user=True), request.cookies.get(GUEST_COOKIE))
        response.delete_cookie(GUEST_COOKIE, path="/api")
        return result

    @app.get("/api/v1/user/profile", response_model=ProfileResponse)
    def profile(request: Request) -> ProfileResponse:
        return auth.profile(auth.owner(request, require_user=True))

    @app.put("/api/v1/user/profile", response_model=ProfileResponse)
    def update_profile(body: ProfileUpdate, request: Request) -> ProfileResponse:
        owner = auth.owner(request, require_user=True)
        with db.transaction() as session:
            user = session.get(User, owner, with_for_update=True)
            if not user:
                raise HTTPException(401, "請先登入")
            user.nickname, user.avatar_url = body.nickname, str(body.avatar_url) if body.avatar_url else ""
        return auth.profile(owner)

    @app.post("/api/v1/quiz/generate", response_model=JobResponse, status_code=202)
    def generate(body: GenerateRequest, request: Request, response: Response,
                 key: Annotated[str, Header(alias="Idempotency-Key")]) -> JobResponse:
        owner = auth.owner(request, response, create=True)
        if body.url:
            try:
                validate_url(body.url)
            except ProviderError:
                raise HTTPException(422, "不允許私有或無效網址") from None
        return learning.create_job(owner, body, key)

    @app.get("/api/v1/jobs/{job_id}", response_model=JobResponse)
    def get_job(job_id: ResourceId, request: Request) -> JobResponse:
        return learning.get_job(auth.owner(request), job_id)

    @app.post("/api/v1/jobs/{job_id}/retry", response_model=JobResponse, status_code=202)
    def retry_job(job_id: ResourceId, body: EmptyRequest, request: Request,
                  key: Annotated[str, Header(alias="Idempotency-Key")]) -> JobResponse:
        from app.db import Job
        owner = auth.owner(request)
        with db.transaction() as session:
            old = session.scalar(select(Job).where(Job.id == job_id, Job.owner_id == owner))
            if not old:
                raise HTTPException(404, "找不到任務")
            if old.kind != "quiz" or old.status != "failed":
                raise HTTPException(409, "只有失敗的出題任務可在此重試")
            payload = GenerateRequest.model_validate(old.payload)
        return learning.create_job(owner, payload, key, retry_of=job_id)

    @app.get("/api/v1/quiz/{quiz_id}", response_model=QuizResponse)
    def quiz(quiz_id: ResourceId, request: Request) -> QuizResponse:
        return learning.get_quiz(auth.owner(request), quiz_id)

    @app.post("/api/v1/quiz/{quiz_id}/answers", response_model=AnswerResponse)
    def answer(quiz_id: ResourceId, body: AnswerRequest, request: Request) -> AnswerResponse:
        return learning.answer(auth.owner(request), quiz_id, body)

    @app.post("/api/v1/quiz/{quiz_id}/report", response_model=ReportResponse)
    def report(quiz_id: ResourceId, body: EmptyRequest, request: Request) -> ReportResponse:
        return learning.report(auth.owner(request), quiz_id)

    @app.get("/api/v1/user/quizzes", response_model=HistoryResponse)
    def history(request: Request, page: Annotated[int, Query(ge=1)] = 1,
                page_size: Annotated[int, Query(ge=1, le=50)] = 10) -> HistoryResponse:
        return learning.history(auth.owner(request), page, page_size)

    @app.post("/api/v1/documents", response_model=DocumentResponse, status_code=202)
    def upload(request: Request, file: Annotated[UploadFile, File()]) -> DocumentResponse:
        owner = auth.owner(request, require_user=True)
        data = file.file.read(config.max_file_bytes + 1)
        return resources.upload(owner, file.filename or "document.txt", data)

    @app.get("/api/v1/documents", response_model=list[DocumentResponse])
    def documents(request: Request) -> list[DocumentResponse]:
        return resources.documents(auth.owner(request, require_user=True))

    @app.get("/api/v1/documents/{document_id}", response_model=DocumentResponse)
    def document(document_id: ResourceId, request: Request) -> DocumentResponse:
        return resources.document(auth.owner(request, require_user=True), document_id)

    @app.delete("/api/v1/documents/{document_id}", status_code=204)
    def delete_document(document_id: ResourceId, body: EmptyRequest, request: Request) -> None:
        resources.delete_document(auth.owner(request, require_user=True), document_id)

    @app.post("/api/v1/documents/{document_id}/retry", response_model=DocumentResponse)
    def retry_document(document_id: ResourceId, body: EmptyRequest, request: Request) -> DocumentResponse:
        return resources.retry_document(auth.owner(request, require_user=True), document_id)

    @app.post("/api/v1/assets", response_model=AssetResponse, status_code=202)
    def image(body: AssetRequest, request: Request,
              key: Annotated[str, Header(alias="Idempotency-Key")]) -> AssetResponse:
        return resources.reserve_image(auth.owner(request, require_user=True), body, key)

    @app.get("/api/v1/assets/{asset_id}", response_model=AssetResponse)
    def image_info(asset_id: ResourceId, request: Request) -> AssetResponse:
        return resources.image(auth.owner(request, require_user=True), asset_id)

    @app.get("/api/v1/assets/{asset_id}/content")
    def image_content(asset_id: ResourceId, request: Request) -> FileResponse:
        path = resources.image_path(auth.owner(request, require_user=True), asset_id)
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, no-store"})

    @app.delete("/api/v1/assets/{asset_id}", status_code=204)
    def delete_image(asset_id: ResourceId, body: EmptyRequest, request: Request) -> None:
        resources.delete_image(auth.owner(request, require_user=True), asset_id)

    return app


app = create_app()
