from collections.abc import Callable
import json
from time import monotonic

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from app.auth import Auth, digest
from app.db import Answer, Database, Job, Principal, Quiz, Report, User
from app.providers import Provider, ProviderError
from app.schemas import (AnswerRequest, AnswerResponse, GenerateRequest, HistoryItem, HistoryResponse, InternalQuestion, JobResponse, PublicQuestion, QuizResponse,
    ReportNarrative, ReportResponse, SourceInfo)
from app.settings import Settings

def bounded_call[T](function: Callable[[float], T], timeout: float) -> T:
    deadline = monotonic() + timeout
    try:
        value = function(deadline)
    except ProviderError:
        raise
    except Exception:
        raise ProviderError("服務暫時無法使用，請重試") from None
    if monotonic() >= deadline:
        raise ProviderError("服務逾時，請明確重試")
    return value


def public_quiz(quiz: Quiz, answered: list[str], image_ids: list[str] | None = None) -> QuizResponse:
    return QuizResponse(id=quiz.id, topic=quiz.topic,
        questions=[PublicQuestion.model_validate({key: q[key] for key in ("id", "type", "text", "options")})
                   for q in quiz.questions], source=SourceInfo.model_validate(quiz.source),
        answered=answered, image_ids=image_ids or [])


def job_response(job: Job) -> JobResponse:
    return JobResponse(id=job.id, status=job.status, result_id=job.result_id, error=job.error, kind=job.kind)  # type: ignore[arg-type]


class Learning:
    def __init__(self, db: Database, auth: Auth, provider: Provider, settings: Settings):
        self.db, self.auth, self.provider, self.settings = db, auth, provider, settings

    def create_job(self, owner: str, body: GenerateRequest, key: str, retry_of: str | None = None) -> JobResponse:
        if not 1 <= len(key) <= 100:
            raise HTTPException(422, "需要 1–100 字元的 Idempotency-Key")
        payload = body.model_dump()
        hashed = digest(json.dumps(payload, sort_keys=True, ensure_ascii=False))
        with self.db.transaction() as session:
            principal = session.get(Principal, owner, with_for_update=True)
            if not principal:
                raise HTTPException(401, "session 已失效")
            if (body.source_mode == "document" or body.include_images) and principal.kind != "user":
                raise HTTPException(401, "私有文件與配圖需要登入")
            existing = session.scalar(select(Job).where(Job.owner_id == owner, Job.request_scope_id == owner, Job.request_key == key))
            if existing:
                if existing.payload_hash != hashed:
                    raise HTTPException(409, "同一 request key 不可更改內容")
                return job_response(existing)
            if retry_of:
                old = session.scalar(select(Job).where(Job.id == retry_of, Job.owner_id == owner).with_for_update())
                if not old:
                    raise HTTPException(404, "找不到任務")
                if old.status != "failed" or old.kind != "quiz":
                    raise HTTPException(409, "只能明確重試失敗的出題任務")
            job = Job(owner_id=owner, request_scope_id=owner, request_key=key, payload_hash=hashed, payload=payload,
                kind="quiz", status="pending", created_at=self.auth.now(), retry_of=retry_of)
            session.add(job)
            session.flush()
            return job_response(job)

    def get_job(self, owner: str, job_id: str) -> JobResponse:
        with self.db.transaction() as session:
            job = session.scalar(select(Job).where(Job.owner_id == owner, Job.id == job_id))
            if not job:
                raise HTTPException(404, "找不到任務")
            return job_response(job)

    def get_quiz(self, owner: str, quiz_id: str) -> QuizResponse:
        from app.db import Asset
        with self.db.transaction() as session:
            quiz = session.scalar(select(Quiz).where(Quiz.id == quiz_id, Quiz.owner_id == owner))
            if not quiz:
                raise HTTPException(404, "找不到測驗")
            answered = list(session.scalars(select(Answer.question_id).where(Answer.quiz_id == quiz_id)))
            images = list(session.scalars(select(Asset.id).where(Asset.quiz_id == quiz_id,
                Asset.owner_id == owner, Asset.status != "deleted")))
            return public_quiz(quiz, answered, images)

    def answer(self, owner: str, quiz_id: str, body: AnswerRequest) -> AnswerResponse:
        with self.db.transaction() as session:
            principal = session.get(Principal, owner, with_for_update=True)
            if not principal or (principal.kind == "guest" and (principal.claimed_by or
                    not principal.expires_at or principal.expires_at <= self.auth.now())):
                raise HTTPException(401, "session 已失效")
            user = session.get(User, owner, with_for_update=True) if principal.kind == "user" else None
            quiz = session.scalar(select(Quiz).where(Quiz.id == quiz_id, Quiz.owner_id == owner).with_for_update())
            if not quiz:
                raise HTTPException(404, "找不到測驗")
            question_data = next((q for q in quiz.questions if q["id"] == body.question_id), None)
            if not question_data:
                raise HTTPException(422, "題目不屬於此測驗")
            question = InternalQuestion.model_validate(question_data)
            selected = sorted(body.selected_answers)
            valid = {option.id for option in question.options}
            if len(selected) != len(set(selected)) or not set(selected) <= valid:
                raise HTTPException(422, "選項無效或重複")
            if question.type != "multiple" and len(selected) != 1:
                raise HTTPException(422, "此題只能選一項")
            existing = session.scalar(select(Answer).where(Answer.quiz_id == quiz_id, Answer.question_id == question.id))
            if existing:
                answer = AnswerResponse.model_validate(existing.data)
                if answer.selected_answers != selected:
                    raise HTTPException(409, "此題已提交，不能更改答案")
                return answer
            result = AnswerResponse(question_id=question.id, selected_answers=selected,
                is_correct=set(selected) == set(question.correct_answers), correct_answers=question.correct_answers,
                explanation=question.explanation, knowledge_points=question.knowledge_points,
                duration_ms=body.duration_ms)
            session.add(Answer(quiz_id=quiz_id, question_id=question.id, data=result.model_dump()))
            session.flush()
            answers = list(session.scalars(select(Answer).where(Answer.quiz_id == quiz_id)))
            if len(answers) == len(quiz.questions) and quiz.experience_awarded == 0:
                experience = 10 + 5 * sum(a.data["is_correct"] for a in answers)
                quiz.experience_awarded = experience
                if user:
                    user.experience += experience
            return result

    def report(self, owner: str, quiz_id: str) -> ReportResponse:
        with self.db.transaction() as session:
            quiz = session.scalar(select(Quiz).where(Quiz.id == quiz_id, Quiz.owner_id == owner))
            if not quiz:
                raise HTTPException(404, "找不到測驗")
            records = list(session.scalars(select(Answer).where(Answer.quiz_id == quiz_id)))
            if len(records) != len(quiz.questions):
                raise HTTPException(409, "請先完成全部題目")
            answers = [AnswerResponse.model_validate(a.data) for a in records]
            report = session.get(Report, quiz_id)
            existing = report.narrative if report else None
            topic = quiz.topic
            experience = quiz.experience_awarded
        if existing is None:
            try:
                raw = bounded_call(lambda deadline: self.provider.report(topic, [a.model_dump() for a in answers], deadline=deadline),
                                   self.settings.provider_timeout_seconds)
                narrative = ReportNarrative.model_validate(raw)
            except (ValidationError, ProviderError):
                raise HTTPException(502, "報告暫時無法產生，可再次重試；答題紀錄已保存") from None
            with self.db.transaction() as session:
                current = session.scalar(select(Quiz).where(Quiz.id == quiz_id, Quiz.owner_id == owner).with_for_update())
                if not current:
                    raise HTTPException(404, "找不到測驗")
                stored = session.get(Report, quiz_id)
                if stored is None:
                    session.add(Report(quiz_id=quiz_id, narrative=narrative.model_dump()))
                else:
                    narrative = ReportNarrative.model_validate(stored.narrative)
        else:
            narrative = ReportNarrative.model_validate(existing)
        correct = sum(answer.is_correct for answer in answers)
        return ReportResponse(quiz_id=quiz_id, total=len(answers), correct=correct,
            accuracy=round(correct / len(answers) * 100, 2), experience=experience,
            duration_ms=sum(a.duration_ms for a in answers), narrative=narrative, answers=answers)

    def history(self, owner: str, page: int, page_size: int) -> HistoryResponse:
        with self.db.transaction() as session:
            total = session.scalar(select(func.count()).select_from(Quiz).where(Quiz.owner_id == owner)) or 0
            quizzes = session.scalars(select(Quiz).where(Quiz.owner_id == owner).order_by(
                Quiz.created_at.desc(), Quiz.id).offset((page - 1) * page_size).limit(page_size))
            items = [HistoryItem(id=q.id, topic=q.topic, created_at=q.created_at.isoformat(),
                answered=session.scalar(select(func.count()).select_from(Answer).where(Answer.quiz_id == q.id)) or 0,
                total=len(q.questions), report_ready=session.get(Report, q.id) is not None) for q in quizzes]
            return HistoryResponse(items=items, total=total, page=page, page_size=page_size)
