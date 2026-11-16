"""Request-scoped model settings for free chat only."""
from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


def _normalize_endpoint(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("endpoint must be an HTTPS URL")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("endpoint must be a valid HTTPS URL") from exc
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("endpoint must use HTTPS")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("endpoint credentials, query, and fragment are not allowed")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("endpoint port is invalid")

    hostname = parsed.hostname.rstrip(".")
    if not hostname or "%" in hostname:
        raise ValueError("endpoint hostname is invalid")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            ascii_host = hostname.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise ValueError("endpoint hostname is invalid") from exc
        labels = ascii_host.split(".")
        if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in labels):
            raise ValueError("endpoint hostname is invalid")
        if not re.fullmatch(r"[a-z0-9.-]+", ascii_host):
            raise ValueError("endpoint hostname is invalid")
        hostname_for_netloc = ascii_host
    else:
        if not address.is_global:
            raise ValueError("endpoint must not use a local or reserved address")
        hostname_for_netloc = f"[{address.compressed}]" if address.version == 6 else address.compressed

    path = parsed.path.rstrip("/")
    if not path.endswith("/chat/completions"):
        path = f"{path}/chat/completions" if path else "/v1/chat/completions"
    netloc = f"{hostname_for_netloc}:{port}" if port else hostname_for_netloc
    return urlunsplit(("https", netloc, path, "", ""))


class ModelConfig(BaseModel):
    """Secrets for one request; never persist this model or include it in logs."""

    model_config = ConfigDict(extra="forbid")

    endpoint: str
    model: str = Field(min_length=1, max_length=128)
    api_key: str = Field(min_length=1, max_length=4096, repr=False, exclude=True)
    timeout: float = Field(default=30.0, gt=0, le=120)

    @field_validator("endpoint", mode="before")
    @classmethod
    def normalize_endpoint(cls, value: object) -> str:
        return _normalize_endpoint(value)

    @field_validator("model")
    @classmethod
    def validate_model_id(cls, value: str) -> str:
        if value != value.strip() or not _MODEL_ID.fullmatch(value):
            raise ValueError("model ID is invalid")
        return value

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: str) -> str:
        if not value or value != value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("API key is invalid")
        return value

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "ModelConfig":
        if not isinstance(payload, Mapping):
            raise ValueError("invalid model configuration")
        try:
            return cls.model_validate(dict(payload))
        except Exception:
            raise ValueError("invalid model configuration") from None

    @property
    def diagnostic_endpoint(self) -> str:
        parsed = urlsplit(self.endpoint)
        host = parsed.hostname or ""
        try:
            port = parsed.port
        except ValueError:
            port = None
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = f"{host}:{port}" if port else host
        return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


class FreeChatRequest(BaseModel):
    """Key-bearing input isolated from the story/game request contracts."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=1000)
    model: ModelConfig

    @field_validator("message")
    @classmethod
    def trim_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be empty")
        return value


class ProviderPreset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    endpoint: str
    default_model: str


class ModelTestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    model: str
    endpoint: str

    @model_validator(mode="after")
    def safe_endpoint(self) -> "ModelTestResult":
        parsed = urlsplit(self.endpoint)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("diagnostic endpoint must be safe")
        return self
