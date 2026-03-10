"""Terminal reporter — rich-formatted output for all analysis layers."""

from __future__ import annotations

from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from analyzers.routing import RoutingReport
from analyzers.context import ContextReport
from analyzers.prompt_order import PromptOrderReport
from analyzers.prompt_compression import CompressionReport
from analyzers.thinking import ThinkingReport
from loader import Session
from utils.tokens import format_tokens


console = Console()


# ── Helpers ───────────────────────────────────────────────────────────────


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def health_color(health: str) -> str:
    return {"green": "green", "yellow": "yellow", "red": "red"}.get(health, "white")


def severity_color(severity: str) -> str:
    return {"none": "green", "low": "yellow", "medium": "bright_red", "high": "red"}.get(severity, "white")


# ── Layer 1: Routing ──────────────────────────────────────────────────────


def print_routing(report: RoutingReport) -> None:
    console.print()
    console.print(Panel("[bold]Layer 1: LM Routing Analysis[/bold]", style="blue"))

    # Summary table
    t = Table(title="Routing Summary", show_header=True, header_style="bold")
    t.add_column("Metric", style="cyan")
    t.add_column("Value", justify="right")

    t.add_row("Total LLM calls", str(report.total_calls))
    t.add_row("Primary calls", str(report.primary_calls))
    t.add_row("Fallback calls", str(report.fallback_calls))
    t.add_row("Unknown routing", str(report.unknown_routing))
    t.add_row("Primary success rate", pct(report.primary_success_rate))
    t.add_row("Fallback success rate", pct(report.fallback_success_rate))
    t.add_row("Overall success rate", pct(report.overall_success_rate))
    t.add_row("Fallback trigger rate", pct(report.fallback_trigger_rate))
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

    # Routing timeline
    if report.timeline:
        tt = Table(title="Routing Timeline", show_header=True, header_style="bold")
        tt.add_column("Timestamp", style="dim")
        tt.add_column("Session", style="cyan", max_width=16)
        tt.add_column("Model", style="cyan")
        tt.add_column("Provider")
        tt.add_column("Role", justify="center")
        tt.add_column("OK", justify="center")
        tt.add_column("Duration", justify="right")

        for entry in report.timeline:
            ts_str = str(entry["timestamp"])
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


# ── Layer 3a: Context ─────────────────────────────────────────────────────


def print_context(report: ContextReport) -> None:
    console.print()
    console.print(Panel("[bold]Layer 3a: Context Composition Analysis[/bold]", style="blue"))

    console.print(f"  Session: [cyan]{report.session_key}[/cyan]")
    console.print(f"  Turns analyzed: {len(report.turns)}")
    console.print(f"  Peak utilization: {pct(report.peak_utilization)}")
    console.print(f"  Avg utilization: {pct(report.avg_utilization)}")
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
        t.add_column("Util", justify="right")
        t.add_column("HP", justify="center")

        for comp in report.turns:
            color = health_color(comp.health)
            t.add_row(
                str(comp.turn_index),
                format_tokens(comp.system_tokens),
                format_tokens(comp.tool_def_tokens),
                format_tokens(comp.history_tokens),
                format_tokens(comp.tool_result_tokens),
                format_tokens(comp.thinking_tokens),
                format_tokens(comp.total_tokens),
                pct(comp.utilization),
                Text("●", style=color),
            )
        console.print(t)

    if report.large_payloads:
        console.print(f"\n  [yellow]Warning:[/yellow] {len(report.large_payloads)} turns with large tool results (>{format_tokens(5000)} tokens)")
        for lp in report.large_payloads[:5]:
            console.print(f"    Turn {lp['turn']}: tool_result={format_tokens(lp['tool_result_tokens'])}")

    # Context growth curve (ASCII bar chart)
    curve = report.growth_curve()
    if curve:
        max_tokens = max((pt["total_tokens"] for pt in curve), default=1) or 1
        bar_width = 40
        console.print()
        console.print("  [bold]Context Growth Curve[/bold]")
        console.print()
        for pt in curve:
            bar_len = int((pt["total_tokens"] / max_tokens) * bar_width)
            bar = "█" * bar_len + "░" * (bar_width - bar_len)
            delta = pt["delta"]
            delta_str = f"+{delta}" if delta >= 0 else str(delta)
            color = "green" if delta >= 0 else "red"
            console.print(
                f"    Turn {pt['turn_index']:3d}: {bar} "
                f"{format_tokens(pt['total_tokens']):>7s}  "
                f"[{color}]{delta_str:>7s}[/{color}]"
            )
        console.print()


# ── Layer 3b: Prompt Order ────────────────────────────────────────────────


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


# ── Layer 3c: Compression ────────────────────────────────────────────────


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

    # Similarity curve
    if report.similarity_curve and len(report.similarity_curve) > 1:
        console.print("\n  Similarity vs baseline:")
        for i, sim in enumerate(report.similarity_curve):
            bar_len = int(sim * 30)
            bar = "█" * bar_len + "░" * (30 - bar_len)
            color = "green" if sim > 0.9 else "yellow" if sim > 0.7 else "red"
            console.print(f"    Turn {i:3d}: [{color}]{bar}[/{color}] {pct(sim)}")


# ── Layer 3d: Thinking ────────────────────────────────────────────────────


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

        lt = Table(title="Leakage Pattern Counts", show_header=True, header_style="bold")
        lt.add_column("Pattern", style="red")
        lt.add_column("Count", justify="right")
        for name, count in sorted(report.leakage_pattern_counts.items(), key=lambda x: -x[1]):
            lt.add_row(name, str(count))
        console.print(lt)

        # Show examples
        for turn in report.turns:
            if turn.has_leakage:
                console.print(f"\n  Turn {turn.turn_index} leakage examples:")
                for li in turn.leakage_instances[:3]:
                    console.print(f"    [{li.pattern_name}] \"{li.matched_text}\"")
                    console.print(f"    [dim]...{li.context}...[/dim]")
    else:
        console.print(f"\n  [green]No thinking leakage detected.[/green]")

    # Per-turn thinking summary
    thinking_turns = [t for t in report.turns if t.has_thinking]
    if thinking_turns:
        tt = Table(title="Thinking per Turn", show_header=True, header_style="bold")
        tt.add_column("Turn", justify="right", style="dim")
        tt.add_column("Think Tokens", justify="right")
        tt.add_column("Content Tokens", justify="right")
        tt.add_column("Ratio", justify="right")
        tt.add_column("Categories", max_width=30)
        tt.add_column("Leak", justify="center")

        for t in thinking_turns:
            cats = ", ".join(sorted({b.category for b in t.thinking_blocks}))
            leak_indicator = Text("●", style=severity_color(t.leakage_severity))
            tt.add_row(
                str(t.turn_index),
                format_tokens(t.thinking_tokens),
                format_tokens(t.content_tokens),
                pct(t.thinking_ratio),
                cats,
                leak_indicator,
            )
        console.print(tt)


# ── Full report ───────────────────────────────────────────────────────────


def print_full_report(
    routing: RoutingReport | None = None,
    context: ContextReport | None = None,
    prompt_order: PromptOrderReport | None = None,
    compression: CompressionReport | None = None,
    thinking: ThinkingReport | None = None,
) -> None:
    console.print(Panel("[bold magenta]claw_llm_doctor — Diagnostic Report[/bold magenta]", style="magenta"))

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

    console.print()


# ── Session replay ───────────────────────────────────────────────────────


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

        # ── agent lifecycle ──────────────────────────────────────────
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

        # ── LLM input (user turn) ───────────────────────────────────
        elif rtype == "llm.input":
            model = rec.model or "?"
            provider = rec.provider or "?"
            # Try to extract the user prompt text
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

        # ── LLM output (assistant turn) ──────────────────────────────
        elif rtype == "llm.output":
            model = rec.model or "?"
            provider = rec.provider or "?"
            dur = rec.duration_ms
            usage = rec.usage or {}
            in_tok = usage.get("input", "?")
            out_tok = usage.get("output", "?")
            # Assistant text
            payload = rec.payload or {}
            assistant_text = payload.get("lastAssistant", "")
            if not assistant_text:
                texts = payload.get("assistantTexts", [])
                if texts:
                    assistant_text = texts[-1] if isinstance(texts[-1], str) else ""
            asst_preview = _truncate(str(assistant_text), 200)

            dur_str = f"  {dur}ms" if dur is not None else ""
            console.print(
                f"\n  [dim]{offset}[/dim]  [bold green]LLM OUTPUT[/bold green]"
                f"  model=[cyan]{model}[/cyan]  tokens=[dim]{in_tok}/{out_tok}[/dim]{dur_str}"
            )
            if asst_preview:
                console.print(f"           [green]{asst_preview}[/green]")

        # ── Tool start ───────────────────────────────────────────────
        elif rtype == "tool.start":
            tool = rec.raw.get("toolName", "?")
            params = rec.raw.get("params", {})
            params_str = _truncate(str(params), 100)
            console.print(
                f"\n  [dim]{offset}[/dim]  [bold yellow]TOOL START[/bold yellow]"
                f"  [yellow]{tool}[/yellow]"
            )
            console.print(f"           [dim]{params_str}[/dim]")

        # ── Tool end ─────────────────────────────────────────────────
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

        # ── Compaction events ────────────────────────────────────────
        elif rtype == "compaction.before":
            console.print(
                f"\n  [dim]{offset}[/dim]  [bold red]COMPACTION BEFORE[/bold red]"
            )
        elif rtype == "compaction.after":
            console.print(
                f"  [dim]{offset}[/dim]  [bold red]COMPACTION AFTER[/bold red]"
            )

        # ── Other event types (model.resolve, diagnostic, etc.) ──────
        else:
            console.print(
                f"  [dim]{offset}[/dim]  [dim]{rtype}[/dim]"
            )

    console.print()
