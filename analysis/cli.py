"""claw-doctor CLI — analyze OpenClaw LLM diagnostic logs."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from loader import load_file, load_dir, group_sessions


DEFAULT_LOG_DIR = Path.home() / ".openclaw" / "logs" / "llm-doctor"


@click.group()
@click.version_option(version="0.1.0")
def main() -> None:
    """claw_llm_doctor — diagnose OpenClaw LLM Provider behaviour."""


# ── Shared options ────────────────────────────────────────────────────────


def source_options(f):
    """Common options for specifying log source."""
    f = click.option(
        "--log-dir",
        type=click.Path(exists=True, file_okay=False),
        default=None,
        help=f"Log directory (default: {DEFAULT_LOG_DIR})",
    )(f)
    f = click.option(
        "--file",
        "log_file",
        type=click.Path(exists=True, dir_okay=False),
        default=None,
        help="Single JSONL file to analyze",
    )(f)
    f = click.option(
        "--session",
        "session_filter",
        default=None,
        help="Filter to a specific sessionKey",
    )(f)
    f = click.option(
        "--token-method",
        type=click.Choice(["char", "tiktoken"]),
        default="char",
        help="Token counting method",
    )(f)
    f = click.option(
        "--format",
        "output_format",
        type=click.Choice(["terminal", "json", "html"]),
        default="terminal",
        help="Output format",
    )(f)
    f = click.option(
        "--output", "-o",
        "output_path",
        default=None,
        help="Output file path (for json/html formats)",
    )(f)
    f = click.option(
        "--primary-model",
        default=None,
        help="Primary model ID (e.g. ark/doubao-seed-2.0-code) for routing classification",
    )(f)
    return f


def _detect_primary_model() -> str | None:
    """Try to read the primary model from the OpenClaw config."""
    import json
    for name in ("openclaw.json", "config.json"):
        config_path = Path.home() / ".openclaw" / name
        if not config_path.exists():
            continue
        try:
            cfg = json.loads(config_path.read_text())
            primary = cfg.get("agents", {}).get("defaults", {}).get("model", {}).get("primary")
            if primary:
                return primary
        except Exception:
            continue
    return None


def load_records(log_dir, log_file):
    """Load records from file or directory."""
    if log_file:
        return load_file(log_file)
    directory = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
    if not directory.exists():
        click.echo(f"Error: log directory not found: {directory}", err=True)
        click.echo(f"Is the claw-llm-doctor plugin installed and has it captured any data?", err=True)
        sys.exit(1)
    return load_dir(directory)


def filter_sessions(sessions, session_filter):
    """Optionally filter to a specific session."""
    if session_filter:
        sessions = [s for s in sessions if session_filter in s.key]
        if not sessions:
            click.echo(f"No sessions matching '{session_filter}'", err=True)
            sys.exit(1)
    return sessions


# ── Commands ──────────────────────────────────────────────────────────────


@main.command()
@source_options
def routing(log_dir, log_file, session_filter, token_method, output_format, output_path, primary_model) -> None:
    """Layer 1: Analyze LM routing (Primary/Fallback, success rates, errors)."""
    from analyzers.routing import analyze_routing
    from reporters.terminal import print_routing

    primary_model = primary_model or _detect_primary_model()
    records = load_records(log_dir, log_file)
    sessions = filter_sessions(group_sessions(records), session_filter)

    report = analyze_routing(sessions, primary_model=primary_model)
    print_routing(report)


@main.command()
@source_options
def context(log_dir, log_file, session_filter, token_method, output_format, output_path, primary_model) -> None:
    """Layer 3a: Analyze context window composition and utilization."""
    from analyzers.context import analyze_context
    from reporters.terminal import print_context

    records = load_records(log_dir, log_file)
    sessions = filter_sessions(group_sessions(records), session_filter)

    for session in sessions:
        report = analyze_context(session, token_method=token_method)
        print_context(report)


@main.command(name="prompt-order")
@source_options
def prompt_order(log_dir, log_file, session_filter, token_method, output_format, output_path, primary_model) -> None:
    """Layer 3b: Analyze system prompt section ordering."""
    from analyzers.prompt_order import analyze_prompt_order
    from reporters.terminal import print_prompt_order

    records = load_records(log_dir, log_file)
    sessions = filter_sessions(group_sessions(records), session_filter)

    for session in sessions:
        report = analyze_prompt_order(session)
        print_prompt_order(report)


@main.command(name="prompt-compression")
@source_options
def prompt_compression(log_dir, log_file, session_filter, token_method, output_format, output_path, primary_model) -> None:
    """Layer 3c: Analyze system prompt compression and content loss."""
    from analyzers.prompt_compression import analyze_compression
    from reporters.terminal import print_compression

    records = load_records(log_dir, log_file)
    sessions = filter_sessions(group_sessions(records), session_filter)

    for session in sessions:
        report = analyze_compression(session, token_method=token_method)
        print_compression(report)


@main.command()
@source_options
def thinking(log_dir, log_file, session_filter, token_method, output_format, output_path, primary_model) -> None:
    """Layer 3d: Analyze thinking process separation and leakage."""
    from analyzers.thinking import analyze_thinking
    from reporters.terminal import print_thinking

    records = load_records(log_dir, log_file)
    sessions = filter_sessions(group_sessions(records), session_filter)

    for session in sessions:
        report = analyze_thinking(session, token_method=token_method)
        print_thinking(report)


@main.command()
@source_options
def full(log_dir, log_file, session_filter, token_method, output_format, output_path, primary_model) -> None:
    """Run all analysis layers and generate a complete report."""
    from analyzers.routing import analyze_routing
    from analyzers.context import analyze_context
    from analyzers.prompt_order import analyze_prompt_order
    from analyzers.prompt_compression import analyze_compression
    from analyzers.thinking import analyze_thinking

    records = load_records(log_dir, log_file)
    sessions = filter_sessions(group_sessions(records), session_filter)

    primary_model = primary_model or _detect_primary_model()
    routing_report = analyze_routing(sessions, primary_model=primary_model)

    # Collect per-session reports
    ctx_reports = []
    order_reports = []
    compress_reports = []
    think_reports = []

    for session in sessions:
        ctx_reports.append(analyze_context(session, token_method=token_method))
        order_reports.append(analyze_prompt_order(session))
        compress_reports.append(analyze_compression(session, token_method=token_method))
        think_reports.append(analyze_thinking(session, token_method=token_method))

    if output_format == "json":
        from reporters.json_report import build_full_json, write_json

        data = build_full_json(
            routing=routing_report,
            contexts=ctx_reports,
            prompt_orders=order_reports,
            compressions=compress_reports,
            thinkings=think_reports,
        )
        write_json(data, output_path)

    elif output_format == "html":
        from reporters.html import generate_html, write_html

        html = generate_html(
            routing=routing_report,
            contexts=ctx_reports,
            prompt_orders=order_reports,
            compressions=compress_reports,
            thinkings=think_reports,
        )
        path = output_path or "report.html"
        write_html(html, path)
        click.echo(f"HTML report written to {path}")

    else:
        from reporters.terminal import print_full_report

        for i, session in enumerate(sessions):
            print_full_report(
                routing=routing_report if i == 0 else None,
                context=ctx_reports[i],
                prompt_order=order_reports[i],
                compression=compress_reports[i],
                thinking=think_reports[i],
            )


@main.command()
@source_options
def replay(log_dir, log_file, session_filter, token_method, output_format, output_path, primary_model) -> None:
    """Replay a session as a human-readable conversation timeline."""
    from reporters.terminal import print_replay

    if not session_filter:
        click.echo("Error: --session is required for replay", err=True)
        sys.exit(1)

    records = load_records(log_dir, log_file)
    sessions = filter_sessions(group_sessions(records), session_filter)

    for session in sessions:
        print_replay(session)


@main.command()
@source_options
def export(log_dir, log_file, session_filter, token_method, output_format, output_path, primary_model) -> None:
    """Export a session's raw records as a JSON array."""
    import json

    if not session_filter:
        click.echo("Error: --session is required for export", err=True)
        sys.exit(1)

    records = load_records(log_dir, log_file)
    sessions = filter_sessions(group_sessions(records), session_filter)

    all_records = []
    for session in sessions:
        for rec in session.records:
            all_records.append(rec.raw)

    # Sort by timestamp
    all_records.sort(key=lambda r: r.get("ts", 0))

    json_str = json.dumps(all_records, indent=2, ensure_ascii=False)

    if output_path:
        Path(output_path).write_text(json_str, encoding="utf-8")
        click.echo(f"Exported {len(all_records)} records to {output_path}")
    else:
        click.echo(json_str)


@main.command()
@source_options
def sessions(log_dir, log_file, session_filter, token_method, output_format, output_path, primary_model) -> None:
    """List all captured sessions."""
    from rich.console import Console
    from rich.table import Table
    from datetime import datetime

    records = load_records(log_dir, log_file)
    all_sessions = filter_sessions(group_sessions(records), session_filter)

    console = Console()
    t = Table(title="Captured Sessions", show_header=True, header_style="bold")
    t.add_column("Session Key", style="cyan", max_width=30)
    t.add_column("Records", justify="right")
    t.add_column("LLM Calls", justify="right")
    t.add_column("Tools", justify="right")
    t.add_column("Start", style="dim")
    t.add_column("End", style="dim")

    for s in all_sessions:
        start, end = s.time_range
        start_str = datetime.fromtimestamp(start / 1000).strftime("%Y-%m-%d %H:%M:%S") if start else "?"
        end_str = datetime.fromtimestamp(end / 1000).strftime("%Y-%m-%d %H:%M:%S") if end else "?"
        t.add_row(
            s.key[:30],
            str(len(s.records)),
            str(len(s.llm_inputs)),
            str(len(s.tool_starts)),
            start_str,
            end_str,
        )

    console.print(t)


if __name__ == "__main__":
    main()
