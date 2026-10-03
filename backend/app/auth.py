from collections.abc import Callable
from datetime import datetime, timedelta, UTC
from hashlib import sha256
from secrets import token_urlsafe
from time import time

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
from fastapi import HTTPException, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import AuthSession, Database, Job, Principal, Quiz, RateBucket, User
from app.schemas import ClaimResponse, LoginRequest, ProfileResponse, RegisterRequest
from app.settings import Settings

GUEST_COOKIE = "ai_learn_guest"
LOGIN_COOKIE = "ai_learn_auth"
HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY_HASH = HASHER.hash("not-a-real-account-password")


def digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


class Auth:
    def __init__(self, db: Database, settings: Settings, clock: Callable[[], float] = time):
        self.db, self.settings, self.clock = db, settings, clock

    def now(self) -> datetime:
        return datetime.fromtimestamp(self.clock(), UTC)

    def cookie(self, response: Response, name: str, value: str, seconds: int) -> None:
        response.set_cookie(name, value, max_age=seconds, httponly=True, samesite="lax",
                            secure=self.settings.secure_cookie, path="/api")

    def resolve_cookie(self, session: Session, token: str | None, kind: str) -> Principal | None:
        if not token:
            return None
        principal = session.scalar(select(Principal).join(AuthSession).where(
            AuthSession.token_hash == digest(token), AuthSession.expires_at > self.now(),
            Principal.kind == kind))
        if principal and kind == "guest" and (principal.expires_at is None or
                principal.expires_at <= self.now() or principal.claimed_by is not None):
            return None
        return principal

    def owner(self, request: Request, response: Response | None = None, create: bool = False,
              require_user: bool = False) -> str:
        with self.db.transaction() as session:
            user = self.resolve_cookie(session, request.cookies.get(LOGIN_COOKIE), "user")
            if user:
                return user.id
            if require_user:
                raise HTTPException(401, "請先登入")
            guest = self.resolve_cookie(session, request.cookies.get(GUEST_COOKIE), "guest")
            if guest:
                return guest.id
            if not create or response is None:
                raise HTTPException(401, "請開始新練習或登入")
            principal = Principal(kind="guest", created_at=self.now(),
                                  expires_at=self.now() + timedelta(seconds=self.settings.guest_seconds))
            session.add(principal)
            session.flush()
            token = token_urlsafe(32)
            session.add(AuthSession(token_hash=digest(token), principal_id=principal.id,
                                    expires_at=principal.expires_at))
            self.cookie(response, GUEST_COOKIE, token, self.settings.guest_seconds)
            return principal.id

    def rate_limit(self, request: Request, email: str, action: str) -> None:
        minute = int(self.clock() // 60)
        ip = request.client.host if request.client else "unknown"
        keys = [digest(f"{action}:{ip}:{minute}"), digest(f"{action}:{email.lower()}:{minute}")]
        with self.db.transaction() as session:
            counts = []
            for key in keys:
                statement = insert(RateBucket).values(key=key, hits=1,
                    expires_at=self.now() + timedelta(minutes=2)).on_conflict_do_update(
                    index_elements=[RateBucket.key], set_={"hits": RateBucket.hits + 1}).returning(RateBucket.hits)
                counts.append(session.scalar(statement) or 0)
        if any(count > 10 for count in counts):
            raise HTTPException(429, "嘗試次數過多，請稍後再試")

    def login_session(self, session: Session, user_id: str, request: Request, response: Response) -> None:
        previous = request.cookies.get(LOGIN_COOKIE)
        if previous:
            session.execute(delete(AuthSession).where(AuthSession.token_hash == digest(previous)))
        token = token_urlsafe(32)
        session.add(AuthSession(token_hash=digest(token), principal_id=user_id,
                                expires_at=self.now() + timedelta(seconds=self.settings.login_seconds)))
        self.cookie(response, LOGIN_COOKIE, token, self.settings.login_seconds)

    def register(self, body: RegisterRequest, request: Request, response: Response) -> str:
        email = str(body.email).lower()
        self.rate_limit(request, email, "register")
        password_hash = HASHER.hash(body.password)
        try:
            with self.db.transaction() as session:
                principal = Principal(kind="user", created_at=self.now())
                session.add(principal)
                session.flush()
                session.add(User(id=principal.id, email=email, password_hash=password_hash,
                                 nickname=body.nickname, avatar_url="", experience=0))
                session.flush()
                self.login_session(session, principal.id, request, response)
                return principal.id
        except IntegrityError:
            raise HTTPException(409, "此 Email 無法註冊，請登入或使用其他 Email") from None

    def login(self, body: LoginRequest, request: Request, response: Response) -> str:
        email = str(body.email).lower()
        self.rate_limit(request, email, "login")
        with self.db.transaction() as session:
            user = session.scalar(select(User).where(User.email == email))
            valid: bool
            try:
                valid = HASHER.verify(user.password_hash if user else DUMMY_HASH, body.password)
            except (VerifyMismatchError, VerificationError):
                valid = False
            if not valid or not user:
                raise HTTPException(401, "Email 或密碼不正確")
            if HASHER.check_needs_rehash(user.password_hash):
                user.password_hash = HASHER.hash(body.password)
            self.login_session(session, user.id, request, response)
            return user.id

    def profile(self, user_id: str) -> ProfileResponse:
        with self.db.transaction() as session:
            user = session.get(User, user_id)
            if user is None:
                raise HTTPException(401, "請先登入")
            count = session.scalar(select(func.count()).select_from(Quiz).where(
                Quiz.owner_id == user.id, Quiz.experience_awarded > 0)) or 0
            return ProfileResponse(id=user.id, email=user.email, nickname=user.nickname,
                avatar_url=user.avatar_url, experience=user.experience, level=1 + user.experience // 100,
                completed_quizzes=count)

    def claim(self, user_id: str, guest_token: str | None) -> ClaimResponse:
        with self.db.transaction() as session:
            user = session.get(User, user_id, with_for_update=True)
            guest = self.resolve_cookie(session, guest_token, "guest")
            if not user or not guest:
                raise HTTPException(409, "沒有可認領的訪客紀錄")
            guest = session.get(Principal, guest.id, with_for_update=True, populate_existing=True)
            if not guest or guest.claimed_by is not None or not guest.expires_at or guest.expires_at <= self.now():
                raise HTTPException(409, "訪客紀錄已認領或過期")
            quizzes = list(session.scalars(select(Quiz).where(Quiz.owner_id == guest.id).with_for_update()))
            experience = sum(q.experience_awarded for q in quizzes)
            for quiz in quizzes:
                quiz.owner_id = user_id
            jobs = list(session.scalars(select(Job).where(Job.owner_id == guest.id).with_for_update()))
            for job in jobs:
                job.owner_id = user_id
            user.experience += experience
            guest.claimed_by = user_id
            session.execute(delete(AuthSession).where(AuthSession.principal_id == guest.id))
            return ClaimResponse(quizzes=len(quizzes), experience=experience, jobs=len(jobs))

    def cleanup(self) -> int:
        with self.db.transaction() as session:
            session.execute(delete(AuthSession).where(AuthSession.expires_at <= self.now()))
            session.execute(delete(RateBucket).where(RateBucket.expires_at <= self.now()))
            ids = list(session.scalars(select(Principal.id).where(
                Principal.kind == "guest", Principal.expires_at <= self.now()).with_for_update()))
            if ids:
                session.execute(delete(Principal).where(Principal.id.in_(ids)))
            return len(ids)
