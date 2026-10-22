from app.timing import format_duration_ms, summarize_timings


def test_format_duration_ms() -> None:
    assert format_duration_ms(42) == "42ms"
    assert format_duration_ms(1500) == "1.5s"
    assert format_duration_ms(65_000) == "1m 5.0s"
    assert format_duration_ms(6_917_548) == "1h 55m"


def test_summarize_timings() -> None:
    text = summarize_timings(
        [
            {"stepId": "process", "durationMs": 1200, "skipped": False},
            {"stepId": "layout", "durationMs": 0, "skipped": True},
        ],
        total_ms=1200,
    )
    assert "process: 1.2s" in text
    assert "layout: skipped" in text
    assert "total: 1.2s" in text
