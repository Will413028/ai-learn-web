from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, model_validator

QuestionType = Literal["single", "multiple", "boolean"]
ResourceId = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")]


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EmptyRequest(Schema):
    pass


class GenerateRequest(Schema):
    topic: Annotated[str, Field(min_length=1, max_length=12000)]
    question_count: Annotated[int, Field(ge=1, le=10)] = 3
    question_types: Annotated[list[QuestionType], Field(min_length=1, max_length=3)] = ["single", "multiple", "boolean"]
    source_mode: Literal["text", "search", "url", "document"] = "text"
    url: str | None = None
    document_id: ResourceId | None = None
    include_images: bool = False

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if not self.topic.strip() or len(set(self.question_types)) != len(self.question_types):
            raise ValueError("題目主題／類型無效")
        if self.source_mode == "document" and not self.document_id:
            raise ValueError("請指定文件")
        if self.source_mode == "url" and not self.url:
            raise ValueError("請指定網址")
        if self.source_mode != "document" and self.document_id:
            raise ValueError("文件模式與指定文件不一致")
        if self.source_mode != "url" and self.url:
            raise ValueError("網址模式與網址不一致")
        return self


class Option(Schema):
    id: Annotated[str, Field(min_length=1, max_length=10)]
    text: Annotated[str, Field(min_length=1, max_length=1000)]


class PublicQuestion(Schema):
    id: Annotated[str, Field(min_length=1, max_length=36)]
    type: QuestionType
    text: Annotated[str, Field(min_length=1, max_length=3000)]
    options: Annotated[list[Option], Field(min_length=2, max_length=6)]


class InternalQuestion(PublicQuestion):
    correct_answers: Annotated[list[str], Field(min_length=1, max_length=6)]
    explanation: Annotated[str, Field(min_length=1, max_length=5000)]
    knowledge_points: Annotated[list[str], Field(min_length=1, max_length=10)]

    @model_validator(mode="after")
    def consistent(self) -> Self:
        ids = [option.id for option in self.options]
        correct = self.correct_answers
        if len(ids) != len(set(ids)) or len(correct) != len(set(correct)) or not set(correct) <= set(ids):
            raise ValueError("選項／答案無效")
        if self.type in {"single", "boolean"} and len(correct) != 1:
            raise ValueError("單選與判斷須有一個答案")
        if self.type == "multiple" and len(correct) < 2:
            raise ValueError("多選須有多個答案")
        if self.type == "boolean" and set(ids) != {"T", "F"}:
            raise ValueError("判斷選項須為 T／F")
        return self


class GeneratedQuiz(Schema):
    questions: Annotated[list[InternalQuestion], Field(min_length=1, max_length=10)]

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        if len({q.id for q in self.questions}) != len(self.questions):
            raise ValueError("題目 ID 重複")
        return self


class Citation(Schema):
    title: str
    url: str | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    score: float | None = None


class SourceInfo(Schema):
    mode: Literal["text", "search", "url", "document"]
    degraded: bool = False
    message: str = ""
    image_message: str = ""
    citations: list[Citation] = []


class QuizResponse(Schema):
    id: str
    topic: str
    questions: list[PublicQuestion]
    source: SourceInfo
    answered: list[str] = []
    image_ids: list[str] = []


class AnswerRequest(Schema):
    question_id: str
    selected_answers: Annotated[list[str], Field(min_length=1, max_length=6)]
    duration_ms: Annotated[int, Field(ge=0, le=86400000)]


class AnswerResponse(Schema):
    question_id: str
    selected_answers: list[str]
    is_correct: bool
    correct_answers: list[str]
    explanation: str
    knowledge_points: list[str]
    duration_ms: int


class ReportNarrative(Schema):
    summary: Annotated[str, Field(min_length=1, max_length=5000)]
    mastery: dict[str, str]
    weaknesses: list[str]
    suggestions: list[str]
    share_quote: Annotated[str, Field(min_length=1, max_length=300)]


class ReportResponse(Schema):
    quiz_id: str
    total: int
    correct: int
    accuracy: float
    experience: int
    duration_ms: int
    narrative: ReportNarrative
    answers: list[AnswerResponse]


class RegisterRequest(Schema):
    email: EmailStr
    password: Annotated[str, Field(min_length=12, max_length=128)]
    nickname: Annotated[str, Field(min_length=1, max_length=80)]


class LoginRequest(Schema):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=128)]


class ProfileUpdate(Schema):
    nickname: Annotated[str, Field(min_length=1, max_length=80)]
    avatar_url: HttpUrl | None = None


class ProfileResponse(Schema):
    id: str
    email: str
    nickname: str
    avatar_url: str
    experience: int
    level: int
    completed_quizzes: int


class SessionResponse(Schema):
    authenticated: bool
    profile: ProfileResponse | None = None
    claimable_quizzes: int = 0
    claimable_jobs: int = 0
    provider_mode: str


class ClaimResponse(Schema):
    quizzes: int
    experience: int
    jobs: int = 0


class HistoryItem(Schema):
    id: str
    topic: str
    created_at: str
    answered: int
    total: int
    report_ready: bool


class HistoryResponse(Schema):
    items: list[HistoryItem]
    total: int
    page: int
    page_size: int


class JobResponse(Schema):
    id: str
    status: Literal["pending", "running", "completed", "failed"]
    result_id: str | None = None
    error: str | None = None
    kind: str


class DocumentResponse(Schema):
    id: str
    filename: str
    status: str
    size: int
    chunk_count: int
    error: str | None = None
    created_at: str


class AssetRequest(Schema):
    quiz_id: ResourceId
    prompt: Annotated[str, Field(min_length=1, max_length=4000)]


class AssetResponse(Schema):
    id: str
    status: str
    url: str | None = None
    error: str | None = None


class Plan(Schema):
    action: Literal["search", "extract", "finish"]
    query: str = ""
