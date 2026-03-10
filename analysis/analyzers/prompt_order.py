"""Layer 3b: System Prompt Ordering Analysis.

Analyzes the structure and ordering of system prompt sections across turns
to detect reordering, displacement after compaction, or inconsistencies.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from loader import Record, Session


# ── Section detection ─────────────────────────────────────────────────────

# Known markers/delimiters used by OpenClaw in system prompts.
# These patterns identify the boundaries between sections.
SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("CORE", re.compile(r"^#\s*(System|Instructions|Core)\b", re.IGNORECASE | re.MULTILINE)),
    ("WORKSPACE", re.compile(r"^#\s*(Project|Workspace|AGENTS\.md|MEMORY\.md)\b", re.IGNORECASE | re.MULTILINE)),
    ("SKILL", re.compile(r"^#\s*(Skills?|Available Skills)\b", re.IGNORECASE | re.MULTILINE)),
    ("MEMORY", re.compile(r"^#\s*(Memory|Session Memory|Context)\b", re.IGNORECASE | re.MULTILINE)),
    ("COMPACT", re.compile(r"(compacted|summary of|conversation summary)", re.IGNORECASE)),
    ("TOOL", re.compile(r"^#\s*(Tools?|Available Tools|Tool Definitions)\b", re.IGNORECASE | re.MULTILINE)),
    ("ENVIRONMENT", re.compile(r"^#\s*(Environment|Runtime|System Info)\b", re.IGNORECASE | re.MULTILINE)),
]


@dataclass
class PromptSection:
    """A detected section within the system prompt."""

    label: str
    start_pos: int
    end_pos: int
    content_hash: str  # SHA-256 of content for change detection
    char_length: int

    @property
    def content_preview(self) -> str:
        """Not stored — just for the hash. Use raw prompt to reconstruct."""
        return ""


@dataclass
class TurnPromptStructure:
    """System prompt structure for a single turn."""

    turn_index: int
    sections: list[PromptSection] = field(default_factory=list)
    raw_length: int = 0

    @property
    def order_signature(self) -> str:
        """Ordered label sequence — used to detect reordering."""
        return " -> ".join(s.label for s in self.sections)

    @property
    def content_signature(self) -> str:
        """Hash of all section hashes — used to detect content changes."""
        combined = "|".join(f"{s.label}:{s.content_hash}" for s in self.sections)
        return hashlib.sha256(combined.encode()).hexdigest()[:16]


@dataclass
class PromptOrderReport:
    """System prompt ordering analysis report."""

    session_key: str
    turns: list[TurnPromptStructure] = field(default_factory=list)
    order_changes: list[dict[str, Any]] = field(default_factory=list)
    content_changes: list[dict[str, Any]] = field(default_factory=list)
    missing_sections: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_stable(self) -> bool:
        """True if the prompt ordering never changed across turns."""
        return len(self.order_changes) == 0


# ── Analysis ──────────────────────────────────────────────────────────────


def extract_system_text(record: Record) -> str | None:
    """Extract the system prompt text from an llm.input record."""
    payload = record.payload
    if not payload:
        return None

    system = payload.get("system")
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        # Array of content blocks — concatenate text parts
        parts = []
        for block in system:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts) if parts else None
    return None


def detect_sections(text: str) -> list[PromptSection]:
    """Detect and label sections within a system prompt string."""
    # Find all section boundary matches
    matches: list[tuple[str, int]] = []
    for label, pattern in SECTION_PATTERNS:
        for m in pattern.finditer(text):
            matches.append((label, m.start()))

    if not matches:
        # No recognizable sections — treat entire text as one section
        h = hashlib.sha256(text.encode()).hexdigest()[:16]
        return [PromptSection(label="UNKNOWN", start_pos=0, end_pos=len(text), content_hash=h, char_length=len(text))]

    # Sort by position
    matches.sort(key=lambda x: x[1])

    sections: list[PromptSection] = []
    for i, (label, start) in enumerate(matches):
        end = matches[i + 1][1] if i + 1 < len(matches) else len(text)
        content = text[start:end]
        h = hashlib.sha256(content.encode()).hexdigest()[:16]
        sections.append(
            PromptSection(
                label=label,
                start_pos=start,
                end_pos=end,
                content_hash=h,
                char_length=len(content),
            )
        )
    return sections


def analyze_prompt_order(session: Session) -> PromptOrderReport:
    """Run system prompt ordering analysis for a session."""
    report = PromptOrderReport(session_key=session.key)

    for i, inp in enumerate(session.llm_inputs):
        text = extract_system_text(inp)
        if text is None:
            continue

        sections = detect_sections(text)
        turn_struct = TurnPromptStructure(
            turn_index=i,
            sections=sections,
            raw_length=len(text),
        )
        report.turns.append(turn_struct)

    # Detect changes between consecutive turns
    for i in range(1, len(report.turns)):
        prev = report.turns[i - 1]
        curr = report.turns[i]

        # Order change?
        if prev.order_signature != curr.order_signature:
            report.order_changes.append(
                {
                    "turn": curr.turn_index,
                    "prev_order": prev.order_signature,
                    "curr_order": curr.order_signature,
                }
            )

        # Content change?
        if prev.content_signature != curr.content_signature:
            # Find which sections changed
            prev_map = {s.label: s.content_hash for s in prev.sections}
            curr_map = {s.label: s.content_hash for s in curr.sections}

            changed = [
                label
                for label in set(prev_map) | set(curr_map)
                if prev_map.get(label) != curr_map.get(label)
            ]
            report.content_changes.append(
                {
                    "turn": curr.turn_index,
                    "changed_sections": changed,
                }
            )

        # Missing sections?
        prev_labels = {s.label for s in prev.sections}
        curr_labels = {s.label for s in curr.sections}
        missing = prev_labels - curr_labels
        if missing:
            report.missing_sections.append(
                {
                    "turn": curr.turn_index,
                    "missing": sorted(missing),
                }
            )

    return report
