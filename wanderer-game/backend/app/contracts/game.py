# 本文件由 codex 辅助生成（外围模块）
from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.contracts.ai import AIResponse, EndingResult


class HistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str
    player_input: str = Field(max_length=1000)
    response_summary: str = Field(max_length=2000)


class GameState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    player_name: str = Field(default="同行者", min_length=1, max_length=20)
    scene_id: str = Field(min_length=1, max_length=80)
    turn_count: int = Field(ge=0, le=30)
    trust: int = Field(ge=0, le=100)
    compassion: int = Field(ge=0, le=100)
    responsibility: int = Field(ge=0, le=100)
    history: list[HistoryItem] = Field(max_length=30)
    is_finished: bool
    ending_id: str | None = None
    created_at: datetime
    updated_at: datetime


class TurnRequest(BaseModel):
    """剧情旅途回合输入：只接受预设选项，玩家不能自定义文本。"""

    model_config = ConfigDict(extra="forbid")

    option_id: str = Field(min_length=1, max_length=80)


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_version: str | None = Field(default=None, max_length=40)
    mode: str | None = Field(default=None, pattern="^(offline|live)$")
    replay_id: str | None = Field(default=None, min_length=1, max_length=80)
    player_name: str = Field(default="同行者", min_length=1, max_length=20)

    @field_validator("player_name")
    @classmethod
    def trim_player_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("player name must not be empty")
        return value


class ChatCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str | None = Field(default=None, pattern="^(offline|live)$")
    player_name: str = Field(default="同行者", min_length=1, max_length=20)

    @field_validator("player_name")
    @classmethod
    def trim_player_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("player name must not be empty")
        return value


class ChatMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def trim_message(self) -> "ChatMessageRequest":
        self.message = self.message.strip()
        if not self.message:
            raise ValueError("message must not be empty")
        return self


class SessionPayload(BaseModel):
    session_id: UUID
    state: GameState
    last_response: AIResponse | None = None
    ending: EndingResult | None = None


def initial_state(session_id: UUID | None = None, player_name: str = "同行者") -> GameState:
    now = datetime.now(timezone.utc)
    return GameState(
        session_id=session_id or uuid4(),
        player_name=player_name,
        scene_id="scene_01",
        turn_count=0,
        trust=50,
        compassion=50,
        responsibility=50,
        history=[],
        is_finished=False,
        ending_id=None,
        created_at=now,
        updated_at=now,
    )
