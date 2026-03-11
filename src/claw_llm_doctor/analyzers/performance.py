"""Layer 4: LLM Performance Metrics.

Computes standard LLM performance metrics from request/response logs:
- E2E latency (total response time per call)
- Output throughput (tokens per second)
- Token efficiency (cache hit rate)
- Latency percentiles (p50, p90, p95, p99)

Note: TTFT and ITL require streaming-level instrumentation and cannot
be computed from request/response pairs alone.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from claw_llm_doctor.loader import Session


@dataclass
class CallPerf:
    """Performance data for a single LLM call."""

    turn_index: int
    model: str | None = None
    provider: str | None = None
    e2e_ms: int | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0
    output_tps: float = 0.0  # output tokens per second
    success: bool = True


@dataclass
class ModelPerf:
    """Aggregated performance for a single model."""

    model: str
    call_count: int = 0
    success_count: int = 0
    latencies_ms: list[int] = field(default_factory=list)
    throughputs_tps: list[float] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read: int = 0
    total_cache_write: int = 0

    @property
    def avg_latency_ms(self) -> float:
        return statistics.mean(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def p50_latency_ms(self) -> float:
        return statistics.median(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def p90_latency_ms(self) -> float:
        return _percentile(self.latencies_ms, 0.90)

    @property
    def p95_latency_ms(self) -> float:
        return _percentile(self.latencies_ms, 0.95)

    @property
    def p99_latency_ms(self) -> float:
        return _percentile(self.latencies_ms, 0.99)

    @property
    def avg_throughput_tps(self) -> float:
        return statistics.mean(self.throughputs_tps) if self.throughputs_tps else 0.0

    @property
    def p50_throughput_tps(self) -> float:
        return statistics.median(self.throughputs_tps) if self.throughputs_tps else 0.0

    @property
    def cache_hit_rate(self) -> float:
        total_input = self.total_input_tokens + self.total_cache_read
        if total_input == 0:
            return 0.0
        return self.total_cache_read / total_input


@dataclass
class PerformanceReport:
    """Performance analysis report."""

    session_key: str
    calls: list[CallPerf] = field(default_factory=list)
    by_model: dict[str, ModelPerf] = field(default_factory=dict)

    # Aggregates
    total_calls: int = 0
    calls_with_duration: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read: int = 0

    @property
    def avg_latency_ms(self) -> float:
        lats = [c.e2e_ms for c in self.calls if c.e2e_ms is not None]
        return statistics.mean(lats) if lats else 0.0

    @property
    def avg_throughput_tps(self) -> float:
        tps = [c.output_tps for c in self.calls if c.output_tps > 0]
        return statistics.mean(tps) if tps else 0.0

    @property
    def overall_cache_hit_rate(self) -> float:
        total_input = self.total_input_tokens + self.total_cache_read
        if total_input == 0:
            return 0.0
        return self.total_cache_read / total_input


def _percentile(data: list[int | float], pct: float) -> float:
    """Compute a percentile from sorted data."""
    if not data:
        return 0.0
    s = sorted(data)
    idx = int(len(s) * pct)
    idx = min(idx, len(s) - 1)
    return float(s[idx])


def analyze_performance(session: Session) -> PerformanceReport:
    """Compute performance metrics from paired llm_input/llm_output records."""
    report = PerformanceReport(session_key=session.key)

    for i, out in enumerate(session.llm_outputs):
        usage = out.usage or {}
        dur = out.duration_ms
        model = out.model
        provider = out.provider

        input_tok = usage.get("input", 0) or 0
        output_tok = usage.get("output", 0) or 0
        cache_read = usage.get("cacheRead", 0) or 0
        cache_write = usage.get("cacheWrite", 0) or 0
        total_tok = usage.get("total", 0) or (input_tok + output_tok + cache_read + cache_write)

        # Output throughput: output_tokens / (duration_seconds)
        output_tps = 0.0
        if dur and dur > 0 and output_tok > 0:
            output_tps = output_tok / (dur / 1000.0)

        call = CallPerf(
            turn_index=i,
            model=model,
            provider=provider,
            e2e_ms=dur,
            input_tokens=input_tok,
            output_tokens=output_tok,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            total_tokens=total_tok,
            output_tps=round(output_tps, 1),
            success=out.success,
        )
        report.calls.append(call)

        # Aggregate
        report.total_calls += 1
        if dur is not None:
            report.calls_with_duration += 1
        report.total_input_tokens += input_tok
        report.total_output_tokens += output_tok
        report.total_cache_read += cache_read

        # Per-model
        if model:
            if model not in report.by_model:
                report.by_model[model] = ModelPerf(model=model)
            mp = report.by_model[model]
            mp.call_count += 1
            if out.success:
                mp.success_count += 1
            if dur is not None:
                mp.latencies_ms.append(dur)
            if output_tps > 0:
                mp.throughputs_tps.append(output_tps)
            mp.total_input_tokens += input_tok
            mp.total_output_tokens += output_tok
            mp.total_cache_read += cache_read
            mp.total_cache_write += cache_write

    return report
