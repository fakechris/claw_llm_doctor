"""Layer 3a: Context Length & Composition Analysis.

Analyzes context window utilization per LLM call: breaks down system prompts,
tool definitions, conversation history, tool results, and thinking blocks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loader import Record, Session
from utils.tokens import count_tokens, format_tokens


# ── Result types ──────────────────────────────────────────────────────────


@dataclass
class ContextComposition:
    """Token breakdown for a single LLM call's input."""

    turn_index: int = 0
    model: str | None = None
    context_limit: int | None = None

    system_tokens: int = 0
    tool_def_tokens: int = 0
    history_tokens: int = 0
    tool_result_tokens: int = 0
    thinking_tokens: int = 0  # thinking blocks from prior turns in history
    image_tokens: int = 0
    other_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.system_tokens
            + self.tool_def_tokens
            + self.history_tokens
            + self.tool_result_tokens
            + self.thinking_tokens
            + self.image_tokens
            + self.other_tokens
        )

    @property
    def utilization(self) -> float:
        """Context window utilization ratio (0.0 - 1.0)."""
        if not self.context_limit or self.context_limit <= 0:
            return 0.0
        return self.total_tokens / self.context_limit

    @property
    def health(self) -> str:
        """Health indicator: green / yellow / red."""
        u = self.utilization
        if u < 0.80:
            return "green"
        if u < 0.95:
            return "yellow"
        return "red"

    def as_dict(self) -> dict[str, Any]:
        return {
            "turn": self.turn_index,
            "model": self.model,
            "context_limit": self.context_limit,
            "system": self.system_tokens,
            "tool_defs": self.tool_def_tokens,
            "history": self.history_tokens,
            "tool_results": self.tool_result_tokens,
            "thinking": self.thinking_tokens,
            "images": self.image_tokens,
            "other": self.other_tokens,
            "total": self.total_tokens,
            "utilization": round(self.utilization, 4),
            "health": self.health,
        }


@dataclass
class ContextReport:
    """Context analysis report for a session."""

    session_key: str
    turns: list[ContextComposition] = field(default_factory=list)
    compaction_events: list[int] = field(default_factory=list)  # turn indices
    large_payloads: list[dict[str, Any]] = field(default_factory=list)

    @property
    def peak_utilization(self) -> float:
        if not self.turns:
            return 0.0
        return max(t.utilization for t in self.turns)

    @property
    def avg_utilization(self) -> float:
        if not self.turns:
            return 0.0
        return sum(t.utilization for t in self.turns) / len(self.turns)

    def growth_curve(self) -> list[dict]:
        """Return a list of dicts describing context growth over the session.

        Each entry contains:
            turn_index, total_tokens, system_tokens, history_tokens,
            delta (change from previous turn)

        Useful for visualization of context growth.
        """
        curve: list[dict] = []
        prev_total = 0
        for turn in self.turns:
            total = turn.total_tokens
            curve.append(
                {
                    "turn_index": turn.turn_index,
                    "total_tokens": total,
                    "system_tokens": turn.system_tokens,
                    "history_tokens": turn.history_tokens,
                    "delta": total - prev_total,
                }
            )
            prev_total = total
        return curve


# ── Analysis ──────────────────────────────────────────────────────────────

LARGE_TOOL_RESULT_THRESHOLD = 5000  # tokens


def classify_message(msg: dict[str, Any]) -> str:
    """Classify a message by its role and content type."""
    role = msg.get("role", "")
    if role == "system":
        return "system"

    content = msg.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                btype = block.get("type", "")
                if btype == "tool_result":
                    return "tool_result"
                if btype == "thinking":
                    return "thinking"
                if btype in ("image", "image_url"):
                    return "image"
    return "history"


def analyze_composition(
    record: Record,
    turn_index: int,
    context_limit: int | None,
    token_method: str = "char",
) -> ContextComposition:
    """Break down the context composition of a single llm.input record."""
    comp = ContextComposition(
        turn_index=turn_index,
        model=record.model,
        context_limit=context_limit,
    )

    payload = record.payload
    if not payload:
        return comp

    # System prompt (SDK field: systemPrompt)
    system = payload.get("systemPrompt") or payload.get("system")
    if system:
        comp.system_tokens = count_tokens(system, token_method)

    # Tool definitions (if present)
    tools = payload.get("tools")
    if tools:
        comp.tool_def_tokens = count_tokens(tools, token_method)

    # History messages (SDK field: historyMessages)
    messages = payload.get("historyMessages") or payload.get("messages")
    if isinstance(messages, list):
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            category = classify_message(msg)
            tokens = count_tokens(msg, token_method)
            if category == "system":
                comp.system_tokens += tokens
            elif category == "tool_result":
                comp.tool_result_tokens += tokens
            elif category == "thinking":
                comp.thinking_tokens += tokens
            elif category == "image":
                comp.image_tokens += tokens
            else:
                comp.history_tokens += tokens

    # Current turn prompt (SDK field: prompt)
    prompt = payload.get("prompt")
    if prompt:
        comp.history_tokens += count_tokens(prompt, token_method)

    # Images count (SDK field: imagesCount) — estimate tokens
    images_count = payload.get("imagesCount", 0)
    if images_count:
        # Rough estimate: ~1000 tokens per image
        comp.image_tokens += images_count * 1000

    return comp


def detect_compaction(turns: list[ContextComposition]) -> list[int]:
    """Detect turns where compaction likely occurred (sudden token drop)."""
    events: list[int] = []
    for i in range(1, len(turns)):
        prev_total = turns[i - 1].total_tokens
        curr_total = turns[i].total_tokens
        if prev_total > 0 and curr_total < prev_total * 0.5:
            events.append(i)
    return events


def find_large_payloads(
    turns: list[ContextComposition],
    inputs: list[Record],
    threshold: int = LARGE_TOOL_RESULT_THRESHOLD,
) -> list[dict[str, Any]]:
    """Find turns with unusually large tool results."""
    findings: list[dict[str, Any]] = []
    for i, comp in enumerate(turns):
        if comp.tool_result_tokens > threshold:
            findings.append(
                {
                    "turn": i,
                    "tool_result_tokens": comp.tool_result_tokens,
                    "total_tokens": comp.total_tokens,
                    "model": comp.model,
                }
            )
    return findings


def analyze_context(
    session: Session,
    context_limits: dict[str, int] | None = None,
    token_method: str = "char",
) -> ContextReport:
    """Run context composition analysis for a session."""
    report = ContextReport(session_key=session.key)

    # Build context_limit lookup from diagnostic events
    limits: dict[str, int] = context_limits or {}
    for diag in session.diagnostics:
        limit = diag.raw.get("contextLimit")
        model = diag.model
        if model and isinstance(limit, int):
            limits[model] = limit

    inputs = session.llm_inputs
    for i, inp in enumerate(inputs):
        ctx_limit = limits.get(inp.model or "", None)
        comp = analyze_composition(inp, turn_index=i, context_limit=ctx_limit, token_method=token_method)
        report.turns.append(comp)

    report.compaction_events = detect_compaction(report.turns)
    report.large_payloads = find_large_payloads(report.turns, inputs)

    return report
