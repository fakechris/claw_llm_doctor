"""JSONL log file loader and session grouper.

Reads llm-doctor-*.jsonl files, parses records, and groups them into sessions.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import orjson


# ── Record types ──────────────────────────────────────────────────────────


@dataclass
class Record:
    """A single JSONL record from the plugin."""

    type: str
    ts: int
    session_key: str | None = None
    agent_id: str | None = None
    run_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    # Convenience accessors for common fields
    @property
    def model(self) -> str | None:
        return self.raw.get("model")

    @property
    def provider(self) -> str | None:
        return self.raw.get("provider")

    @property
    def payload(self) -> dict[str, Any] | None:
        return self.raw.get("payload")

    @property
    def usage(self) -> dict[str, Any] | None:
        return self.raw.get("usage")

    @property
    def success(self) -> bool:
        return self.raw.get("success", True)

    @property
    def error(self) -> str | None:
        return self.raw.get("error")

    @property
    def error_code(self) -> str | None:
        return self.raw.get("errorCode")

    @property
    def duration_ms(self) -> int | None:
        return self.raw.get("durationMs")

    @property
    def is_primary(self) -> bool | None:
        return self.raw.get("isPrimary")

    @property
    def fallback_reason(self) -> str | None:
        return self.raw.get("fallbackReason")


# ── Session grouping ──────────────────────────────────────────────────────


@dataclass
class Session:
    """A group of records sharing the same sessionKey."""

    key: str
    records: list[Record] = field(default_factory=list)

    @property
    def llm_inputs(self) -> list[Record]:
        return [r for r in self.records if r.type == "llm.input"]

    @property
    def llm_outputs(self) -> list[Record]:
        return [r for r in self.records if r.type == "llm.output"]

    @property
    def tool_starts(self) -> list[Record]:
        return [r for r in self.records if r.type == "tool.start"]

    @property
    def tool_ends(self) -> list[Record]:
        return [r for r in self.records if r.type == "tool.end"]

    @property
    def diagnostics(self) -> list[Record]:
        return [r for r in self.records if r.type == "diagnostic.usage"]

    @property
    def time_range(self) -> tuple[int, int]:
        """(start_ts, end_ts) in epoch ms."""
        ts_values = [r.ts for r in self.records]
        return (min(ts_values), max(ts_values)) if ts_values else (0, 0)


# ── Loading ───────────────────────────────────────────────────────────────


def parse_record(line: bytes) -> Record | None:
    """Parse a single JSONL line into a Record."""
    try:
        data = orjson.loads(line)
    except (orjson.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict) or "type" not in data:
        return None

    return Record(
        type=data["type"],
        ts=data.get("ts", 0),
        session_key=data.get("sessionKey"),
        agent_id=data.get("agentId"),
        run_id=data.get("runId"),
        raw=data,
    )


def load_file(path: str | Path) -> list[Record]:
    """Load all records from a single JSONL file."""
    records: list[Record] = []
    with open(path, "rb") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = parse_record(line)
            if record:
                records.append(record)
    return records


def load_dir(directory: str | Path) -> list[Record]:
    """Load all llm-doctor-*.jsonl files from a directory, sorted by name."""
    pattern = os.path.join(str(directory), "llm-doctor-*.jsonl")
    files = sorted(glob.glob(pattern))
    records: list[Record] = []
    for f in files:
        records.extend(load_file(f))
    # Sort by timestamp
    records.sort(key=lambda r: r.ts)
    return records


def group_sessions(records: list[Record]) -> list[Session]:
    """Group records into sessions by sessionKey."""
    sessions: dict[str, Session] = {}
    for r in records:
        key = r.session_key or "_unknown_"
        if key not in sessions:
            sessions[key] = Session(key=key)
        sessions[key].records.append(r)

    # Sort sessions by start time
    result = list(sessions.values())
    result.sort(key=lambda s: s.time_range[0])
    return result
