"""Layer 3c: System Prompt Compression Analysis.

Detects content loss in system prompts due to truncation (OpenClaw's
70/20/10 split) or compaction (/compact).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any

from claw_llm_doctor.loader import Session
from claw_llm_doctor.analyzers.prompt_order import extract_system_text, detect_sections
from claw_llm_doctor.utils.tokens import count_tokens


# -- Result types ----------------------------------------------------------


@dataclass
class TruncationInfo:
    """Truncation detection for a single turn."""

    turn_index: int
    is_truncated: bool = False
    truncation_markers: list[str] = field(default_factory=list)
    original_length: int | None = None  # from baseline
    current_length: int = 0
    loss_ratio: float = 0.0  # 0.0 = no loss, 1.0 = total loss


@dataclass
class CompactionInfo:
    """Compaction detection at a specific turn."""

    turn_index: int
    before_length: int = 0
    after_length: int = 0
    compression_ratio: float = 0.0
    preserved_entities: list[str] = field(default_factory=list)  # file paths, IDs, etc.
    lost_sections: list[str] = field(default_factory=list)


@dataclass
class CompressionReport:
    """System prompt compression analysis report."""

    session_key: str
    baseline_length: int = 0  # first turn's system prompt length
    baseline_sections: list[str] = field(default_factory=list)

    truncations: list[TruncationInfo] = field(default_factory=list)
    compactions: list[CompactionInfo] = field(default_factory=list)

    # Overall metrics
    max_loss_ratio: float = 0.0
    turns_with_loss: int = 0

    # Similarity scores per turn (vs baseline)
    similarity_curve: list[float] = field(default_factory=list)


# -- Truncation markers ----------------------------------------------------

TRUNCATION_MARKERS = [
    "... (truncated)",
    "[TRUNCATED]",
    "<!-- truncated -->",
    "\u26a0\ufe0f Content truncated",
    "... content continues",
    "[Content exceeded",
]


# -- Entity extraction (for compaction preservation check) -----------------

# Patterns for important entities that should survive compaction
ENTITY_PATTERNS = [
    re.compile(r"(?:^|[\s\(])(/[\w.\-/]+\.\w+)"),  # file paths
    re.compile(r"\b([A-Z_]{2,}\.md)\b"),  # markdown files like AGENTS.md
    re.compile(r"\b(function|class|def)\s+(\w+)"),  # code definitions
    re.compile(r"\b(\w+_id|session_?key)\b", re.IGNORECASE),  # identifiers
]


def extract_entities(text: str) -> set[str]:
    """Extract notable entities from text (file paths, IDs, definitions)."""
    entities: set[str] = set()
    for pattern in ENTITY_PATTERNS:
        for m in pattern.finditer(text):
            entities.add(m.group(0).strip())
    return entities


# -- Analysis --------------------------------------------------------------


def check_truncation(text: str) -> list[str]:
    """Check if a system prompt contains truncation markers."""
    found: list[str] = []
    lower = text.lower()
    for marker in TRUNCATION_MARKERS:
        if marker.lower() in lower:
            found.append(marker)
    return found


def text_similarity(a: str, b: str) -> float:
    """Compute similarity ratio between two texts (0.0 to 1.0)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def analyze_compression(session: Session, token_method: str = "char") -> CompressionReport:
    """Run system prompt compression analysis for a session."""
    report = CompressionReport(session_key=session.key)

    inputs = session.llm_inputs
    if not inputs:
        return report

    # Extract system prompts for each turn
    prompts: list[tuple[int, str]] = []
    for i, inp in enumerate(inputs):
        text = extract_system_text(inp)
        if text is not None:
            prompts.append((i, text))

    if not prompts:
        return report

    # Baseline: first turn's system prompt
    baseline_idx, baseline_text = prompts[0]
    report.baseline_length = len(baseline_text)
    baseline_sections = detect_sections(baseline_text)
    report.baseline_sections = [s.label for s in baseline_sections]
    baseline_entities = extract_entities(baseline_text)

    prev_text = baseline_text

    for turn_idx, text in prompts:
        # Similarity vs baseline
        sim = text_similarity(baseline_text, text)
        report.similarity_curve.append(sim)

        # Truncation check
        markers = check_truncation(text)
        loss_ratio = 1.0 - (len(text) / report.baseline_length) if report.baseline_length > 0 else 0.0
        loss_ratio = max(0.0, loss_ratio)  # clamp -- text can grow

        trunc = TruncationInfo(
            turn_index=turn_idx,
            is_truncated=bool(markers),
            truncation_markers=markers,
            original_length=report.baseline_length,
            current_length=len(text),
            loss_ratio=loss_ratio,
        )
        report.truncations.append(trunc)

        if loss_ratio > 0:
            report.turns_with_loss += 1
            report.max_loss_ratio = max(report.max_loss_ratio, loss_ratio)

        # Compaction detection: sudden size drop vs previous turn
        if len(text) < len(prev_text) * 0.5 and turn_idx > baseline_idx:
            current_entities = extract_entities(text)
            preserved = sorted(baseline_entities & current_entities)

            # Check which section labels disappeared
            current_sections = detect_sections(text)
            current_labels = {s.label for s in current_sections}
            baseline_labels = set(report.baseline_sections)
            lost = sorted(baseline_labels - current_labels)

            compaction = CompactionInfo(
                turn_index=turn_idx,
                before_length=len(prev_text),
                after_length=len(text),
                compression_ratio=1.0 - (len(text) / len(prev_text)) if len(prev_text) > 0 else 0.0,
                preserved_entities=preserved[:20],  # cap for readability
                lost_sections=lost,
            )
            report.compactions.append(compaction)

        prev_text = text

    return report
