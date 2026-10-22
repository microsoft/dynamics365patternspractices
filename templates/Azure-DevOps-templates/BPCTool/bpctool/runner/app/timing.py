"""Duration helpers for apply / job summaries."""

from __future__ import annotations


def format_duration_ms(ms: int | float | None) -> str:
    if ms is None:
        return "n/a"
    value = max(0, int(ms))
    if value < 1000:
        return f"{value}ms"
    seconds = value / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    if minutes >= 60:
        return f"{minutes // 60}h {minutes % 60}m"
    rem = seconds - minutes * 60
    return f"{minutes}m {rem:.1f}s"


def summarize_timings(timings: list[dict], *, total_ms: int | None = None) -> str:
    """Human-readable multi-line summary for logs."""
    lines: list[str] = []
    for row in timings:
        step = row.get("stepId") or row.get("step_id") or "?"
        skipped = bool(row.get("skipped"))
        duration = row.get("durationMs", row.get("duration_ms", 0))
        if skipped:
            lines.append(f"  {step}: skipped")
        else:
            lines.append(f"  {step}: {format_duration_ms(duration)}")
    if total_ms is not None:
        lines.append(f"  total: {format_duration_ms(total_ms)}")
    return "\n".join(lines) if lines else "  (no steps)"
