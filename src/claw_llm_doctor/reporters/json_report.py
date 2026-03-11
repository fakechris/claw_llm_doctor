"""JSON reporter -- structured export for programmatic consumption."""

from __future__ import annotations

import json
import sys
from typing import Any

from claw_llm_doctor.analyzers.routing import RoutingReport
from claw_llm_doctor.analyzers.context import ContextReport
from claw_llm_doctor.analyzers.prompt_order import PromptOrderReport
from claw_llm_doctor.analyzers.prompt_compression import CompressionReport
from claw_llm_doctor.analyzers.thinking import ThinkingReport


def routing_to_dict(report: RoutingReport) -> dict[str, Any]:
    return {
        "layer": "routing",
        "summary": {
            "total_calls": report.total_calls,
            "primary_calls": report.primary_calls,
            "fallback_calls": report.fallback_calls,
            "unknown_routing": report.unknown_routing,
            "total_success": report.total_success,
            "total_failure": report.total_failure,
            "primary_success_rate": round(report.primary_success_rate, 4),
            "fallback_success_rate": round(report.fallback_success_rate, 4),
            "overall_success_rate": round(report.overall_success_rate, 4),
            "fallback_trigger_rate": round(report.fallback_trigger_rate, 4),
            "fan_out_ratio": round(report.fan_out_ratio, 2),
        },
        "by_model": {
            model: {
                "total": count,
                "success": report.success_by_model.get(model, 0),
                "failure": report.failure_by_model.get(model, 0),
            }
            for model, count in report.calls_by_model.most_common()
        },
        "by_provider": dict(report.calls_by_provider.most_common()),
        "errors": {
            code: {
                "count": bucket.count,
                "models": bucket.models,
                "examples": bucket.examples,
            }
            for code, bucket in report.errors.items()
        },
        "sessions": report.session_summaries,
        "timeline": report.timeline,
        "fallback_chains": report.fallback_chains,
        "success_over_time": report.success_over_time,
    }


def context_to_dict(report: ContextReport) -> dict[str, Any]:
    return {
        "layer": "context",
        "session_key": report.session_key,
        "peak_utilization": round(report.peak_utilization, 4),
        "avg_utilization": round(report.avg_utilization, 4),
        "compaction_events": report.compaction_events,
        "large_payloads": report.large_payloads,
        "turns": [t.as_dict() for t in report.turns],
        "growth_curve": report.growth_curve(),
    }


def prompt_order_to_dict(report: PromptOrderReport) -> dict[str, Any]:
    return {
        "layer": "prompt_order",
        "session_key": report.session_key,
        "is_stable": report.is_stable,
        "turns": [
            {
                "turn": t.turn_index,
                "order": t.order_signature,
                "content_signature": t.content_signature,
                "raw_length": t.raw_length,
                "sections": [
                    {"label": s.label, "chars": s.char_length, "hash": s.content_hash}
                    for s in t.sections
                ],
            }
            for t in report.turns
        ],
        "order_changes": report.order_changes,
        "content_changes": report.content_changes,
        "missing_sections": report.missing_sections,
    }


def compression_to_dict(report: CompressionReport) -> dict[str, Any]:
    return {
        "layer": "compression",
        "session_key": report.session_key,
        "baseline_length": report.baseline_length,
        "baseline_sections": report.baseline_sections,
        "max_loss_ratio": round(report.max_loss_ratio, 4),
        "turns_with_loss": report.turns_with_loss,
        "similarity_curve": [round(s, 4) for s in report.similarity_curve],
        "truncations": [
            {
                "turn": t.turn_index,
                "is_truncated": t.is_truncated,
                "markers": t.truncation_markers,
                "current_length": t.current_length,
                "loss_ratio": round(t.loss_ratio, 4),
            }
            for t in report.truncations
        ],
        "compactions": [
            {
                "turn": c.turn_index,
                "before_length": c.before_length,
                "after_length": c.after_length,
                "compression_ratio": round(c.compression_ratio, 4),
                "preserved_entities": c.preserved_entities,
                "lost_sections": c.lost_sections,
            }
            for c in report.compactions
        ],
    }


def thinking_to_dict(report: ThinkingReport) -> dict[str, Any]:
    return {
        "layer": "thinking",
        "session_key": report.session_key,
        "total_thinking_tokens": report.total_thinking_tokens,
        "total_content_tokens": report.total_content_tokens,
        "overall_thinking_ratio": round(report.overall_thinking_ratio, 4),
        "turns_with_thinking": report.turns_with_thinking,
        "turns_with_leakage": report.turns_with_leakage,
        "leakage_rate": round(report.leakage_rate, 4),
        "leakage_pattern_counts": report.leakage_pattern_counts,
        "turns": [
            {
                "turn": t.turn_index,
                "thinking_tokens": t.thinking_tokens,
                "content_tokens": t.content_tokens,
                "thinking_ratio": round(t.thinking_ratio, 4),
                "has_leakage": t.has_leakage,
                "leakage_severity": t.leakage_severity,
                "leakage_instances": [
                    {
                        "pattern": li.pattern_name,
                        "matched": li.matched_text,
                        "context": li.context,
                    }
                    for li in t.leakage_instances
                ],
                "thinking_categories": list({b.category for b in t.thinking_blocks}),
            }
            for t in report.turns
        ],
    }


def build_full_json(
    routing: RoutingReport | None = None,
    contexts: list[ContextReport] | None = None,
    prompt_orders: list[PromptOrderReport] | None = None,
    compressions: list[CompressionReport] | None = None,
    thinkings: list[ThinkingReport] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"version": "0.1.0"}
    if routing:
        result["routing"] = routing_to_dict(routing)
    if contexts:
        result["context"] = [context_to_dict(c) for c in contexts]
    if prompt_orders:
        result["prompt_order"] = [prompt_order_to_dict(p) for p in prompt_orders]
    if compressions:
        result["compression"] = [compression_to_dict(c) for c in compressions]
    if thinkings:
        result["thinking"] = [thinking_to_dict(t) for t in thinkings]
    return result


def write_json(
    data: dict[str, Any],
    output: str | None = None,
) -> None:
    """Write JSON report to file or stdout."""
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if output:
        with open(output, "w") as f:
            f.write(text)
            f.write("\n")
    else:
        sys.stdout.write(text)
        sys.stdout.write("\n")
