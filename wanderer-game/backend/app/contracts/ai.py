# 本文件由 codex 辅助生成（外围模块）
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Emotion(str, Enum):
    GUARDED = "guarded"
    IRRITATED = "irritated"
    CALM = "calm"
    ANGRY = "angry"
    RELUCTANT = "reluctant"
    QUIET = "quiet"


class Choice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=100)


class NextScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str = Field(min_length=1, max_length=80)
    options: list[Choice] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def unique_choice_ids(self) -> "NextScene":
        ids = [choice.id for choice in self.options]
        if len(ids) != len(set(ids)):
            raise ValueError("choice ids must be unique")
        return self


class AIResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reply: str = Field(min_length=1, max_length=1000)
    emotion: Emotion
    state_delta: dict[str, int] = Field(default_factory=dict)
    next_scene: NextScene | None
    is_ending: bool
    ending_id: str | None = None

    @model_validator(mode="after")
    def ending_consistency(self) -> "AIResponse":
        if self.is_ending and self.ending_id is None:
            raise ValueError("ending_id is required for an ending response")
        if not self.is_ending and self.next_scene is None:
            raise ValueError("next_scene is required for a non-ending response")
        if not self.is_ending and self.ending_id is not None:
            raise ValueError("ending_id must be null before an ending")
        if any(key not in {"trust", "compassion", "responsibility"} for key in self.state_delta):
            raise ValueError("state_delta contains an unsupported field")
        if any(abs(value) > 10 for value in self.state_delta.values()):
            raise ValueError("state_delta values must be between -10 and 10")
        return self


class ChatResponse(BaseModel):
    """自由对话响应；不进入剧情状态机，因此没有场景或结局。"""

    model_config = ConfigDict(extra="forbid")

    reply: str = Field(min_length=1, max_length=1000)
    title: str | None = Field(default=None, max_length=30)
    emotion: Emotion


class CoreTurnResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response: AIResponse
    state: Any
    ending: "EndingResult | None" = None


class EndingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ending_id: str
    title: str
    summary: str
