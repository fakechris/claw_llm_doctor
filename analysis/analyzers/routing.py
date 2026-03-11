"""Layer 1: LM Routing Analysis.

Analyzes Primary vs Fallback model call patterns, success rates, and error
classification across sessions.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from loader import Record, Session


# ── Result types ──────────────────────────────────────────────────────────


@dataclass
class LlmCall:
    """A paired llm.input -> llm.output representing one LLM round-trip."""

    input_record: Record
    output_record: Record | None = None

    @property
    def model(self) -> str | None:
        return self.input_record.model

    @property
    def provider(self) -> str | None:
        return self.input_record.provider

    @property
    def is_primary(self) -> bool | None:
        return self.input_record.is_primary

    @property
    def fallback_reason(self) -> str | None:
        return self.input_record.fallback_reason

    @property
    def success(self) -> bool:
        if self.output_record is None:
            return False
        return self.output_record.success

    @property
    def error(self) -> str | None:
        if self.output_record is None:
            return "no_response"
        return self.output_record.error

    @property
    def error_code(self) -> str | None:
        if self.output_record is None:
            return "no_response"
        return self.output_record.error_code

    @property
    def duration_ms(self) -> int | None:
        if self.output_record:
            return self.output_record.duration_ms
        return None


@dataclass
class ErrorBucket:
    """Aggregated error info for a specific error category."""

    code: str
    count: int = 0
    examples: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)

    def add(self, error_msg: str | None, model: str | None) -> None:
        self.count += 1
        if error_msg and len(self.examples) < 3:
            self.examples.append(error_msg[:200])
        if model and model not in self.models:
            self.models.append(model)


@dataclass
class RoutingReport:
    """Complete routing analysis report."""

    total_calls: int = 0
    primary_calls: int = 0
    fallback_calls: int = 0
    unknown_routing: int = 0

    total_success: int = 0
    total_failure: int = 0
    primary_success: int = 0
    primary_failure: int = 0
    fallback_success: int = 0
    fallback_failure: int = 0

    errors: dict[str, ErrorBucket] = field(default_factory=dict)
    calls_by_model: Counter = field(default_factory=Counter)
    success_by_model: Counter = field(default_factory=Counter)
    failure_by_model: Counter = field(default_factory=Counter)
    calls_by_provider: Counter = field(default_factory=Counter)

    # Per-session summaries
    session_summaries: list[dict[str, Any]] = field(default_factory=list)

    # Routing timeline & fallback chains
    timeline: list[dict] = field(default_factory=list)
    fallback_chains: list[dict] = field(default_factory=list)

    # Success rate over time (degradation detection)
    success_over_time: list[dict] = field(default_factory=list)

    # Fan-out ratio (user requests -> LLM calls)
    fan_out_ratio: float = 0.0

    @property
    def primary_success_rate(self) -> float:
        if self.primary_calls == 0:
            return 0.0
        return self.primary_success / self.primary_calls

    @property
    def fallback_success_rate(self) -> float:
        if self.fallback_calls == 0:
            return 0.0
        return self.fallback_success / self.fallback_calls

    @property
    def overall_success_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.total_success / self.total_calls

    @property
    def fallback_trigger_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.fallback_calls / self.total_calls


# ── Analysis ──────────────────────────────────────────────────────────────


def pair_llm_calls(session: Session) -> list[LlmCall]:
    """Pair llm.input records with their corresponding llm.output records.

    Pairing heuristic: match by runId, or by sequential ordering within the
    same session.
    """
    inputs = list(session.llm_inputs)
    outputs = list(session.llm_outputs)

    # Index outputs by runId for fast lookup
    output_by_run: dict[str, Record] = {}
    unmatched_outputs: list[Record] = []
    for o in outputs:
        if o.run_id:
            output_by_run[o.run_id] = o
        else:
            unmatched_outputs.append(o)

    calls: list[LlmCall] = []
    remaining_outputs = list(unmatched_outputs)

    for inp in inputs:
        # Try matching by runId first
        if inp.run_id and inp.run_id in output_by_run:
            calls.append(LlmCall(input_record=inp, output_record=output_by_run.pop(inp.run_id)))
            continue

        # Fall back to sequential matching by timestamp
        matched = None
        for i, out in enumerate(remaining_outputs):
            if out.ts >= inp.ts:
                matched = remaining_outputs.pop(i)
                break
        calls.append(LlmCall(input_record=inp, output_record=matched))

    return calls


def classify_error(call: LlmCall) -> str:
    """Classify the error category for a failed LLM call."""
    code = call.error_code
    if code:
        return code

    error = call.error or ""
    lower = error.lower()

    if any(kw in lower for kw in ("auth", "api key", "unauthorized", "403", "401")):
        return "auth_failed"
    if any(kw in lower for kw in ("rate limit", "429", "throttle", "quota")):
        return "rate_limited"
    if any(kw in lower for kw in ("timeout", "timed out", "deadline")):
        return "timeout"
    if any(kw in lower for kw in ("context_length", "too many tokens", "max tokens")):
        return "context_length_exceeded"
    if any(kw in lower for kw in ("500", "502", "503", "504", "server error", "internal error")):
        return "server_error"
    if error == "no_response":
        return "no_response"

    return "unknown"


def infer_primary(call: LlmCall, primary_model: str | None) -> bool | None:
    """Infer whether a call used the primary model.

    The OpenClaw SDK doesn't expose isPrimary/fallbackReason. Instead, we
    compare the model used against the configured primary model.  When
    *primary_model* is None we cannot infer and return None.
    """
    if primary_model is None:
        return None
    fq = call.input_record.raw.get("provider", "") + "/" + (call.model or "")
    if fq == primary_model or call.model == primary_model:
        return True
    return False


def build_routing_timeline(
    sessions: list[Session],
    primary_model: str | None = None,
) -> list[dict]:
    """Build a time-ordered list of routing events across all sessions.

    Each entry contains:
        timestamp, session_key, model, provider, is_primary (inferred),
        success, duration_ms, error
    """
    timeline: list[dict] = []

    for session in sessions:
        calls = pair_llm_calls(session)
        for call in calls:
            is_primary = call.is_primary
            if is_primary is None:
                is_primary = infer_primary(call, primary_model)

            timeline.append(
                {
                    "timestamp": call.input_record.ts,
                    "session_key": session.key,
                    "run_id": call.input_record.run_id,
                    "model": call.model or "unknown",
                    "provider": call.provider or "unknown",
                    "is_primary": is_primary,
                    "success": call.success,
                    "duration_ms": call.duration_ms,
                    "error": call.error if not call.success else None,
                }
            )

    timeline.sort(key=lambda e: e["timestamp"])
    return timeline


def detect_fallback_chains(
    timeline: list[dict],
    max_gap_ms: int = 60_000,
) -> list[dict]:
    """Detect cascading fallback chains from the routing timeline.

    A fallback chain is a group of consecutive LLM calls within the same
    session where the first call failed and subsequent calls used different
    models within a short time window (``max_gap_ms``).  We group by session
    only (not run_id) because fallback retries often use a new run_id.

    The temporal proximity check (default 60 s between consecutive calls)
    prevents unrelated later calls from being mis-classified as fallbacks.

    Returns a list of chain dicts, each with:
        session_key, start_timestamp, calls (list of timeline entries),
        models_tried (ordered list of distinct models), final_success
    """
    chains: list[dict] = []

    # Group timeline entries by session_key preserving order
    groups: dict[str, list[dict]] = defaultdict(list)
    for entry in timeline:
        groups[entry["session_key"]].append(entry)

    for session_key, entries in groups.items():
        # Walk through entries looking for failure -> retry sequences
        i = 0
        while i < len(entries):
            if not entries[i]["success"]:
                # Start of a potential chain
                chain_calls = [entries[i]]
                j = i + 1
                while j < len(entries):
                    prev_ts = chain_calls[-1]["timestamp"]
                    curr_ts = entries[j]["timestamp"]
                    # Only chain if the next call is temporally close and
                    # uses a different model (actual fallback behaviour).
                    if (
                        entries[j]["model"] != entries[i]["model"]
                        and (curr_ts - prev_ts) <= max_gap_ms
                    ):
                        chain_calls.append(entries[j])
                        if entries[j]["success"]:
                            break  # chain resolved
                        j += 1
                    else:
                        break
                if len(chain_calls) > 1:
                    chains.append(
                        {
                            "session_key": session_key,
                            "start_timestamp": chain_calls[0]["timestamp"],
                            "calls": chain_calls,
                            "models_tried": list(
                                dict.fromkeys(c["model"] for c in chain_calls)
                            ),
                            "final_success": chain_calls[-1]["success"],
                        }
                    )
                    i = j + 1
                else:
                    i += 1
            else:
                i += 1

    chains.sort(key=lambda c: c["start_timestamp"])
    return chains


def build_success_over_time(
    timeline: list[dict],
    bucket_minutes: int = 10,
) -> list[dict]:
    """Bucket LLM calls into time windows and compute per-bucket success rates.

    Useful for detecting degradation patterns (e.g. success rate dropping over
    time).

    Returns a list of dicts with keys:
        bucket_start, bucket_end, total, success, rate
    """
    if not timeline:
        return []

    bucket_ms = bucket_minutes * 60 * 1000
    first_ts = timeline[0]["timestamp"]

    buckets: dict[int, dict] = {}
    for entry in timeline:
        offset = entry["timestamp"] - first_ts
        bucket_idx = offset // bucket_ms
        bucket_start = first_ts + bucket_idx * bucket_ms
        bucket_end = bucket_start + bucket_ms

        if bucket_start not in buckets:
            buckets[bucket_start] = {
                "bucket_start": bucket_start,
                "bucket_end": bucket_end,
                "total": 0,
                "success": 0,
            }
        buckets[bucket_start]["total"] += 1
        if entry["success"]:
            buckets[bucket_start]["success"] += 1

    result: list[dict] = []
    for _start, b in sorted(buckets.items()):
        b["rate"] = b["success"] / b["total"] if b["total"] > 0 else 0.0
        result.append(b)

    return result


def analyze_routing(
    sessions: list[Session],
    primary_model: str | None = None,
) -> RoutingReport:
    """Run full routing analysis across all sessions.

    *primary_model* should be the fully-qualified model id from the OpenClaw
    config (e.g. ``"ark/doubao-seed-2.0-code"``).  When provided, routing
    classification will infer primary vs fallback.
    """
    report = RoutingReport()

    for session in sessions:
        calls = pair_llm_calls(session)
        session_total = len(calls)
        session_success = 0
        session_fallback = 0

        for call in calls:
            report.total_calls += 1

            model = call.model or "unknown"
            provider = call.provider or "unknown"
            report.calls_by_model[model] += 1
            report.calls_by_provider[provider] += 1

            # Routing classification — try explicit field first, then infer
            is_primary = call.is_primary
            if is_primary is None:
                is_primary = infer_primary(call, primary_model)

            if is_primary is True:
                report.primary_calls += 1
            elif is_primary is False:
                report.fallback_calls += 1
                session_fallback += 1
            else:
                report.unknown_routing += 1

            # Success/failure
            if call.success:
                report.total_success += 1
                session_success += 1
                if is_primary is True:
                    report.primary_success += 1
                elif is_primary is False:
                    report.fallback_success += 1
                report.success_by_model[model] += 1
            else:
                report.total_failure += 1
                if is_primary is True:
                    report.primary_failure += 1
                elif is_primary is False:
                    report.fallback_failure += 1
                report.failure_by_model[model] += 1

                # Error classification
                err_code = classify_error(call)
                if err_code not in report.errors:
                    report.errors[err_code] = ErrorBucket(code=err_code)
                report.errors[err_code].add(call.error, call.model)

        # Per-session summary
        report.session_summaries.append(
            {
                "session_key": session.key,
                "total_calls": session_total,
                "success": session_success,
                "failure": session_total - session_success,
                "fallback_triggered": session_fallback,
                "time_range": session.time_range,
            }
        )

    # Build timeline and detect fallback chains
    report.timeline = build_routing_timeline(sessions, primary_model)
    report.fallback_chains = detect_fallback_chains(report.timeline)

    # Success rate over time (degradation detection)
    report.success_over_time = build_success_over_time(report.timeline)

    # Fan-out ratio: total LLM calls per agent start
    agent_start_count = sum(
        1 for s in sessions for r in s.records if r.type == "agent.start"
    )
    if agent_start_count > 0:
        report.fan_out_ratio = report.total_calls / agent_start_count

    return report
