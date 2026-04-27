"""Token + cost usage aggregation for the dashboard.

We pull the relevant message rows from SQL and do the bucketing in
Python — SQLite's date functions vary across dialects and we want the
output to be timezone-correct (UTC) and gap-filled regardless.

Buckets are anchored to the user's "now" (UTC) and then labeled in the
output so the frontend doesn't need to recompute times. An empty bucket
still comes back with zeros so the chart draws a smooth baseline.

Only ``assistant``-role messages are counted — the LLM's reply is what
actually gets billed; storing prompt_tokens on the assistant message
captures the prompt it was answered from.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.extensions import db
from app.models import Message, Conversation
from app.pricing import estimate_cost

# Granularities we support. Values: (bucket count, bucket width).
GRANULARITIES: dict[str, tuple[int, timedelta]] = {
    "hour": (24, timedelta(hours=1)),
    "day": (30, timedelta(days=1)),
    "week": (12, timedelta(weeks=1)),
    "month": (12, timedelta(days=30)),  # approximated; labeled by month anyway
}


@dataclass
class UsageBucket:
    """One time bucket's aggregated metrics."""

    start: datetime
    end: datetime
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    message_count: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> dict:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "message_count": self.message_count,
        }


class UsageError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _normalize_granularity(granularity: str | None) -> str:
    g = (granularity or "day").strip().lower()
    if g not in GRANULARITIES:
        raise UsageError(
            "validation_error",
            f"granularity must be one of: {', '.join(GRANULARITIES)}.",
            status=422,
        )
    return g


def _floor_to_bucket(dt: datetime, granularity: str) -> datetime:
    """Round ``dt`` *down* to the start of its bucket."""
    dt = dt.astimezone(timezone.utc)
    if granularity == "hour":
        return dt.replace(minute=0, second=0, microsecond=0)
    if granularity == "day":
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    if granularity == "week":
        # ISO week: start on Monday.
        monday = dt - timedelta(days=dt.weekday())
        return monday.replace(hour=0, minute=0, second=0, microsecond=0)
    if granularity == "month":
        return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    raise UsageError("validation_error", f"Unknown granularity: {granularity}")


def _advance_bucket(start: datetime, granularity: str) -> datetime:
    if granularity == "hour":
        return start + timedelta(hours=1)
    if granularity == "day":
        return start + timedelta(days=1)
    if granularity == "week":
        return start + timedelta(weeks=1)
    if granularity == "month":
        # +1 calendar month.
        if start.month == 12:
            return start.replace(year=start.year + 1, month=1)
        return start.replace(month=start.month + 1)
    raise UsageError("validation_error", f"Unknown granularity: {granularity}")


def _build_empty_buckets(
    now: datetime, granularity: str
) -> list[UsageBucket]:
    """Return ``count`` contiguous buckets ending at (or just after) ``now``."""
    count = GRANULARITIES[granularity][0]
    current_end_start = _floor_to_bucket(now, granularity)
    # We want the last bucket to include `now`, so its start is
    # current_end_start. The first bucket is count-1 buckets earlier.
    starts: list[datetime] = [current_end_start]
    cur = current_end_start
    for _ in range(count - 1):
        # Step backward. For month we rely on year rollover.
        if granularity == "month":
            if cur.month == 1:
                cur = cur.replace(year=cur.year - 1, month=12)
            else:
                cur = cur.replace(month=cur.month - 1)
        else:
            _, width = GRANULARITIES[granularity]
            cur = cur - width
        starts.append(cur)
    starts.reverse()

    buckets: list[UsageBucket] = []
    for start in starts:
        end = _advance_bucket(start, granularity)
        buckets.append(UsageBucket(start=start, end=end))
    return buckets


def _bucket_for_timestamp(
    ts: datetime, buckets: list[UsageBucket]
) -> UsageBucket | None:
    """Binary-ish lookup. Buckets are in ascending order, contiguous."""
    if not buckets:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    if ts < buckets[0].start or ts >= buckets[-1].end:
        return None
    # Linear scan is fine — never more than 30 buckets.
    for b in buckets:
        if b.start <= ts < b.end:
            return b
    return None


def summary_for_user(user, *, granularity: str | None = "day") -> dict:
    """Aggregate the caller's assistant-message usage into buckets.

    Shape:

        {
          "granularity": "day",
          "now": "<ISO8601 UTC>",
          "buckets": [ {start, end, prompt_tokens, ...}, ... ],
          "totals": {prompt_tokens, completion_tokens, total_tokens, cost_usd, message_count},
          "window": {"start": "...", "end": "..."}
        }
    """
    g = _normalize_granularity(granularity)
    now = datetime.now(timezone.utc)
    buckets = _build_empty_buckets(now, g)
    window_start = buckets[0].start
    window_end = buckets[-1].end

    stmt = (
        select(
            Message.prompt_tokens,
            Message.completion_tokens,
            Message.model,
            Message.provider,
            Message.created_at,
            Conversation.provider.label("convo_provider"),
        )
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Conversation.user_id == user.id,
            Message.role == "assistant",
            Message.created_at >= window_start,
            Message.created_at < window_end,
        )
    )
    rows = db.session.execute(stmt).all()

    totals_prompt = 0
    totals_completion = 0
    totals_cost = 0.0
    totals_messages = 0

    for row in rows:
        (
            pt,
            ct,
            model_id,
            msg_provider,
            created_at,
            convo_provider,
        ) = row
        provider = msg_provider or convo_provider or None
        cost = estimate_cost(pt, ct, model_id, provider)
        bucket = _bucket_for_timestamp(created_at, buckets)
        if bucket is None:
            continue
        bucket.prompt_tokens += pt or 0
        bucket.completion_tokens += ct or 0
        bucket.cost_usd += cost
        bucket.message_count += 1

        totals_prompt += pt or 0
        totals_completion += ct or 0
        totals_cost += cost
        totals_messages += 1

    return {
        "granularity": g,
        "now": now.isoformat(),
        "buckets": [b.to_dict() for b in buckets],
        "totals": {
            "prompt_tokens": totals_prompt,
            "completion_tokens": totals_completion,
            "total_tokens": totals_prompt + totals_completion,
            "cost_usd": round(totals_cost, 6),
            "message_count": totals_messages,
        },
        "window": {
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
        },
    }


__all__ = ["GRANULARITIES", "UsageBucket", "UsageError", "summary_for_user"]
