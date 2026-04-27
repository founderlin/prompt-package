"""Chat domain service.

Owns: creating a Conversation inside a Project, appending Messages,
calling the configured LLM provider on the user's behalf, and
persisting the assistant reply with token usage.

The user's plaintext API key is decrypted *only* inside this module's
call to :func:`llm_service.chat_completion`. We never log it or return it.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone

from sqlalchemy import select

from app.extensions import db
from app.models import Attachment, ContextPack, Conversation, Message, User
from app.models.attachment import KIND_IMAGE, KIND_PDF, KIND_TEXT
from app.providers import DEFAULT_PROVIDER, SUPPORTED_PROVIDERS, get_provider, normalize_provider
from app.services.attachment_service import (
    AttachmentError,
    attach_to_message,
    read_bytes as read_attachment_bytes,
    resolve_user_attachments,
)
from app.services.credentials_service import CredentialsError, get_decrypted_key_for
from app.services.llm_service import LLMError, chat_completion
from app.services.project_service import ProjectError, get_for_user as get_project_for_user

DEFAULT_MODEL = "openai/gpt-4o-mini"
TITLE_MAX = 80
CONTENT_MIN = 1
CONTENT_MAX = 50_000
MAX_HISTORY_MESSAGES = 50  # how much history we feed back to the model

# Friendly per-provider hint used when a key is missing.
_PROVIDER_KEY_HINT = {
    "openrouter": "Add your OpenRouter API key in Settings before chatting.",
    "deepseek": "Add your DeepSeek API key in Settings before chatting.",
    "openai": "Add your OpenAI API key in Settings before chatting.",
}


class ChatError(Exception):
    """Predictable, user-facing chat failures."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_content(raw: str | None) -> str:
    if raw is None:
        raise ChatError("validation_error", "Message content is required.")
    cleaned = raw.strip()
    if len(cleaned) < CONTENT_MIN:
        raise ChatError("validation_error", "Message content is required.")
    if len(cleaned) > CONTENT_MAX:
        raise ChatError(
            "validation_error",
            f"Message content must be at most {CONTENT_MAX} characters.",
        )
    return cleaned


def _normalize_model(raw: str | None) -> str:
    cleaned = (raw or "").strip()
    if not cleaned:
        return DEFAULT_MODEL
    if len(cleaned) > 120:
        raise ChatError("validation_error", "Model identifier is too long.")
    return cleaned


def _normalize_chat_provider(raw: str | None) -> str:
    if raw is None or not str(raw).strip():
        return DEFAULT_PROVIDER
    cleaned = str(raw).strip().lower()
    if cleaned not in SUPPORTED_PROVIDERS:
        raise ChatError(
            "validation_error",
            f"Unsupported provider {cleaned!r}. "
            f"Supported: {', '.join(SUPPORTED_PROVIDERS)}.",
        )
    return cleaned


def _derive_title(text: str) -> str:
    flat = " ".join(text.split())
    if len(flat) <= TITLE_MAX:
        return flat
    return flat[: TITLE_MAX - 1].rstrip() + "…"


def get_conversation_for_user(user: User, conversation_id: int) -> Conversation:
    convo = db.session.get(Conversation, conversation_id)
    if convo is None or convo.user_id != user.id:
        raise ChatError("not_found", "Conversation not found.", status=404)
    return convo


def list_for_project(user: User, project_id: int) -> list[Conversation]:
    try:
        get_project_for_user(user, project_id)
    except ProjectError as err:
        raise ChatError(err.code, err.message, status=err.status) from err

    stmt = (
        select(Conversation)
        .where(
            Conversation.user_id == user.id,
            Conversation.project_id == project_id,
        )
        .order_by(
            Conversation.last_message_at.desc().nulls_last(),
            Conversation.updated_at.desc(),
            Conversation.id.desc(),
        )
    )
    return list(db.session.scalars(stmt).all())


MAX_LIST_LIMIT = 100


def list_recent_for_user(user: User, *, limit: int = 20) -> list[Conversation]:
    """Return the user's most-recently-active conversations across all projects."""
    if limit < 1:
        limit = 1
    if limit > MAX_LIST_LIMIT:
        limit = MAX_LIST_LIMIT
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(
            Conversation.last_message_at.desc().nulls_last(),
            Conversation.updated_at.desc(),
            Conversation.id.desc(),
        )
        .limit(limit)
    )
    return list(db.session.scalars(stmt).all())


def count_for_user(user: User) -> int:
    return db.session.query(Conversation).filter(Conversation.user_id == user.id).count()


def _resolve_pack_for_user(user: User, pack_id: int | None) -> ContextPack | None:
    """Return the user's Context Pack ``pack_id``, or raise a 404-style error.

    ``None`` means "no pack" (caller already handled that). The pack is
    *not* required to live in the same project as the conversation —
    cross-project reuse is the whole point of the feature.
    """
    if pack_id is None:
        return None
    pack = db.session.get(ContextPack, pack_id)
    if pack is None or pack.user_id != user.id:
        raise ChatError("context_pack_not_found", "Context Pack not found.", status=404)
    return pack


def create_conversation(
    user: User,
    project_id: int,
    *,
    model: str | None = None,
    provider: str | None = None,
    context_pack_id: int | None = None,
) -> Conversation:
    try:
        project = get_project_for_user(user, project_id)
    except ProjectError as err:
        raise ChatError(err.code, err.message, status=err.status) from err

    pack = _resolve_pack_for_user(user, context_pack_id)

    convo = Conversation(
        user_id=user.id,
        project_id=project.id,
        model=_normalize_model(model),
        provider=_normalize_chat_provider(provider),
        context_pack_id=pack.id if pack is not None else None,
    )
    db.session.add(convo)
    db.session.commit()
    return convo


def set_context_pack(
    user: User, conversation_id: int, pack_id: int | None
) -> Conversation:
    """Attach / detach a Context Pack to a conversation.

    Pass ``pack_id=None`` to clear it. Returns the refreshed conversation.
    """
    convo = get_conversation_for_user(user, conversation_id)
    pack = _resolve_pack_for_user(user, pack_id)
    convo.context_pack_id = pack.id if pack is not None else None
    db.session.add(convo)
    db.session.commit()
    db.session.refresh(convo)
    return convo


def list_messages(user: User, conversation_id: int) -> list[Message]:
    convo = get_conversation_for_user(user, conversation_id)
    return list(convo.messages.order_by(Message.id.asc()).all())


CONTEXT_PACK_PREAMBLE = (
    "You are continuing a project the user has worked on before. "
    "The Markdown block below is the project's distilled Context Pack — "
    "treat it as authoritative project background and let it inform every "
    "answer in this conversation, but do not repeat it back verbatim unless asked.\n\n"
    "===== PROJECT CONTEXT PACK =====\n"
    "{body}\n"
    "===== END CONTEXT PACK ====="
)


def _attachment_to_content_parts(att: Attachment) -> list[dict]:
    """Render one attachment as OpenAI-compatible multimodal parts.

    * Images (PNG/JPG/WEBP/GIF) → ``image_url`` part with a data URL.
    * PDF → extracted text wrapped in a labeled block.
    * TXT/MD → raw text wrapped in a labeled block.

    Text parts include the filename so the model knows what it's looking at.
    """
    try:
        data = read_attachment_bytes(att)
    except AttachmentError as err:
        # If the file vanished, surface a friendly text note rather than
        # silently skipping — better to tell the model an attachment was
        # meant to be here.
        return [
            {
                "type": "text",
                "text": (
                    f"[Attached file '{att.filename}' is no longer available: "
                    f"{err.message}]"
                ),
            }
        ]

    if att.kind == KIND_IMAGE:
        b64 = base64.b64encode(data).decode("ascii")
        return [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{att.mime_type};base64,{b64}",
                    "detail": "auto",
                },
            }
        ]

    if att.kind in (KIND_PDF, KIND_TEXT):
        text = att.extracted_text or ""
        note = " (truncated)" if att.extracted_truncated else ""
        header = (
            f"===== Attached file: {att.filename}{note} =====\n"
            if text
            else f"[Attached file '{att.filename}' has no extractable text.]"
        )
        body = text if text else ""
        footer = "\n===== END Attached file =====" if text else ""
        return [{"type": "text", "text": f"{header}{body}{footer}".strip()}]

    # Unknown kind — skip silently.
    return []


def _user_content_with_attachments(
    text: str, attachments: list[Attachment]
) -> str | list[dict]:
    """Build the ``content`` field for the new user message payload.

    Returns a plain string when there are no attachments (keeps the
    upstream request small and maximally compatible). Otherwise
    returns a list of content parts in OpenAI's multimodal format.
    """
    if not attachments:
        return text

    parts: list[dict] = [{"type": "text", "text": text}]
    for att in attachments:
        parts.extend(_attachment_to_content_parts(att))
    return parts


def _build_message_payload(
    history: list[Message],
    new_user_text: str,
    *,
    context_pack: ContextPack | None = None,
    attachments: list[Attachment] | None = None,
) -> list[dict]:
    """Build the OpenRouter messages payload.

    Optionally prepends a synthetic ``system`` message carrying the
    Context Pack body. The pack message is **not** persisted — flipping
    or removing the pack is non-destructive.
    """
    trimmed = history[-MAX_HISTORY_MESSAGES:] if len(history) > MAX_HISTORY_MESSAGES else history
    payload: list[dict] = []
    if context_pack is not None and (context_pack.body or "").strip():
        payload.append(
            {
                "role": "system",
                "content": CONTEXT_PACK_PREAMBLE.format(body=context_pack.body.strip()),
            }
        )
    payload.extend({"role": m.role, "content": m.content} for m in trimmed)
    payload.append(
        {
            "role": "user",
            "content": _user_content_with_attachments(
                new_user_text, attachments or []
            ),
        }
    )
    return payload


def send_user_message(
    user: User,
    conversation_id: int,
    *,
    content: str,
    model: str | None = None,
    provider: str | None = None,
    attachment_ids: list[int] | None = None,
) -> tuple[Message, Message, Conversation]:
    """Persist the user's message, call the right LLM provider, persist the reply.

    ``provider`` and ``model`` are both optional; when missing we fall
    back to whatever was last set on the conversation (or our defaults).
    ``attachment_ids`` is a list of previously-uploaded Attachment ids
    that should be folded into the user message as multimodal parts.

    Returns ``(user_message, assistant_message, conversation)``.
    """
    convo = get_conversation_for_user(user, conversation_id)

    chosen_provider = _normalize_chat_provider(
        provider if provider is not None else convo.provider
    )

    try:
        api_key = get_decrypted_key_for(user, chosen_provider)
    except CredentialsError as err:
        raise ChatError(err.code, err.message, status=err.status) from err
    if not api_key:
        raise ChatError(
            "no_api_key",
            _PROVIDER_KEY_HINT.get(
                chosen_provider,
                f"Add your {get_provider(chosen_provider).label} API key in Settings before chatting.",
            ),
            status=400,
        )

    cleaned = _normalize_content(content)
    chosen_model = _normalize_model(model or convo.model)

    # Validate attachments up-front. resolve_user_attachments raises
    # AttachmentError for cross-user / wrong-conversation / already-sent,
    # which the route layer translates to the right HTTP status.
    attachments: list[Attachment] = resolve_user_attachments(
        user, convo.id, attachment_ids or []
    )

    history = list(convo.messages.order_by(Message.id.asc()).all())

    user_msg = Message(
        conversation_id=convo.id,
        role="user",
        content=cleaned,
        model=chosen_model,
        provider=chosen_provider,
    )
    db.session.add(user_msg)

    if not convo.title:
        convo.title = _derive_title(cleaned)
    convo.model = chosen_model
    convo.provider = chosen_provider
    convo.last_message_at = _utcnow()
    db.session.add(convo)
    db.session.commit()  # commit user message first so it persists even if the LLM call fails

    # Stamp attachments onto the just-saved user message. If this fails
    # we roll the transaction back but the message itself is kept —
    # the attachments just stay detached for later retry/cleanup.
    if attachments:
        try:
            attach_to_message(attachments, user_msg)
        except Exception:
            db.session.rollback()

    # Resolve attached pack lazily; if it was deleted out from under us
    # since the conversation was bound, we silently skip it.
    pack = convo.context_pack if convo.context_pack_id else None

    payload = _build_message_payload(
        history,
        cleaned,
        context_pack=pack,
        attachments=attachments,
    )

    try:
        completion = chat_completion(
            api_key, model=chosen_model, messages=payload, provider=chosen_provider
        )
    except LLMError as err:
        raise ChatError(err.code, err.message, status=err.status) from err

    assistant_msg = Message(
        conversation_id=convo.id,
        role="assistant",
        content=completion.content,
        model=completion.model or chosen_model,
        provider=chosen_provider,
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
        total_tokens=completion.total_tokens,
    )
    db.session.add(assistant_msg)

    convo.last_message_at = _utcnow()
    db.session.add(convo)
    db.session.commit()

    # Refresh the user message so its `.attachments` relationship sees
    # the stamped rows when callers serialize to JSON.
    db.session.refresh(user_msg)

    return user_msg, assistant_msg, convo


def delete_conversation(user: User, conversation_id: int) -> None:
    convo = get_conversation_for_user(user, conversation_id)
    db.session.delete(convo)
    db.session.commit()


__all__ = [
    "ChatError",
    "DEFAULT_MODEL",
    "MAX_LIST_LIMIT",
    "count_for_user",
    "create_conversation",
    "delete_conversation",
    "get_conversation_for_user",
    "list_for_project",
    "list_messages",
    "list_recent_for_user",
    "send_user_message",
    "set_context_pack",
]
