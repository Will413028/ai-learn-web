from collections.abc import Sequence
from hashlib import sha256
import io
import math
import re
from typing import Any, Protocol
from uuid import uuid4

from PIL import Image, ImageDraw

from app.schemas import GenerateRequest, Plan


class ProviderError(Exception):
    """Sanitized adapter failure; never include credentials or private text."""


class Provider(Protocol):
    """Adapters must stop transport work by the monotonic deadline; never auto-retry.

    Network adapters implement connect/read/total timeouts within this budget.
    Non-cooperative local inference must run in a terminable process, not a thread.
    """
    embedding_model: str
    embedding_dimensions: int
    def generate(self, request: GenerateRequest, context: str, *, deadline: float = float("inf")) -> object: ...
    def report(self, topic: str, answers: list[dict[str, Any]], *, deadline: float = float("inf")) -> object: ...
    def plan(self, topic: str, context: str, round_number: int, *, deadline: float = float("inf")) -> object: ...
    def search(self, query: str, *, deadline: float = float("inf")) -> list[dict[str, str]]: ...
    def extract(self, url: str, *, deadline: float = float("inf")) -> list[dict[str, str]]: ...
    def embed(self, texts: Sequence[str], *, deadline: float = float("inf")) -> list[list[float]]: ...
    def image(self, prompt: str, *, deadline: float = float("inf")) -> bytes: ...


def configured_provider(mode: str) -> Provider:
    if mode == "fake":
        return FakeProvider()
    if mode == "cloud":
        from app.cloud_provider import CloudConfig, CloudProvider
        return CloudProvider(CloudConfig.from_environment())
    raise RuntimeError("Provider 尚未設定或完成驗收，請選用 fake 模式")


class FakeProvider:
    embedding_model = "fake-hash-v1"
    embedding_dimensions = 64

    def generate(self, request: GenerateRequest, context: str, *, deadline: float = float("inf")) -> object:
        result: list[dict[str, Any]] = []
        topic = request.topic[:80]
        excerpt = context[:120].replace("\n", " ")
        for i in range(request.question_count):
            kind = request.question_types[i % len(request.question_types)]
            if kind == "boolean":
                text = f"學習「{topic}」時，透過實作檢查理解是一種有效方法。"
                options = [{"id": "T", "text": "正確"}, {"id": "F", "text": "錯誤"}]
                correct = ["T"]
            elif kind == "multiple":
                text = f"哪些方法能幫助理解「{topic}」？（多選）"
                options = [
                    {"id": "A", "text": "用自己的話解釋"},
                    {"id": "B", "text": "完成小練習並檢查结果"},
                    {"id": "C", "text": "只記住標題，不確認理解"},
                ]
                correct = ["A", "B"]
            else:
                text = f"學習「{topic}」時，哪一種方式更能確認自己理解？"
                options = [
                    {"id": "A", "text": "只閱讀定義，不實作"},
                    {"id": "B", "text": "用自己的話解釋，並完成一個小練習"},
                ]
                correct = ["B"]
            result.append({"id": str(uuid4()), "type": kind, "text": text, "options": options,
                "correct_answers": correct,
                "explanation": "解釋與實作能暴露理解中的缺口。" + (f"參考片段：{excerpt}" if excerpt else ""),
                "knowledge_points": [topic, "主動學習"]})
        return {"questions": result}

    def report(self, topic: str, answers: list[dict[str, Any]], *, deadline: float = float("inf")) -> object:
        wrong = [a for a in answers if not a["is_correct"]]
        return {"summary": f"已完成「{topic[:80]}」練習；透過錯題找出下一個練習方向。",
            "mastery": {point: "需加強" if wrong else "已掌握" for a in answers for point in a["knowledge_points"]},
            "weaknesses": sorted({point for a in wrong for point in a["knowledge_points"]}),
            "suggestions": ["用自己的話解釋錯題觀念", "完成另一個小例子後再練習"],
            "share_quote": "把知道，變成做得到。"}

    def plan(self, topic: str, context: str, round_number: int, *, deadline: float = float("inf")) -> object:
        return Plan(action="search" if round_number == 0 else "finish", query=topic).model_dump()

    def search(self, query: str, *, deadline: float = float("inf")) -> list[dict[str, str]]:
        return [{"title": f"{query[:60]} · 示範搜尋", "url": "https://example.com/learning",
                 "text": f"{query} 可透過概念整理、實作、回饋來學習。這是離線搜尋 fixture。"}]

    def extract(self, url: str, *, deadline: float = float("inf")) -> list[dict[str, str]]:
        return [{"title": "網址內容示範", "url": url,
                 "text": "此為離線網址提取示範：練習、回饋與複習有助理解。"}]

    def embed(self, texts: Sequence[str], *, deadline: float = float("inf")) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.0] * self.embedding_dimensions
            tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text.lower())
            for token in tokens:
                index = int.from_bytes(sha256(token.encode()).digest()[:2]) % len(vector)
                vector[index] += 1
            norm = math.sqrt(sum(v * v for v in vector)) or 1.0
            vectors.append([v / norm for v in vector])
        return vectors

    def image(self, prompt: str, *, deadline: float = float("inf")) -> bytes:
        image = Image.new("RGB", (640, 360), "#eff4e8")
        draw = ImageDraw.Draw(image)
        color = tuple(sha256(prompt.encode()).digest()[:3])
        draw.rounded_rectangle((80, 80, 560, 280), radius=28, fill=color)
        draw.text((110, 120), "AI LEARN - DEMO", fill="white")
        draw.text((110, 170), "Learn > Practice > Reflect", fill="white")
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
