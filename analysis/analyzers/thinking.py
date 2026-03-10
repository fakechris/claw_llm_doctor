"""Layer 3d: Thinking Process Analysis.

Analyzes the model's thinking blocks for cleanliness, separation quality,
and potential leakage into the response content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from loader import Record, Session
from utils.tokens import count_tokens


# ── Thinking leakage patterns ─────────────────────────────────────────────

# Patterns that suggest thinking/reasoning leaked into content blocks.
# These are common "inner monologue" phrases that shouldn't appear in final output.
LEAKAGE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("self_direction", re.compile(r"\b(let me think|i need to|i should|let me consider)\b", re.IGNORECASE)),
    ("reasoning_step", re.compile(r"\b(step \d+:|first,? i|next,? i|then,? i)\b", re.IGNORECASE)),
    ("self_correction", re.compile(r"\b(wait,? (actually|no)|actually,? (let me|i)|on second thought)\b", re.IGNORECASE)),
    ("meta_reasoning", re.compile(r"\b(my reasoning|my approach|i('m| am) thinking)\b", re.IGNORECASE)),
    ("planning", re.compile(r"\b(my plan is|here('s| is) my plan|the plan:)\b", re.IGNORECASE)),
    ("xml_thinking_tag", re.compile(r"</?thinking>", re.IGNORECASE)),
    ("thinking_prefix", re.compile(r"^(thinking|thought):\s", re.IGNORECASE | re.MULTILINE)),
]


# ── Result types ──────────────────────────────────────────────────────────


@dataclass
class ThinkingBlock:
    """A single thinking block from a response."""

    text: str
    token_count: int = 0
    category: str = "general"  # planning, reasoning, self_correction, tool_selection, code_review


@dataclass
class LeakageInstance:
    """A detected instance of thinking leaking into content."""

    pattern_name: str
    matched_text: str
    context: str  # surrounding text for review


@dataclass
class TurnThinkingAnalysis:
    """Thinking analysis for a single turn."""

    turn_index: int
    thinking_blocks: list[ThinkingBlock] = field(default_factory=list)
    content_text: str = ""
    leakage_instances: list[LeakageInstance] = field(default_factory=list)

    thinking_tokens: int = 0
    content_tokens: int = 0

    @property
    def has_thinking(self) -> bool:
        return len(self.thinking_blocks) > 0

    @property
    def thinking_ratio(self) -> float:
        """Ratio of thinking tokens to total output tokens."""
        total = self.thinking_tokens + self.content_tokens
        if total == 0:
            return 0.0
        return self.thinking_tokens / total

    @property
    def has_leakage(self) -> bool:
        return len(self.leakage_instances) > 0

    @property
    def leakage_severity(self) -> str:
        """none / low / medium / high."""
        n = len(self.leakage_instances)
        if n == 0:
            return "none"
        if n <= 2:
            return "low"
        if n <= 5:
            return "medium"
        return "high"


@dataclass
class ThinkingReport:
    """Thinking process analysis report."""

    session_key: str
    turns: list[TurnThinkingAnalysis] = field(default_factory=list)

    # Aggregate metrics
    total_thinking_tokens: int = 0
    total_content_tokens: int = 0
    turns_with_thinking: int = 0
    turns_with_leakage: int = 0
    leakage_pattern_counts: dict[str, int] = field(default_factory=dict)

    @property
    def overall_thinking_ratio(self) -> float:
        total = self.total_thinking_tokens + self.total_content_tokens
        if total == 0:
            return 0.0
        return self.total_thinking_tokens / total

    @property
    def leakage_rate(self) -> float:
        """Fraction of turns with thinking that have leakage."""
        if self.turns_with_thinking == 0:
            return 0.0
        return self.turns_with_leakage / self.turns_with_thinking


# ── Analysis ──────────────────────────────────────────────────────────────

# Categories for classifying thinking block content
CATEGORY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("planning", re.compile(r"\b(plan|approach|strategy|outline|steps)\b", re.IGNORECASE)),
    ("tool_selection", re.compile(r"\b(tool|function|call|invoke|use the)\b", re.IGNORECASE)),
    ("code_review", re.compile(r"\b(code|bug|fix|refactor|implement)\b", re.IGNORECASE)),
    ("self_correction", re.compile(r"\b(wait|actually|correction|mistake|wrong)\b", re.IGNORECASE)),
    ("reasoning", re.compile(r"\b(because|therefore|since|given that|implies)\b", re.IGNORECASE)),
]


def classify_thinking(text: str) -> str:
    """Classify a thinking block by its dominant theme."""
    scores: dict[str, int] = {}
    for category, pattern in CATEGORY_PATTERNS:
        scores[category] = len(pattern.findall(text))
    if not any(scores.values()):
        return "general"
    return max(scores, key=lambda k: scores[k])


def extract_thinking_blocks(content_blocks: list[Any], token_method: str = "char") -> list[ThinkingBlock]:
    """Extract thinking blocks from response content."""
    blocks: list[ThinkingBlock] = []
    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "thinking":
            text = block.get("thinking", "") or block.get("text", "")
            if not isinstance(text, str):
                continue
            blocks.append(
                ThinkingBlock(
                    text=text,
                    token_count=count_tokens(text, token_method),
                    category=classify_thinking(text),
                )
            )
    return blocks


def extract_content_text(content_blocks: list[Any]) -> str:
    """Extract non-thinking text content from response."""
    parts: list[str] = []
    for block in content_blocks:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            btype = block.get("type", "")
            if btype == "text":
                parts.append(block.get("text", ""))
            elif btype == "thinking":
                continue  # skip thinking blocks
            elif btype == "tool_use":
                continue  # skip tool calls
    return "\n".join(parts)


def detect_leakage(content_text: str) -> list[LeakageInstance]:
    """Detect thinking patterns that leaked into content text."""
    instances: list[LeakageInstance] = []
    for name, pattern in LEAKAGE_PATTERNS:
        for m in pattern.finditer(content_text):
            start = max(0, m.start() - 40)
            end = min(len(content_text), m.end() + 40)
            instances.append(
                LeakageInstance(
                    pattern_name=name,
                    matched_text=m.group(0),
                    context=content_text[start:end],
                )
            )
    return instances


def analyze_thinking(session: Session, token_method: str = "char") -> ThinkingReport:
    """Run thinking process analysis for a session."""
    report = ThinkingReport(session_key=session.key)

    outputs = session.llm_outputs
    for i, out in enumerate(outputs):
        payload = out.payload
        if not payload:
            continue

        # Extract thinking and content from the actual SDK shape.
        # SDK provides: payload.assistantTexts (string[]), payload.lastAssistant
        # lastAssistant has .content (content block array) with type=thinking and type=text blocks
        thinking_blocks: list[ThinkingBlock] = []
        content_text = ""

        # Try lastAssistant.content first (structured content blocks)
        last_assistant = payload.get("lastAssistant")
        content_raw = None
        if isinstance(last_assistant, dict):
            content_raw = last_assistant.get("content")

        # Fall back to top-level payload.thinking / payload.content for compatibility
        thinking_raw = payload.get("thinking")
        if isinstance(thinking_raw, list):
            thinking_blocks = extract_thinking_blocks(thinking_raw, token_method)

        if isinstance(content_raw, list):
            # Content blocks may include both thinking and text blocks
            thinking_blocks.extend(extract_thinking_blocks(content_raw, token_method))
            content_text = extract_content_text(content_raw)
        elif not content_raw:
            # Fall back to assistantTexts
            assistant_texts = payload.get("assistantTexts")
            if isinstance(assistant_texts, list):
                content_text = "\n".join(str(t) for t in assistant_texts if t)

        thinking_tokens = sum(b.token_count for b in thinking_blocks)
        content_tokens = count_tokens(content_text, token_method)

        # Also use reported usage if available
        usage = out.usage
        if usage and isinstance(usage, dict):
            reported_thinking = usage.get("thinkingTokens")
            if isinstance(reported_thinking, int) and reported_thinking > 0:
                thinking_tokens = max(thinking_tokens, reported_thinking)

        # Detect leakage
        leakage = detect_leakage(content_text) if content_text else []

        turn = TurnThinkingAnalysis(
            turn_index=i,
            thinking_blocks=thinking_blocks,
            content_text=content_text[:500],  # truncate for report
            leakage_instances=leakage,
            thinking_tokens=thinking_tokens,
            content_tokens=content_tokens,
        )
        report.turns.append(turn)

        # Aggregate
        report.total_thinking_tokens += thinking_tokens
        report.total_content_tokens += content_tokens
        if thinking_blocks:
            report.turns_with_thinking += 1
        if leakage:
            report.turns_with_leakage += 1
            for li in leakage:
                report.leakage_pattern_counts[li.pattern_name] = (
                    report.leakage_pattern_counts.get(li.pattern_name, 0) + 1
                )

    return report
