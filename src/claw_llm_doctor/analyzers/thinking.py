"""Layer 3d: Thinking Process Analysis.

Analyzes the model's thinking blocks for cleanliness, separation quality,
and potential leakage into the response content.

Detects three categories of leakage (from real-world bug observations):
1. Tagged leaks -- think_never_used_* or <thinking>/<think> tags in content
2. Untagged leaks -- reasoning/deliberation in content (EN + CN patterns)
3. Token interleaving -- garbled fragments from parallel thinking/content streams
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from claw_llm_doctor.loader import Record, Session
from claw_llm_doctor.utils.tokens import count_tokens


# -- Thinking leakage patterns ------------------------------------------------

# Category 1: Explicit thinking tags leaked into content
TAG_LEAK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Volcengine Ark API internal tag
    ("ark_think_tag", re.compile(r"</?think_never_used[^>]*>", re.IGNORECASE)),
    # Standard thinking/reasoning XML tags
    ("xml_thinking_tag", re.compile(r"</?(?:thinking|think|reasoning|thought|inner_monologue)>", re.IGNORECASE)),
    # Thinking block prefix in plain text
    ("thinking_prefix", re.compile(r"^(?:thinking|thought|reasoning|inner monologue):\s", re.IGNORECASE | re.MULTILINE)),
]

# Category 2: Inner monologue phrases (English)
EN_MONOLOGUE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("en_self_direction", re.compile(r"\b(?:let me think|i need to|i should|let me consider|let me (?:re)?read)\b", re.IGNORECASE)),
    ("en_reasoning_step", re.compile(r"\b(?:step \d+:|first,? i|next,? i|then,? i)\b", re.IGNORECASE)),
    ("en_self_correction", re.compile(r"\b(?:wait,? (?:actually|no)|actually,? (?:let me|i)|on second thought)\b", re.IGNORECASE)),
    ("en_meta_reasoning", re.compile(r"\b(?:my reasoning|my approach|i(?:'m| am) thinking)\b", re.IGNORECASE)),
    ("en_planning", re.compile(r"\b(?:my plan is|here(?:'s| is) my plan|the plan:)\b", re.IGNORECASE)),
    ("en_deliberation", re.compile(r"\b(?:hmm,? |okay,? (?:so|let)|that's backwards|let me (?:see|check|look))\b", re.IGNORECASE)),
]

# Category 2: Inner monologue phrases (Chinese)
CN_MONOLOGUE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("cn_self_direction", re.compile(r"(?:让我(?:想想|看看|再想|考虑|检查)|我(?:需要|应该|来)(?:想|看|检查|分析))")),
    ("cn_self_correction", re.compile(r"(?:不对[，,]|等等[，,]|等一下[，,]?|不[，,](?:因为|应该)|(?:啊)?不对)")),
    ("cn_deliberation", re.compile(r"(?:或者[，,]?我应该|所以(?:也许|我应该|回复)|那我应该|也许这次)")),
    ("cn_self_question", re.compile(r"(?:我应该回复.*吗[？?]|这次不需要.*了[？?]?|怎么给.*[？?])")),
    ("cn_meta_reasoning", re.compile(r"(?:我的(?:想法|思路|推理|分析)|原文(?:说|是)|用户(?:说的是|给的指令))")),
    ("cn_internal_conclusion", re.compile(r"(?:可以结束了[。.]|所以回复|现在任务完成[：:])")),
]

# Category 3: Token interleaving detection
# When thinking/content streams cross-contaminate, you get patterns like
# Chinese text interrupted by short (2-4 char) uppercase English fragments
INTERLEAVE_PATTERN = re.compile(
    r"[\u4e00-\u9fff]"          # CJK character
    r"[A-Z]{2,5}"              # short uppercase fragment (e.g. HE, ART, BE, AT)
    r"[\u4e00-\u9fff。，！？]"  # CJK or CN punctuation
)

# Combined LEAKAGE_PATTERNS for backward compatibility
LEAKAGE_PATTERNS: list[tuple[str, re.Pattern[str]]] = (
    TAG_LEAK_PATTERNS + EN_MONOLOGUE_PATTERNS + CN_MONOLOGUE_PATTERNS
)


# -- Result types -------------------------------------------------------------


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
    category: str = "unknown"  # tag_leak, en_monologue, cn_monologue, interleave


@dataclass
class TurnThinkingAnalysis:
    """Thinking analysis for a single turn."""

    turn_index: int
    model: str | None = None
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
        # Tag leaks and interleaving are always high severity
        if any(li.category in ("tag_leak", "interleave") for li in self.leakage_instances):
            return "high"
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
    leakage_category_counts: dict[str, int] = field(default_factory=dict)

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


# -- Analysis -----------------------------------------------------------------

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
    """Detect thinking patterns that leaked into content text.

    Checks for:
    1. Explicit thinking tags (highest confidence)
    2. English inner monologue phrases
    3. Chinese inner monologue phrases
    4. Token interleaving (CJK/English fragment mixing)
    """
    instances: list[LeakageInstance] = []

    # Tag leaks (highest confidence)
    for name, pattern in TAG_LEAK_PATTERNS:
        for m in pattern.finditer(content_text):
            start = max(0, m.start() - 40)
            end = min(len(content_text), m.end() + 40)
            instances.append(
                LeakageInstance(
                    pattern_name=name,
                    matched_text=m.group(0),
                    context=content_text[start:end],
                    category="tag_leak",
                )
            )

    # English monologue patterns
    for name, pattern in EN_MONOLOGUE_PATTERNS:
        for m in pattern.finditer(content_text):
            start = max(0, m.start() - 40)
            end = min(len(content_text), m.end() + 40)
            instances.append(
                LeakageInstance(
                    pattern_name=name,
                    matched_text=m.group(0),
                    context=content_text[start:end],
                    category="en_monologue",
                )
            )

    # Chinese monologue patterns
    for name, pattern in CN_MONOLOGUE_PATTERNS:
        for m in pattern.finditer(content_text):
            start = max(0, m.start() - 40)
            end = min(len(content_text), m.end() + 40)
            instances.append(
                LeakageInstance(
                    pattern_name=name,
                    matched_text=m.group(0),
                    context=content_text[start:end],
                    category="cn_monologue",
                )
            )

    # Token interleaving detection
    for m in INTERLEAVE_PATTERN.finditer(content_text):
        start = max(0, m.start() - 40)
        end = min(len(content_text), m.end() + 40)
        instances.append(
            LeakageInstance(
                pattern_name="token_interleave",
                matched_text=m.group(0),
                context=content_text[start:end],
                category="interleave",
            )
        )

    return instances


def _split_tagged_leak(content_text: str) -> tuple[str, str]:
    """If content has a think_never_used tag, split into (reasoning, actual).

    Returns ("", content_text) if no tag found.
    """
    m = re.search(r"</think_never_used[^>]*>", content_text)
    if m:
        reasoning = content_text[:m.start()]
        actual = content_text[m.end():]
        return reasoning, actual
    return "", content_text


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

        # Fall back to top-level payload.thinking for compatibility
        thinking_raw = payload.get("thinking")
        if isinstance(thinking_raw, list):
            thinking_blocks = extract_thinking_blocks(thinking_raw, token_method)

        # Also try legacy payload.content (pre-SDK-alignment logs)
        if not content_raw:
            legacy_content = payload.get("content")
            if isinstance(legacy_content, list):
                content_raw = legacy_content

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

        # Check for tagged leaks embedded in content text.
        # If a think_never_used tag is found, the text before it is reasoning
        # that was leaked -- count it toward thinking tokens.
        leaked_reasoning, actual_content = _split_tagged_leak(content_text)
        if leaked_reasoning:
            leaked_tokens = count_tokens(leaked_reasoning, token_method)
            thinking_tokens += leaked_tokens
            # Recount content tokens on the actual response part only
            content_tokens = count_tokens(actual_content, token_method)

        # Detect leakage (run on the FULL content_text so tags are detected)
        leakage = detect_leakage(content_text) if content_text else []

        turn = TurnThinkingAnalysis(
            turn_index=i,
            model=out.model,
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
        if thinking_blocks or leaked_reasoning:
            report.turns_with_thinking += 1
        if leakage:
            report.turns_with_leakage += 1
            for li in leakage:
                report.leakage_pattern_counts[li.pattern_name] = (
                    report.leakage_pattern_counts.get(li.pattern_name, 0) + 1
                )
                report.leakage_category_counts[li.category] = (
                    report.leakage_category_counts.get(li.category, 0) + 1
                )

    return report
