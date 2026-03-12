"""Terminal reporter -- rich-formatted output for all analysis layers."""

from __future__ import annotations

from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from claw_llm_doctor.analyzers.routing import RoutingReport
from claw_llm_doctor.analyzers.context import ContextReport
from claw_llm_doctor.analyzers.prompt_order import PromptOrderReport
from claw_llm_doctor.analyzers.prompt_compression import CompressionReport
from claw_llm_doctor.analyzers.thinking import ThinkingReport
from claw_llm_doctor.analyzers.performance import PerformanceReport
from claw_llm_doctor.loader import Session
from claw_llm_doctor.utils.tokens import format_tokens


console = Console()


# -- Helpers ---------------------------------------------------------------


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def health_color(health: str) -> str:
    return {"green": "green", "yellow": "yellow", "red": "red"}.get(health, "white")


def severity_color(severity: str) -> str:
    return {"none": "green", "low": "yellow", "medium": "bright_red", "high": "red"}.get(severity, "white")


# -- Layer 1: Routing ------------------------------------------------------


def print_routing(report: RoutingReport) -> None:
    console.print()
    console.print(Panel("[bold]Layer 1: LM Routing Analysis[/bold]", style="blue"))

    # Summary table
    t = Table(title="Routing Summary", show_header=True, header_style="bold")
    t.add_column("Metric", style="cyan")
    t.add_column("Value", justify="right")

    t.add_row("Primary model", report.primary_model or "(not configured)")
    t.add_row("Total LLM calls", str(report.total_calls))
    t.add_row("Primary calls", str(report.primary_calls))
    t.add_row("Fallback calls", str(report.fallback_calls))
    t.add_row("Unknown routing", str(report.unknown_routing))
    t.add_row("Primary success rate", pct(report.primary_success_rate))
    t.add_row("Fallback success rate", pct(report.fallback_success_rate))
    t.add_row("Overall success rate", pct(report.overall_success_rate))
    t.add_row("Fallback trigger rate", pct(report.fallback_trigger_rate))
    t.add_row("Fan-out ratio", f"{report.fan_out_ratio:.1f}x")
    console.print(t)

    # Model breakdown
    if report.calls_by_model:
        mt = Table(title="Calls by Model", show_header=True, header_style="bold")
        mt.add_column("Model", style="cyan")
        mt.add_column("Total", justify="right")
        mt.add_column("Success", justify="right", style="green")
        mt.add_column("Failure", justify="right", style="red")

        for model, total in report.calls_by_model.most_common():
            succ = report.success_by_model.get(model, 0)
            fail = report.failure_by_model.get(model, 0)
            mt.add_row(model, str(total), str(succ), str(fail))
        console.print(mt)

    # Error breakdown
    if report.errors:
        et = Table(title="Error Classification", show_header=True, header_style="bold")
        et.add_column("Error Code", style="red")
        et.add_column("Count", justify="right")
        et.add_column("Models", style="dim")
        et.add_column("Example", style="dim", max_width=60)

        for code, bucket in sorted(report.errors.items(), key=lambda x: -x[1].count):
            example = bucket.examples[0] if bucket.examples else ""
            et.add_row(code, str(bucket.count), ", ".join(bucket.models), example)
        console.print(et)

    # Per-session
    if report.session_summaries:
        st = Table(title="Per-Session Summary", show_header=True, header_style="bold")
        st.add_column("Session", style="cyan", max_width=20)
        st.add_column("Calls", justify="right")
        st.add_column("OK", justify="right", style="green")
        st.add_column("Fail", justify="right", style="red")
        st.add_column("Fallback", justify="right", style="yellow")

        for s in report.session_summaries:
            st.add_row(
                s["session_key"][:20],
                str(s["total_calls"]),
                str(s["success"]),
                str(s["failure"]),
                str(s["fallback_triggered"]),
            )
        console.print(st)

    # Routing timeline (capped to 30 rows: first 15 + last 15)
    if report.timeline:
        total_entries = len(report.timeline)
        cap = 30
        if total_entries > cap:
            display_entries = report.timeline[:15] + report.timeline[-15:]
            omitted = total_entries - cap
            title = f"Routing Timeline ({cap} of {total_entries})"
        else:
            display_entries = report.timeline
            omitted = 0
            title = f"Routing Timeline ({total_entries})"

        tt = Table(title=title, show_header=True, header_style="bold")
        tt.add_column("Timestamp", style="dim")
        tt.add_column("Session", style="cyan", max_width=16)
        tt.add_column("Model", style="cyan")
        tt.add_column("Provider")
        tt.add_column("Role", justify="center")
        tt.add_column("OK", justify="center")
        tt.add_column("Duration", justify="right")

        for idx, entry in enumerate(display_entries):
            if omitted and idx == 15:
                tt.add_row(f"... {omitted} omitted ...", "", "", "", "", "", "")
            ts_str = datetime.fromtimestamp(entry["timestamp"] / 1000).strftime("%m-%d %H:%M:%S")
            role_label = "Primary" if entry["is_primary"] is True else (
                "Fallback" if entry["is_primary"] is False else "?"
            )
            role_style = "green" if entry["is_primary"] is True else (
                "yellow" if entry["is_primary"] is False else "dim"
            )
            ok_text = Text("OK", style="green") if entry["success"] else Text("FAIL", style="red")
            dur = str(entry["duration_ms"]) + "ms" if entry["duration_ms"] is not None else "-"

            tt.add_row(
                ts_str,
                (entry["session_key"] or "")[:16],
                entry["model"],
                entry["provider"],
                Text(role_label, style=role_style),
                ok_text,
                dur,
            )
        console.print(tt)

    # Success rate over time
    if report.success_over_time:
        sot = Table(title="Success Rate Over Time", show_header=True, header_style="bold")
        sot.add_column("Time Window", style="dim")
        sot.add_column("Total", justify="right")
        sot.add_column("Success", justify="right", style="green")
        sot.add_column("Rate", justify="right")

        for bucket in report.success_over_time:
            start_str = datetime.fromtimestamp(bucket["bucket_start"] / 1000).strftime("%m-%d %H:%M")
            end_str = datetime.fromtimestamp(bucket["bucket_end"] / 1000).strftime("%m-%d %H:%M")
            rate_style = "green" if bucket["rate"] >= 0.9 else ("yellow" if bucket["rate"] >= 0.7 else "red")
            sot.add_row(
                f"{start_str}-{end_str}",
                str(bucket["total"]),
                str(bucket["success"]),
                Text(pct(bucket["rate"]), style=rate_style),
            )
        console.print(sot)

    # Fallback chains
    if report.fallback_chains:
        console.print(f"\n  [yellow]Detected {len(report.fallback_chains)} fallback chain(s):[/yellow]")
        for i, chain in enumerate(report.fallback_chains, 1):
            resolved = "[green]resolved[/green]" if chain["final_success"] else "[red]unresolved[/red]"
            models = " -> ".join(chain["models_tried"])
            console.print(f"\n  Chain {i}: {models}  ({resolved})")
            ct = Table(show_header=True, header_style="bold", padding=(0, 1))
            ct.add_column("Step", justify="right", style="dim")
            ct.add_column("Model", style="cyan")
            ct.add_column("OK", justify="center")
            ct.add_column("Error", style="red", max_width=50)
            ct.add_column("Duration", justify="right")
            for step, call in enumerate(chain["calls"], 1):
                ok_text = Text("OK", style="green") if call["success"] else Text("FAIL", style="red")
                dur = str(call["duration_ms"]) + "ms" if call["duration_ms"] is not None else "-"
                ct.add_row(
                    str(step),
                    call["model"],
                    ok_text,
                    (call.get("error") or "")[:50],
                    dur,
                )
            console.print(ct)


# -- Layer 3a: Context -----------------------------------------------------


def print_context(report: ContextReport) -> None:
    console.print()
    console.print(Panel("[bold]Layer 3a: Context Composition Analysis[/bold]", style="blue"))

    has_context_limits = any(t.context_limit for t in report.turns)

    console.print(f"  Session: [cyan]{report.session_key}[/cyan]")
    console.print(f"  Turns analyzed: {len(report.turns)}")
    if has_context_limits:
        console.print(f"  Peak utilization: {pct(report.peak_utilization)}")
        console.print(f"  Avg utilization: {pct(report.avg_utilization)}")
    else:
        console.print(f"  Peak utilization: N/A (no context limit available)")
        console.print(f"  Avg utilization: N/A (no context limit available)")
    console.print(f"  Compaction events: {len(report.compaction_events)}")
    console.print()

    if report.turns:
        t = Table(title="Context Breakdown per Turn", show_header=True, header_style="bold")
        t.add_column("Turn", justify="right", style="dim")
        t.add_column("System", justify="right")
        t.add_column("Tools", justify="right")
        t.add_column("History", justify="right")
        t.add_column("ToolRes", justify="right")
        t.add_column("Think", justify="right")
        t.add_column("Total", justify="right", style="bold")
        if has_context_limits:
            t.add_column("Util", justify="right")
            t.add_column("HP", justify="center")

        for comp in report.turns:
            row = [
                str(comp.turn_index),
                format_tokens(comp.system_tokens),
                format_tokens(comp.tool_def_tokens),
                format_tokens(comp.history_tokens),
                format_tokens(comp.tool_result_tokens),
                format_tokens(comp.thinking_tokens),
                format_tokens(comp.total_tokens),
            ]
            if has_context_limits:
                color = health_color(comp.health)
                row.append(pct(comp.utilization))
                row.append(Text("\u25cf", style=color))
            t.add_row(*row)
        console.print(t)

    if report.large_payloads:
        console.print(f"\n  [yellow]Warning:[/yellow] {len(report.large_payloads)} turns with large tool results (>{format_tokens(5000)} tokens)")
        for lp in report.large_payloads[:5]:
            console.print(f"    Turn {lp['turn']}: tool_result={format_tokens(lp['tool_result_tokens'])}")

    # Context growth curve (ASCII bar chart, sampled to max 40 points)
    curve = report.growth_curve()
    if curve:
        max_points = 40
        if len(curve) > max_points:
            # Always keep: first, last, and compaction points
            keep = {0, len(curve) - 1}
            for ci in report.compaction_events:
                if 0 <= ci < len(curve):
                    keep.add(ci)
            # Evenly sample remaining slots
            remaining = max_points - len(keep)
            if remaining > 0:
                step = max(1, len(curve) // remaining)
                for idx in range(0, len(curve), step):
                    keep.add(idx)
            curve = [curve[i] for i in sorted(keep)][:max_points]

        max_tokens = max((pt["total_tokens"] for pt in curve), default=1) or 1
        bar_width = 40
        console.print()
        console.print("  [bold]Context Growth Curve[/bold]")
        console.print()
        for pt in curve:
            bar_len = int((pt["total_tokens"] / max_tokens) * bar_width)
            bar = "\u2588" * bar_len + "\u2591" * (bar_width - bar_len)
            delta = pt["delta"]
            delta_str = f"+{delta}" if delta >= 0 else str(delta)
            color = "green" if delta >= 0 else "red"
            console.print(
                f"    Turn {pt['turn_index']:3d}: {bar} "
                f"{format_tokens(pt['total_tokens']):>7s}  "
                f"[{color}]{delta_str:>7s}[/{color}]"
            )
        console.print()


# -- Layer 3b: Prompt Order ------------------------------------------------


def print_prompt_order(report: PromptOrderReport) -> None:
    console.print()
    console.print(Panel("[bold]Layer 3b: System Prompt Ordering Analysis[/bold]", style="blue"))

    console.print(f"  Session: [cyan]{report.session_key}[/cyan]")
    console.print(f"  Turns analyzed: {len(report.turns)}")
    stable_text = "[green]STABLE[/green]" if report.is_stable else "[red]UNSTABLE[/red]"
    console.print(f"  Ordering: {stable_text}")

    if report.turns:
        # Show the ordering of the first turn as baseline
        first = report.turns[0]
        console.print(f"\n  Baseline order (turn {first.turn_index}):")
        console.print(f"    {first.order_signature}")

    if report.order_changes:
        console.print(f"\n  [yellow]Order changes detected ({len(report.order_changes)}):[/yellow]")
        for ch in report.order_changes:
            console.print(f"    Turn {ch['turn']}: {ch['prev_order']}  =>  {ch['curr_order']}")

    if report.content_changes:
        console.print(f"\n  Content changes: {len(report.content_changes)} turns")
        for ch in report.content_changes[:5]:
            console.print(f"    Turn {ch['turn']}: sections changed: {', '.join(ch['changed_sections'])}")

    if report.missing_sections:
        console.print(f"\n  [red]Missing sections ({len(report.missing_sections)}):[/red]")
        for ms in report.missing_sections:
            console.print(f"    Turn {ms['turn']}: lost [{', '.join(ms['missing'])}]")


# -- Layer 3c: Compression ------------------------------------------------


def print_compression(report: CompressionReport) -> None:
    console.print()
    console.print(Panel("[bold]Layer 3c: System Prompt Compression Analysis[/bold]", style="blue"))

    console.print(f"  Session: [cyan]{report.session_key}[/cyan]")
    console.print(f"  Baseline length: {report.baseline_length:,} chars")
    console.print(f"  Baseline sections: {', '.join(report.baseline_sections)}")
    console.print(f"  Max loss ratio: {pct(report.max_loss_ratio)}")
    console.print(f"  Turns with loss: {report.turns_with_loss}")

    if report.compactions:
        console.print(f"\n  [yellow]Compaction events ({len(report.compactions)}):[/yellow]")
        for c in report.compactions:
            console.print(f"    Turn {c.turn_index}: {c.before_length:,} -> {c.after_length:,} chars ({pct(c.compression_ratio)} compressed)")
            if c.lost_sections:
                console.print(f"      Lost sections: {', '.join(c.lost_sections)}")
            if c.preserved_entities:
                console.print(f"      Preserved entities: {len(c.preserved_entities)}")

    # Similarity curve (only show notable changes: sim < 0.95 or delta > 1%)
    if report.similarity_curve and len(report.similarity_curve) > 1:
        console.print("\n  Similarity vs baseline (notable changes):")
        prev_sim = 1.0
        shown = 0
        for i, sim in enumerate(report.similarity_curve):
            delta = abs(sim - prev_sim)
            if sim < 0.95 or delta > 0.01 or i == 0:
                bar_len = int(sim * 30)
                bar = "\u2588" * bar_len + "\u2591" * (30 - bar_len)
                color = "green" if sim > 0.9 else "yellow" if sim > 0.7 else "red"
                console.print(f"    Turn {i:3d}: [{color}]{bar}[/{color}] {pct(sim)}")
                shown += 1
            prev_sim = sim
        if shown == 0:
            console.print("    All turns >= 95% similar to baseline.")


# -- Layer 3d: Thinking ----------------------------------------------------


def print_thinking(report: ThinkingReport) -> None:
    console.print()
    console.print(Panel("[bold]Layer 3d: Thinking Process Analysis[/bold]", style="blue"))

    console.print(f"  Session: [cyan]{report.session_key}[/cyan]")
    console.print(f"  Turns with thinking: {report.turns_with_thinking} / {len(report.turns)}")
    console.print(f"  Overall thinking ratio: {pct(report.overall_thinking_ratio)}")
    console.print(f"  Total thinking tokens: {format_tokens(report.total_thinking_tokens)}")
    console.print(f"  Total content tokens: {format_tokens(report.total_content_tokens)}")

    # Leakage summary
    if report.turns_with_leakage > 0:
        console.print(f"\n  [red]Thinking leakage detected in {report.turns_with_leakage} turns ({pct(report.leakage_rate)} of thinking turns)[/red]")

        # By category
        if report.leakage_category_counts:
            ct = Table(title="Leakage by Category", show_header=True, header_style="bold")
            ct.add_column("Category", style="red")
            ct.add_column("Count", justify="right")
            category_labels = {
                "tag_leak": "Tag Leak (think_never_used / <thinking>)",
                "en_monologue": "English Inner Monologue",
                "cn_monologue": "Chinese Inner Monologue",
                "interleave": "Token Interleaving",
            }
            for cat, count in sorted(report.leakage_category_counts.items(), key=lambda x: -x[1]):
                ct.add_row(category_labels.get(cat, cat), str(count))
            console.print(ct)

        # By pattern
        lt = Table(title="Leakage Pattern Details", show_header=True, header_style="bold")
        lt.add_column("Pattern", style="red")
        lt.add_column("Category")
        lt.add_column("Count", justify="right")
        # Merge pattern + category
        pattern_cats: dict[str, str] = {}
        for turn in report.turns:
            for li in turn.leakage_instances:
                pattern_cats[li.pattern_name] = li.category
        for name, count in sorted(report.leakage_pattern_counts.items(), key=lambda x: -x[1]):
            lt.add_row(name, pattern_cats.get(name, "?"), str(count))
        console.print(lt)

        # Show examples
        for turn in report.turns:
            if turn.has_leakage:
                model_str = f"  model={turn.model}" if turn.model else ""
                ts_str = datetime.fromtimestamp(turn.ts / 1000).strftime("%m-%d %H:%M:%S") if turn.ts else "?"
                console.print(f"\n  Turn {turn.turn_index} [{turn.leakage_severity}]{model_str}  [dim]{ts_str}[/dim]:")
                for li in turn.leakage_instances[:3]:
                    console.print(f"    [{li.category}/{li.pattern_name}] \"{li.matched_text}\"")
                    console.print(f"    [dim]...{li.context}...[/dim]")
    else:
        console.print(f"\n  [green]No thinking leakage detected.[/green]")

    # Per-turn thinking summary
    thinking_turns = [t for t in report.turns if t.has_thinking]
    if thinking_turns:
        tt = Table(title="Thinking per Turn", show_header=True, header_style="bold")
        tt.add_column("Turn", justify="right", style="dim")
        tt.add_column("Time", style="dim")
        tt.add_column("Model", style="cyan", max_width=25)
        tt.add_column("Think Tokens", justify="right")
        tt.add_column("Content Tokens", justify="right")
        tt.add_column("Ratio", justify="right")
        tt.add_column("Categories", max_width=30)
        tt.add_column("Leak", justify="center")

        for t in thinking_turns:
            cats = ", ".join(sorted({b.category for b in t.thinking_blocks}))
            leak_indicator = Text("\u25cf", style=severity_color(t.leakage_severity))
            ts_str = datetime.fromtimestamp(t.ts / 1000).strftime("%m-%d %H:%M:%S") if t.ts else "-"
            tt.add_row(
                str(t.turn_index),
                ts_str,
                t.model or "?",
                format_tokens(t.thinking_tokens),
                format_tokens(t.content_tokens),
                pct(t.thinking_ratio),
                cats,
                leak_indicator,
            )
        console.print(tt)

    # Leakage by model summary
    leak_turns = [t for t in report.turns if t.has_leakage]
    if leak_turns:
        model_leaks: dict[str, int] = {}
        for t in leak_turns:
            key = t.model or "unknown"
            model_leaks[key] = model_leaks.get(key, 0) + len(t.leakage_instances)
        mlt = Table(title="Leakage by Model", show_header=True, header_style="bold")
        mlt.add_column("Model", style="cyan")
        mlt.add_column("Leak Instances", justify="right")
        mlt.add_column("Turns Affected", justify="right")
        model_turn_counts: dict[str, int] = {}
        for t in leak_turns:
            key = t.model or "unknown"
            model_turn_counts[key] = model_turn_counts.get(key, 0) + 1
        for model, count in sorted(model_leaks.items(), key=lambda x: -x[1]):
            mlt.add_row(model, str(count), str(model_turn_counts[model]))
        console.print(mlt)


# -- Layer 4: Performance --------------------------------------------------


def print_performance(report: PerformanceReport) -> None:
    console.print()
    console.print(Panel("[bold]Layer 4: LLM Performance Metrics[/bold]", style="blue"))

    console.print(f"  Session: [cyan]{report.session_key}[/cyan]")
    console.print(f"  Total calls: {report.total_calls} ({report.calls_with_duration} with timing)")
    console.print(f"  Total tokens: {format_tokens(report.total_input_tokens)} in / {format_tokens(report.total_output_tokens)} out")
    console.print(f"  Cache hit rate: {pct(report.overall_cache_hit_rate)}")
    if report.avg_latency_ms > 0:
        console.print(f"  Avg E2E latency: {report.avg_latency_ms:.0f}ms")
    if report.avg_throughput_tps > 0:
        console.print(f"  Avg output throughput: {report.avg_throughput_tps:.1f} tok/s")

    # Per-model table
    if report.by_model:
        mt = Table(title="Performance by Model", show_header=True, header_style="bold")
        mt.add_column("Model", style="cyan")
        mt.add_column("Calls", justify="right")
        mt.add_column("Avg Lat.", justify="right")
        mt.add_column("p50 Lat.", justify="right")
        mt.add_column("p95 Lat.", justify="right")
        mt.add_column("p99 Lat.", justify="right")
        mt.add_column("Avg tok/s", justify="right")
        mt.add_column("p50 tok/s", justify="right")
        mt.add_column("Cache Hit", justify="right")

        for model, mp in sorted(report.by_model.items()):
            throughput_avg = f"{mp.avg_throughput_tps:.1f}" if mp.success_count > 0 else "N/A"
            throughput_p50 = f"{mp.p50_throughput_tps:.1f}" if mp.success_count > 0 else "N/A"
            mt.add_row(
                model,
                str(mp.call_count),
                f"{mp.avg_latency_ms:.0f}ms",
                f"{mp.p50_latency_ms:.0f}ms",
                f"{mp.p95_latency_ms:.0f}ms",
                f"{mp.p99_latency_ms:.0f}ms",
                throughput_avg,
                throughput_p50,
                pct(mp.cache_hit_rate),
            )
        console.print(mt)

    # Slowest successful calls (top 10)
    successful_with_dur = [c for c in report.calls if c.e2e_ms is not None and c.success]
    if successful_with_dur:
        slowest = sorted(successful_with_dur, key=lambda c: c.e2e_ms or 0, reverse=True)[:10]
        st = Table(title="Slowest Successful Calls (Top 10)", show_header=True, header_style="bold")
        st.add_column("Turn", justify="right", style="dim")
        st.add_column("Time", style="dim")
        st.add_column("Model", style="cyan")
        st.add_column("E2E", justify="right")
        st.add_column("In Tok", justify="right")
        st.add_column("Out Tok", justify="right")
        st.add_column("tok/s", justify="right")

        for c in slowest:
            ts_str = datetime.fromtimestamp(c.ts / 1000).strftime("%m-%d %H:%M:%S") if c.ts else "-"
            st.add_row(
                str(c.turn_index),
                ts_str,
                c.model or "?",
                f"{c.e2e_ms}ms",
                str(c.input_tokens),
                str(c.output_tokens),
                f"{c.output_tps:.1f}",
            )
        console.print(st)

    # Failed calls (up to 10)
    failed_calls = [c for c in report.calls if not c.success]
    if failed_calls:
        ft = Table(title=f"Failed Calls ({len(failed_calls)})", show_header=True, header_style="bold")
        ft.add_column("Turn", justify="right", style="dim")
        ft.add_column("Time", style="dim")
        ft.add_column("Model", style="cyan")
        ft.add_column("E2E", justify="right")

        for c in failed_calls[:10]:
            ts_str = datetime.fromtimestamp(c.ts / 1000).strftime("%m-%d %H:%M:%S") if c.ts else "-"
            dur = f"{c.e2e_ms}ms" if c.e2e_ms is not None else "-"
            ft.add_row(
                str(c.turn_index),
                ts_str,
                c.model or "?",
                dur,
            )
        if len(failed_calls) > 10:
            ft.add_row(f"... {len(failed_calls) - 10} more ...", "", "", "")
        console.print(ft)

    # Performance over time (adaptive buckets)
    calls_with_dur = [c for c in report.calls if c.e2e_ms is not None]
    if calls_with_dur and len(calls_with_dur) > 1:
        import statistics
        from claw_llm_doctor.analyzers.routing import _auto_bucket_minutes

        ts_values = [c.ts for c in calls_with_dur if c.ts]
        first_ts = min(ts_values) if ts_values else 0
        last_ts = max(ts_values) if ts_values else 0
        # Build a fake timeline for _auto_bucket_minutes
        bucket_minutes = _auto_bucket_minutes(
            [{"timestamp": first_ts}, {"timestamp": last_ts}]
        ) if first_ts and last_ts and last_ts > first_ts else 10
        bucket_ms = bucket_minutes * 60 * 1000

        buckets: dict[int, list] = {}
        for c in calls_with_dur:
            if not c.ts:
                continue
            idx = (c.ts - first_ts) // bucket_ms
            buckets.setdefault(idx, []).append(c)

        if len(buckets) > 1:
            bt = Table(title="Performance Over Time", show_header=True, header_style="bold")
            bt.add_column("Time Window", style="dim")
            bt.add_column("Calls", justify="right")
            bt.add_column("Avg Lat.", justify="right")
            bt.add_column("Avg tok/s", justify="right")
            bt.add_column("Models", style="cyan", max_width=40)

            for idx in sorted(buckets):
                bc = buckets[idx]
                start_ts = first_ts + idx * bucket_ms
                end_ts = start_ts + bucket_ms
                start_str = datetime.fromtimestamp(start_ts / 1000).strftime("%m-%d %H:%M")
                end_str = datetime.fromtimestamp(end_ts / 1000).strftime("%m-%d %H:%M")
                lats = [c.e2e_ms for c in bc if c.e2e_ms is not None]
                tps_list = [c.output_tps for c in bc if c.output_tps > 0]
                models = sorted(set(c.model or "?" for c in bc))
                bt.add_row(
                    f"{start_str}-{end_str}",
                    str(len(bc)),
                    f"{statistics.mean(lats):.0f}ms" if lats else "-",
                    f"{statistics.mean(tps_list):.1f}" if tps_list else "-",
                    ", ".join(models),
                )
            console.print(bt)


# -- Executive Summary -----------------------------------------------------


def print_executive_summary(
    routing: RoutingReport,
    contexts: list[ContextReport] | None = None,
    thinkings: list[ThinkingReport] | None = None,
    performances: list[PerformanceReport] | None = None,
) -> None:
    """Print a concise executive summary at the top of the full report."""
    console.print()
    console.print(Panel("[bold]Executive Summary[/bold]", style="green"))

    # Overview line
    session_count = len(routing.session_summaries)
    total_calls = routing.total_calls

    # Compute time span from timeline
    if routing.timeline:
        first_ts = routing.timeline[0]["timestamp"]
        last_ts = routing.timeline[-1]["timestamp"]
        span_hours = (last_ts - first_ts) / 3_600_000
        span_str = f"{span_hours:.1f}h" if span_hours >= 1 else f"{(last_ts - first_ts) / 60_000:.0f}m"
    else:
        span_str = "?"

    console.print(f"  Analyzed [bold]{session_count}[/bold] session(s), "
                  f"[bold]{total_calls}[/bold] LLM calls over [bold]{span_str}[/bold]")
    console.print()

    # Aggregate performance stats across all sessions
    agg_input_tokens = 0
    agg_output_tokens = 0
    agg_cache_read = 0
    agg_latencies: list[int] = []
    agg_throughputs: list[float] = []
    if performances:
        for p in performances:
            agg_input_tokens += p.total_input_tokens
            agg_output_tokens += p.total_output_tokens
            agg_cache_read += p.total_cache_read
            for c in p.calls:
                if c.e2e_ms is not None and c.success:
                    agg_latencies.append(c.e2e_ms)
                if c.output_tps > 0 and c.success:
                    agg_throughputs.append(c.output_tps)

    agg_total_prompt = agg_input_tokens + agg_cache_read
    agg_cache_hit = (agg_cache_read / agg_total_prompt) if agg_total_prompt > 0 else 0.0

    # Key metrics table
    t = Table(show_header=True, header_style="bold", title="Key Metrics")
    t.add_column("Metric", style="cyan")
    t.add_column("Value", justify="right")

    t.add_row("Total requests", str(total_calls))
    t.add_row("Success rate", pct(routing.overall_success_rate))
    t.add_row("Input tokens", format_tokens(agg_input_tokens))
    t.add_row("Output tokens", format_tokens(agg_output_tokens))
    t.add_row("Cache read tokens", format_tokens(agg_cache_read))
    cache_color = "green" if agg_cache_hit >= 0.5 else ("yellow" if agg_cache_hit >= 0.2 else "red")
    t.add_row("Cache hit rate", Text(pct(agg_cache_hit), style=cache_color))
    if agg_latencies:
        import statistics
        avg_lat = statistics.mean(agg_latencies)
        t.add_row("Avg latency (success)", f"{avg_lat:.0f}ms")
    if agg_throughputs:
        import statistics
        avg_tps = statistics.mean(agg_throughputs)
        t.add_row("Avg throughput (success)", f"{avg_tps:.1f} tok/s")
    console.print(t)

    console.print()

    # Model success rates
    if routing.primary_model:
        p_rate = routing.primary_success_rate
        p_color = "green" if p_rate >= 0.95 else ("yellow" if p_rate >= 0.8 else "red")
        console.print(f"  Primary model: [cyan]{routing.primary_model}[/cyan]  "
                      f"success=[{p_color}]{pct(p_rate)}[/{p_color}]  "
                      f"({routing.primary_calls} calls)")

    if routing.fallback_calls > 0:
        f_rate = routing.fallback_success_rate
        f_color = "green" if f_rate >= 0.95 else ("yellow" if f_rate >= 0.8 else "red")
        console.print(f"  Fallback models: success=[{f_color}]{pct(f_rate)}[/{f_color}]  "
                      f"({routing.fallback_calls} calls)")

    console.print()

    # Findings
    findings: list[str] = []

    if routing.total_failure > 0:
        findings.append(f"[red]{routing.total_failure}[/red] failed call(s) "
                       f"({pct(routing.total_failure / routing.total_calls)} failure rate)")

    if routing.fallback_chains:
        findings.append(f"{len(routing.fallback_chains)} fallback chain(s) detected")

    # Thinking leakage
    total_leakage = 0
    if thinkings:
        total_leakage = sum(t.turns_with_leakage for t in thinkings)
    if total_leakage > 0:
        findings.append(f"[red]{total_leakage}[/red] turn(s) with thinking leakage")

    # High failure rate models
    for model, count in routing.calls_by_model.most_common():
        fail = routing.failure_by_model.get(model, 0)
        if count >= 3 and fail / count > 0.3:
            findings.append(f"Model [cyan]{model}[/cyan] has {pct(fail / count)} failure rate ({fail}/{count})")

    if findings:
        console.print("  [bold]Findings:[/bold]")
        for f in findings:
            console.print(f"    \u2022 {f}")
    else:
        console.print("  [green]No issues detected.[/green]")

    console.print()


# -- Full report -----------------------------------------------------------


def print_full_report(
    routing: RoutingReport | None = None,
    context: ContextReport | None = None,
    prompt_order: PromptOrderReport | None = None,
    compression: CompressionReport | None = None,
    thinking: ThinkingReport | None = None,
    performance: PerformanceReport | None = None,
) -> None:
    if routing:
        print_routing(routing)
    if context:
        print_context(context)
    if prompt_order:
        print_prompt_order(prompt_order)
    if compression:
        print_compression(compression)
    if thinking:
        print_thinking(thinking)
    if performance:
        print_performance(performance)

    console.print()


# -- Session replay --------------------------------------------------------


def _relative_ts(ts_ms: int, origin_ms: int) -> str:
    """Format a timestamp as +Xs or +Xm Ys relative to *origin_ms*."""
    delta_s = max(0, (ts_ms - origin_ms)) / 1000.0
    if delta_s < 60:
        return f"+{delta_s:.1f}s"
    minutes = int(delta_s // 60)
    seconds = delta_s % 60
    return f"+{minutes}m{seconds:04.1f}s"


def _truncate(text: str, limit: int = 120) -> str:
    """Truncate a string, appending an ellipsis if it was trimmed."""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "\u2026"


def print_replay(session: Session) -> None:
    """Print a human-readable conversation replay for *session*."""
    console.print()
    console.print(
        Panel(
            f"[bold]Session Replay[/bold]  [cyan]{session.key}[/cyan]",
            style="magenta",
        )
    )

    if not session.records:
        console.print("  (no records)")
        return

    start_ts = session.records[0].ts

    for rec in session.records:
        offset = _relative_ts(rec.ts, start_ts)
        rtype = rec.type

        # -- agent lifecycle -----------------------------------------------
        if rtype == "agent.start":
            prompt = rec.raw.get("prompt", "")
            prompt_preview = _truncate(prompt, 100)
            console.print(
                f"\n  [dim]{offset}[/dim]  [bold magenta]AGENT START[/bold magenta]"
                f"  agent=[cyan]{rec.agent_id or '?'}[/cyan]"
            )
            if prompt_preview:
                console.print(f"           trigger: {prompt_preview}")

        elif rtype == "agent.end":
            dur = rec.raw.get("durationMs")
            ok = rec.raw.get("success", True)
            status = "[green]OK[/green]" if ok else "[red]FAIL[/red]"
            dur_str = f"  ({dur}ms)" if dur is not None else ""
            console.print(
                f"\n  [dim]{offset}[/dim]  [bold magenta]AGENT END[/bold magenta]"
                f"  {status}{dur_str}"
            )

        # -- LLM input (user turn) ----------------------------------------
        elif rtype == "llm.input":
            model = rec.model or "?"
            provider = rec.provider or "?"
            payload = rec.payload or {}
            user_msgs = payload.get("userMessages", [])
            user_text = ""
            if isinstance(user_msgs, list) and user_msgs:
                last = user_msgs[-1]
                if isinstance(last, dict):
                    user_text = last.get("content", "") or ""
                elif isinstance(last, str):
                    user_text = last
            if not user_text:
                user_text = payload.get("prompt", "") or ""
            user_preview = _truncate(str(user_text), 200)

            console.print(
                f"\n  [dim]{offset}[/dim]  [bold blue]LLM INPUT[/bold blue]"
                f"  model=[cyan]{model}[/cyan]  provider=[cyan]{provider}[/cyan]"
            )
            if user_preview:
                console.print(f"           [blue]{user_preview}[/blue]")

        # -- LLM output (assistant turn) -----------------------------------
        elif rtype == "llm.output":
            model = rec.model or "?"
            provider = rec.provider or "?"
            dur = rec.duration_ms
            usage = rec.usage or {}
            in_tok = usage.get("input", "?")
            out_tok = usage.get("output", "?")
            payload = rec.payload or {}
            assistant_text = ""
            la = payload.get("lastAssistant")
            if isinstance(la, dict):
                content_blocks = la.get("content", [])
                if isinstance(content_blocks, list):
                    parts = [b.get("text", "") for b in content_blocks
                             if isinstance(b, dict) and b.get("type") == "text"]
                    assistant_text = "\n".join(p for p in parts if p)
            if not assistant_text:
                texts = payload.get("assistantTexts", [])
                if isinstance(texts, list) and texts:
                    assistant_text = texts[-1] if isinstance(texts[-1], str) else ""
            asst_preview = _truncate(assistant_text, 200)

            dur_str = f"  {dur}ms" if dur is not None else ""
            console.print(
                f"\n  [dim]{offset}[/dim]  [bold green]LLM OUTPUT[/bold green]"
                f"  model=[cyan]{model}[/cyan]  tokens=[dim]{in_tok}/{out_tok}[/dim]{dur_str}"
            )
            if asst_preview:
                console.print(f"           [green]{asst_preview}[/green]")

        # -- Tool start ----------------------------------------------------
        elif rtype == "tool.start":
            tool = rec.raw.get("toolName", "?")
            params = rec.raw.get("params", {})
            params_str = _truncate(str(params), 100)
            console.print(
                f"\n  [dim]{offset}[/dim]  [bold yellow]TOOL START[/bold yellow]"
                f"  [yellow]{tool}[/yellow]"
            )
            console.print(f"           [dim]{params_str}[/dim]")

        # -- Tool end ------------------------------------------------------
        elif rtype == "tool.end":
            tool = rec.raw.get("toolName", "?")
            ok = rec.raw.get("success", True)
            dur = rec.raw.get("durationMs")
            dur_str = f"  {dur}ms" if dur is not None else ""
            if ok:
                status = "[green]OK[/green]"
            else:
                err = rec.error or "unknown error"
                status = f"[red]ERR: {_truncate(err, 80)}[/red]"
            console.print(
                f"  [dim]{offset}[/dim]  [bold yellow]TOOL END[/bold yellow]"
                f"    [yellow]{tool}[/yellow]  {status}{dur_str}"
            )

        # -- Compaction events ---------------------------------------------
        elif rtype == "compaction.before":
            console.print(
                f"\n  [dim]{offset}[/dim]  [bold red]COMPACTION BEFORE[/bold red]"
            )
        elif rtype == "compaction.after":
            console.print(
                f"  [dim]{offset}[/dim]  [bold red]COMPACTION AFTER[/bold red]"
            )

        # -- Other event types ---------------------------------------------
        else:
            console.print(
                f"  [dim]{offset}[/dim]  [dim]{rtype}[/dim]"
            )

    console.print()
