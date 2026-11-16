# 本文件由 codex 辅助生成（外围模块）
import logging
from collections.abc import Mapping
from threading import Event, Lock
from uuid import UUID, uuid4

from backend.app.config import demo_mode
from backend.app.contracts.ai import AIResponse, ChatResponse, Emotion
from backend.app.contracts.game import GameState
from backend.app.contracts.model import ModelConfig
from backend.app.errors import AppError
from backend.app.storage.session_repository import SessionRepository
from backend.app.core.character_profile import DEFAULT_CHARACTER_PROFILE
from backend.app.core.model_client import ChatModelRequest, ChatReplyEventStream, DeterministicModelClient, LiveModelClient, _ReplyTextChunker, normalize_chat_reply_layout, summarize_chat_title
from backend.app.core.language_guard import guard_language
from backend.app.core.output_sanitizer import sanitize_character_reply
from backend.app.core.pronoun_guard import (
    FALLBACK_REPLIES,
    guard_chat_reply,
    sanitize_history_pair,
    sanitize_visible_pair,
    sanitize_visible_reply,
)
from backend.app.core.roleplay_engine import RoleplayEngineImpl
from backend.app.core.errors import (
    InvalidAIResponseError,
    InvalidOptionError,
    InvalidTurnInputError,
    ModelProviderError,
    ModelTimeoutError,
    SessionFinishedError,
    TurnLimitExceededError,
)

logger = logging.getLogger(__name__)

# 首次生成 + 最多 2 次重试（spec 5.2.1 规则 6：重试上限 2 次）
_GUARD_MAX_ATTEMPTS = 3
class _ChatStreamControl:
    def __init__(self, chat_id: UUID) -> None:
        self.chat_id = chat_id
        self._cancelled = Event()
        self._lock = Lock()
        self._stream = None
        self._committed = False
        self._started = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def attach_stream(self, stream) -> None:
        cancel_now = False
        with self._lock:
            self._started = True
            if self._cancelled.is_set():
                cancel_now = True
            else:
                self._stream = stream
        if cancel_now:
            stream.cancel()

    def cancel(self) -> bool:
        with self._lock:
            if self._committed:
                return False
            self._cancelled.set()
            stream = self._stream
        if stream is not None:
            stream.cancel()
        return True

    def commit(self, action) -> bool:
        with self._lock:
            if self._cancelled.is_set():
                return False
            action()
            self._committed = True
            self._stream = None
            return True

    @property
    def pending_before_start(self) -> bool:
        with self._lock:
            return not self._started and self._cancelled.is_set()


def normalize_chat_pronouns(reply: str) -> str:
    """兼容旧入口：委托人称守门，不可安全修复时保守返回原文。"""
    return sanitize_visible_reply(reply)


def _clean_history_pairs(items: list[dict]) -> tuple[tuple[str, str], ...]:
    """回传模型前的场景感知历史清洗：不可安全清洗的条目整体剔除，切断脏历史自我强化。"""
    pairs: list[tuple[str, str]] = []
    for item in items:
        safe_reply = sanitize_character_reply(item.get("reply", ""))
        if safe_reply is None:
            continue
        cleaned = sanitize_history_pair(item.get("message", ""), safe_reply)
        if cleaned is not None and guard_language(cleaned).status == "clean":
            pairs.append((item.get("message", ""), cleaned))
    return tuple(pairs)


def _present_chat_messages(items: list[dict]) -> list[dict]:
    """Build single-paragraph view copies without rewriting stored history."""
    return [
        {
            **{key: item[key] for key in ("message", "emotion") if key in item},
            "reply": normalize_chat_reply_layout(
                sanitize_visible_pair(
                    item.get("message", ""),
                    sanitize_character_reply(item.get("reply", "")) or FALLBACK_REPLIES[2],
                )
            ),
        }
        for item in items
    ]


def _coerce_chat_response(raw: Mapping[str, object] | ChatResponse) -> ChatResponse:
    """Keep harmless provider omissions and metadata from breaking free chat.

    Chat replies do not drive the game state. Story fields and provider
    metadata are deliberately dropped before Pydantic validation.
    """
    if isinstance(raw, ChatResponse):
        response = raw
    else:
        if not isinstance(raw, Mapping):
            raise TypeError("chat model response must be an object")

        payload = {key: raw[key] for key in ChatResponse.model_fields if key in raw}
        payload.setdefault("emotion", Emotion.CALM.value)
        if payload.get("emotion") not in {item.value for item in Emotion}:
            payload["emotion"] = Emotion.CALM.value
        title = payload.get("title")
        if not isinstance(title, str) or not 1 <= len(title) <= 30:
            payload["title"] = None
        response = ChatResponse.model_validate(payload)

    safe_reply = sanitize_character_reply(response.reply)
    safe_title = sanitize_character_reply(response.title) if response.title else None
    return response.model_copy(update={"reply": safe_reply or "", "title": safe_title})


class SessionService:
    REPLAY_ID = "demo_guarded_path"

    def __init__(self, repository: SessionRepository, default_mode: str | None = None, engine=None, model_client=None):
        self.repository = repository
        self.default_mode = default_mode or demo_mode()
        self._engine_override = engine
        self._model_client_override = model_client
        self._engines: dict[str, RoleplayEngineImpl] = {}
        self._chat_clients: dict[str, object] = {}
        self._chat_streams: dict[str, _ChatStreamControl] = {}
        self._chat_streams_lock = Lock()
        # Story sessions are deterministic offline replays; never load the
        # environment-backed live client into the free-chat service object.
        self.engine = self._engine_for_mode("offline")

    def _new_model_client(self, mode: str):
        if self._model_client_override is not None:
            return self._model_client_override
        return LiveModelClient() if mode == "live" else DeterministicModelClient()

    def _engine_for_mode(self, mode: str):
        if self._engine_override is not None:
            return self._engine_override
        if mode not in self._engines:
            self._engines[mode] = RoleplayEngineImpl(model_client=self._new_model_client(mode))
        return self._engines[mode]

    @staticmethod
    def _history_input(last_response, player_message: str | None, option_id: str | None) -> str:
        if player_message:
            return player_message
        if last_response and last_response.next_scene and option_id:
            for choice in last_response.next_scene.options:
                if choice.id == option_id:
                    return choice.text
        return "选择了一个行动"

    def _label_latest_history(self, result, last_response, player_message: str | None, option_id: str | None):
        history = list(result.state.history)
        if history:
            history[-1] = history[-1].model_copy(
                update={"player_input": self._history_input(last_response, player_message, option_id)}
            )
            result.state = result.state.model_copy(update={"history": history})
        return result

    def create(self, requested_mode: str | None = None, replay_id: str | None = None, player_name: str = "同行者"):
        # 剧情旅途始终使用确定性固定回放；实时模型仅用于自由对话。
        mode = "offline"
        selected_replay = replay_id or self.REPLAY_ID
        session_id = uuid4()
        ending = None
        if mode == "offline":
            try:
                response = DeterministicModelClient.opening_response(selected_replay)
            except InvalidOptionError as exc:
                raise AppError("REPLAY_NOT_FOUND", "所选离线回放不存在", 404) from exc
            state = self._engine_for_mode("offline").create_initial_state(session_id=str(session_id))
            state = state.model_copy(update={"player_name": player_name})
            response = AIResponse.model_validate(response)
            ending = None
        else:
            state = self.engine.create_initial_state(session_id=str(session_id))
            state = state.model_copy(update={"player_name": player_name})
            response = None
            selected_replay = "live"
        self.repository.save(state, response, mode, selected_replay, ending)
        return state, response, mode, selected_replay, ending

    def get(self, session_id: UUID) -> tuple[GameState, object | None, str, str, object | None]:
        saved = self.repository.get(session_id)
        if saved is None:
            raise AppError("SESSION_NOT_FOUND", "会话不存在或已过期", 404)
        return saved

    def turn(self, session_id: UUID, player_message: str | None, option_id: str | None):
        state, last_response, mode, replay_id, _ = self.get(session_id)
        # 老版本创建的 live 剧情存档迁移到固定回放，进度仍由同一状态继续。
        mode = "offline"
        if state.is_finished:
            raise AppError("SESSION_FINISHED", "本局已结束，请重新开始", 409)

        if last_response and last_response.next_scene:
            allowed_options = {choice.id for choice in last_response.next_scene.options}
            if option_id is not None and option_id not in allowed_options:
                raise AppError("INVALID_OPTION", "该选项不属于当前回合", 409)

        try:
            result = self._engine_for_mode("offline").handle_turn(state=state, player_message=player_message, option_id=option_id)
        except ModelTimeoutError as exc:
            raise AppError("MODEL_TIMEOUT", "模型服务响应超时", 504) from exc
        except ModelProviderError as exc:
            raise AppError("MODEL_PROVIDER_ERROR", exc.user_message, 502) from exc
        except InvalidOptionError as exc:
            raise AppError("INVALID_OPTION", "该选项无法在当前场景中解析", 409) from exc
        except InvalidTurnInputError as exc:
            raise AppError("INVALID_REQUEST", "请输入一句话或选择一个有效选项", 400) from exc
        except SessionFinishedError as exc:
            raise AppError("SESSION_FINISHED", "本局已结束，请重新开始", 409) from exc
        except TurnLimitExceededError as exc:
            raise AppError("TURN_LIMIT_EXCEEDED", "已达到本局回合上限", 409) from exc
        except InvalidAIResponseError as exc:
            raise AppError("INVALID_AI_RESPONSE", "模型返回内容不符合协议", 502) from exc
        result = self._label_latest_history(result, last_response, player_message, option_id)
        self.repository.save(result.state, result.response, mode, replay_id, result.ending)
        return result.state, result.response, result.ending

    def restart(self, session_id: UUID):
        state, _, mode, replay_id, _ = self.get(session_id)
        self.repository.delete(session_id)
        return self.create(mode, replay_id, state.player_name)

    def delete(self, session_id: UUID) -> bool:
        return self.repository.delete(session_id)

    def create_chat(self, requested_mode: str | None = None, player_name: str = "同行者"):
        chat_id = uuid4()
        mode = requested_mode or self.default_mode
        self.repository.create_chat(chat_id, mode, player_name)
        return chat_id, mode

    def delete_chat(self, chat_id: UUID) -> bool:
        return self.repository.delete_chat(chat_id)

    def _get_chat_record(self, chat_id: UUID):
        value = self.repository.get_chat_details(chat_id)
        if value is None:
            raise AppError("CHAT_SESSION_NOT_FOUND", "自由对话会话不存在或已过期", 404)
        mode, messages, player_name, title = value
        if title == "新对话" and messages:
            first = _present_chat_messages(messages)[0]
            title = summarize_chat_title(first.get("message", ""), first.get("reply", ""))
            self.repository.save_chat_messages(chat_id, messages, title)
        title = sanitize_character_reply(title) or "新对话"
        return mode, messages, player_name, title

    def get_chat(self, chat_id: UUID):
        mode, messages, player_name, title = self._get_chat_record(chat_id)
        return mode, _present_chat_messages(messages), player_name, title

    @staticmethod
    def _chat_client_for_config(model_config: ModelConfig | None):
        if model_config is None:
            raise AppError("MODEL_NOT_CONFIGURED", "请先配置模型服务后再开始自由对话。", 400)
        return LiveModelClient(model_config)

    def _request_chat_response(
        self,
        model_config: ModelConfig | None,
        request: ChatModelRequest,
        *,
        client=None,
    ) -> ChatResponse:
        client = client or self._chat_client_for_config(model_config)
        try:
            raw = client.generate_chat(request=request)
            return _coerce_chat_response(raw)
        except AppError:
            raise
        except ModelTimeoutError as exc:
            raise AppError("MODEL_TIMEOUT", "模型服务响应超时", 504) from exc
        except ModelProviderError as exc:
            self._raise_chat_error(exc, client, model_config)
        except (ValueError, TypeError) as exc:
            raise AppError("INVALID_AI_RESPONSE", "模型返回内容不符合协议，请检查服务商的 JSON 输出兼容性。", 502) from exc
        except Exception as exc:
            raise AppError("MODEL_PROVIDER_ERROR", "模型服务暂时无法完成回复，请稍后重试。", 502) from exc

    @staticmethod
    def _raise_chat_error(exc, client=None, model_config: ModelConfig | None = None):
        if isinstance(exc, AppError):
            raise exc
        if isinstance(exc, ModelTimeoutError):
            raise AppError("MODEL_TIMEOUT", "模型服务响应超时", 504) from exc
        if isinstance(exc, InvalidAIResponseError):
            raise AppError("INVALID_AI_RESPONSE", "模型返回内容不符合对话要求。", 502) from exc
        if isinstance(exc, ModelProviderError):
            if getattr(exc, "configuration_error", False) or exc.status_code in {400, 404}:
                raise AppError("MODEL_CONFIGURATION_ERROR", "模型接口地址无效或无法安全连接，请编辑模型设置。", 400) from exc
            if str(exc) in {
                "model provider returned invalid JSON",
                "model provider returned an unexpected payload",
                "model provider returned invalid streaming JSON",
                "model provider returned an incomplete streamed response",
            }:
                raise AppError("INVALID_AI_RESPONSE", "模型返回内容不符合协议，请检查服务商的 JSON 输出兼容性。", 502) from exc
            details = {"provider_status": exc.status_code} if exc.status_code is not None else {}
            if exc.retry_after is not None:
                details["retry_after"] = exc.retry_after
            api_key = model_config.api_key if model_config is not None else None
            if exc.provider_code and (not api_key or api_key not in exc.provider_code):
                details["provider_code"] = exc.provider_code
            if exc.provider_request_id and (not api_key or api_key not in exc.provider_request_id):
                details["provider_request_id"] = exc.provider_request_id
            model_name = getattr(client, "model_name", None)
            endpoint = getattr(client, "diagnostic_endpoint", None)
            if not isinstance(model_name, str) and model_config is not None:
                model_name = model_config.model
            if not isinstance(endpoint, str) and model_config is not None:
                endpoint = model_config.diagnostic_endpoint
            if isinstance(model_name, str) and (not api_key or api_key not in model_name):
                details["model"] = model_name
            if isinstance(endpoint, str) and (not api_key or api_key not in endpoint):
                details["endpoint"] = endpoint
            message = exc.user_message
            if api_key and api_key in message:
                message = "模型服务暂时不可用，请检查实时接口配置后重试。"
            raise AppError("MODEL_PROVIDER_ERROR", message, 502, details=details or None) from exc
        if isinstance(exc, (ValueError, TypeError)):
            raise AppError("INVALID_AI_RESPONSE", "模型返回内容不符合对话要求。", 502) from exc
        raise AppError("MODEL_PROVIDER_ERROR", "模型服务暂时无法完成回复，请稍后重试。", 502) from exc

    def _generate_chat(self, model_config: ModelConfig | None, request: ChatModelRequest, *, client=None) -> ChatResponse:
        """Generate and guard a live reply; never substitute fixture text after failure."""
        client = client or self._chat_client_for_config(model_config)
        for attempt in range(1, _GUARD_MAX_ATTEMPTS + 1):
            response = self._request_chat_response(model_config, request, client=client)
            normalized_reply = normalize_chat_reply_layout(response.reply)
            if not normalized_reply.strip():
                logger.warning(
                    "chat reply became blank after layout normalization (attempt %d/%d)",
                    attempt,
                    _GUARD_MAX_ATTEMPTS,
                )
                continue
            response = response.model_copy(update={"reply": normalized_reply})
            try:
                result = guard_chat_reply(request.message, response.reply)
            except Exception as exc:
                logger.warning("pronoun guard raised unexpectedly")
                raise AppError("INVALID_AI_RESPONSE", "模型返回内容不符合对话要求。", 502) from exc
            if result.status != "unrepairable":
                language_result = guard_language(result.text)
                if language_result.status != "unrepairable":
                    return response.model_copy(update={"reply": language_result.text})
                logger.warning(
                    "chat reply rejected by language guard (attempt %d/%d, status=%s)",
                    attempt,
                    _GUARD_MAX_ATTEMPTS,
                    language_result.status,
                )
                continue
            logger.warning(
                "chat reply rejected by pronoun guard (attempt %d/%d, status=%s)",
                attempt,
                _GUARD_MAX_ATTEMPTS,
                result.status,
            )
        logger.warning("chat reply guard retries exhausted")
        raise AppError("INVALID_AI_RESPONSE", "模型回复连续未通过内容校验，请调整提示或模型设置后重试。", 502)

    def chat_message(self, chat_id: UUID, message: str, *, model_config: ModelConfig | None = None):
        mode, messages, player_name, title = self._get_chat_record(chat_id)
        history = _clean_history_pairs(messages)
        request = ChatModelRequest(character_profile=DEFAULT_CHARACTER_PROFILE, message=message, history=history, player_name=player_name)
        response = self._generate_chat(model_config, request)
        conversation_title = title
        if conversation_title == "新对话":
            conversation_title = response.title or summarize_chat_title(message, response.reply)
        response = response.model_copy(update={"title": conversation_title})
        messages.append({"message": message, "reply": response.reply, "emotion": response.emotion.value})
        self.repository.save_chat_messages(chat_id, messages, conversation_title)
        return response, _present_chat_messages(messages)

    def stream_chat_message(
        self,
        chat_id: UUID,
        message: str,
        *,
        stream_id: str | None = None,
        model_config: ModelConfig | None = None,
    ):
        control = None
        if stream_id:
            with self._chat_streams_lock:
                previous = self._chat_streams.get(stream_id)
                if previous and previous.chat_id == chat_id and previous.pending_before_start:
                    control = previous
                else:
                    control = _ChatStreamControl(chat_id)
                    self._chat_streams[stream_id] = control
            if previous and previous is not control:
                previous.cancel()

        def events():
            event_index = 0
            stream = None
            reply_chunker = _ReplyTextChunker()

            def publish(text: str, *, final: bool = False):
                nonlocal event_index
                for chunk in reply_chunker.feed(text, final=final):
                    if control and control.cancelled:
                        return False
                    yield {"type": "text", "index": event_index, "delta": chunk}
                    event_index += 1
                return True

            def prepare_response(raw: Mapping[str, object] | ChatResponse) -> ChatResponse:
                response = _coerce_chat_response(raw)
                normalized_reply = normalize_chat_reply_layout(response.reply)
                if not normalized_reply.strip():
                    raise InvalidAIResponseError("streamed chat reply became blank after layout normalization")
                response = response.model_copy(update={"reply": normalized_reply})
                guarded = guard_chat_reply(message, response.reply)
                if guarded.status == "unrepairable":
                    raise InvalidAIResponseError("streamed chat reply failed the character guard")
                language = guard_language(guarded.text)
                if language.status == "unrepairable":
                    raise InvalidAIResponseError("streamed chat reply failed the language guard")
                return response.model_copy(update={"reply": language.text})

            try:
                if control and control.cancelled:
                    return
                mode, messages, player_name, title = self._get_chat_record(chat_id)
                request = ChatModelRequest(
                    character_profile=DEFAULT_CHARACTER_PROFILE,
                    message=message,
                    history=_clean_history_pairs(messages),
                    player_name=player_name,
                )
                client = self._chat_client_for_config(model_config)
                raw_response = None
                stream_failure = None
                streamed = hasattr(client, "generate_chat_stream")
                if streamed:
                    try:
                        stream = client.generate_chat_stream(request=request)
                        if control:
                            control.attach_stream(stream)
                            if control.cancelled:
                                return
                        for item in stream:
                            if control and control.cancelled:
                                return
                            if item.get("type") == "done":
                                raw_response = item.get("response")
                    except (AppError, ModelProviderError, ModelTimeoutError, InvalidAIResponseError, ValueError, TypeError) as exc:
                        if control and control.cancelled:
                            return
                        stream_failure = exc
                    finally:
                        if control and control.cancelled:
                            close = getattr(stream, "close", None)
                            if callable(close):
                                close()

                if stream_failure is not None:
                    self._raise_chat_error(stream_failure, client, model_config)
                if streamed and raw_response is None:
                    raise AppError("INVALID_AI_RESPONSE", "模型服务没有返回完整的回复。", 502)
                if not streamed:
                    response = self._generate_chat(model_config, request, client=client)
                else:
                    try:
                        response = prepare_response(raw_response)
                    except (InvalidAIResponseError, ValueError, TypeError) as exc:
                        raise AppError("INVALID_AI_RESPONSE", "模型返回内容不符合对话要求。", 502) from exc

                if control and control.cancelled:
                    return
                published = yield from publish(response.reply, final=True)
                if not published:
                    return

                conversation_title = title
                if conversation_title == "新对话":
                    conversation_title = response.title or summarize_chat_title(message, response.reply)
                response = response.model_copy(update={"title": conversation_title})
                messages.append({"message": message, "reply": response.reply, "emotion": response.emotion.value})
                if control:
                    committed = control.commit(
                        lambda: self.repository.save_chat_messages(chat_id, messages, conversation_title)
                    )
                    if not committed:
                        return
                else:
                    self.repository.save_chat_messages(chat_id, messages, conversation_title)
                yield {
                    "type": "done",
                    "response": response.model_dump(mode="json"),
                    "game_state": None,
                    "messages": _present_chat_messages(messages),
                    "title": conversation_title,
                }
            except AppError as exc:
                yield {"type": "error", "message": exc.message, "code": exc.code, "details": exc.details}
            except (ModelProviderError, ModelTimeoutError, ValueError, TypeError) as exc:
                logger.warning("free chat stream failed")
                try:
                    self._raise_chat_error(exc, locals().get("client"), model_config)
                except AppError as app_error:
                    yield {"type": "error", "message": app_error.message, "code": app_error.code, "details": app_error.details}
            except Exception as exc:
                logger.warning("free chat stream failed unexpectedly")
                try:
                    self._raise_chat_error(exc, locals().get("client"), model_config)
                except AppError as app_error:
                    yield {"type": "error", "message": app_error.message, "code": app_error.code, "details": app_error.details}
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()
                if stream_id:
                    with self._chat_streams_lock:
                        if self._chat_streams.get(stream_id) is control:
                            self._chat_streams.pop(stream_id, None)

        return events()

    def cancel_chat_stream(self, stream_id: str, *, chat_id: UUID | None = None) -> bool:
        with self._chat_streams_lock:
            control = self._chat_streams.get(stream_id)
            if control and (chat_id is not None and control.chat_id != chat_id):
                return False
            if control is None:
                prefix = f"{chat_id}-" if chat_id is not None else ""
                turn_number = stream_id[len(prefix):] if prefix and stream_id.startswith(prefix) else ""
                if not turn_number.isdecimal() or int(turn_number) < 1:
                    return False
                control = _ChatStreamControl(chat_id)
                self._chat_streams[stream_id] = control
                stale_before_start = [
                    key for key, value in self._chat_streams.items()
                    if value.pending_before_start
                ]
                while len(stale_before_start) > 512:
                    self._chat_streams.pop(stale_before_start.pop(0), None)
        return control.cancel()

    def regenerate_chat(self, chat_id: UUID, *, model_config: ModelConfig | None = None):
        """按上一条玩家输入重新生成回复；新版本替换原展示位置，失败不改动原回复。"""
        mode, messages, player_name, title = self._get_chat_record(chat_id)
        if not messages:
            raise AppError("CHAT_NOTHING_TO_REGENERATE", "当前对话还没有可以重新生成的回复", 409)
        last = messages[-1]
        history = _clean_history_pairs(messages[:-1])
        request = ChatModelRequest(character_profile=DEFAULT_CHARACTER_PROFILE, message=last["message"], history=history, player_name=player_name)
        response = self._generate_chat(model_config, request)
        response = response.model_copy(update={"title": title})
        updated = {**last, "reply": response.reply, "emotion": response.emotion.value}
        messages = [*messages[:-1], updated]
        self.repository.save_chat_messages(chat_id, messages, title)
        return response, _present_chat_messages(messages)
