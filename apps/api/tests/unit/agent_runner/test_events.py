from __future__ import annotations

from symphony.agent_runner.events import extract_usage_snapshot


def test_extract_usage_snapshot_preserves_zero_token_values_for_absolute_totals() -> None:
    usage = extract_usage_snapshot(
        {
            "method": "turn/completed",
            "params": {
                "usage": {
                    "input_tokens": 0,
                    "inputTokens": 42,
                    "output_tokens": 0,
                    "outputTokens": 11,
                    "total_tokens": 0,
                    "totalTokens": 53,
                }
            },
        }
    )

    assert usage is not None
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0
    assert usage.total_tokens == 0
    assert usage.is_absolute_total is True


def test_extract_usage_snapshot_reads_total_token_usage_wrappers_as_absolute() -> None:
    usage = extract_usage_snapshot(
        {
            "method": "item/updated",
            "params": {
                "total_token_usage": {
                    "inputTokens": "10",
                    "outputTokens": "5",
                    "totalTokens": "15",
                }
            },
        }
    )

    assert usage is not None
    assert usage.input_tokens == 10
    assert usage.output_tokens == 5
    assert usage.total_tokens == 15
    assert usage.is_absolute_total is True


def test_extract_usage_snapshot_marks_last_token_usage_as_delta_only() -> None:
    usage = extract_usage_snapshot(
        {
            "method": "item/updated",
            "params": {
                "last_token_usage": {
                    "input_tokens": 3,
                    "output_tokens": 2,
                    "total_tokens": 5,
                }
            },
        }
    )

    assert usage is not None
    assert usage.total_tokens == 5
    assert usage.is_absolute_total is False


def test_extract_usage_snapshot_falls_back_to_last_token_usage_for_known_absolute_methods() -> None:
    usage = extract_usage_snapshot(
        {
            "method": "turn/completed",
            "params": {
                "last_token_usage": {
                    "input_tokens": 3,
                    "output_tokens": 2,
                    "total_tokens": 5,
                }
            },
        }
    )

    assert usage is not None
    assert usage.total_tokens == 5
    assert usage.is_absolute_total is False


def test_extract_usage_snapshot_ignores_generic_usage_for_unknown_event_shapes() -> None:
    usage = extract_usage_snapshot(
        {
            "method": "item/updated",
            "params": {
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                }
            },
        }
    )

    assert usage is None


def test_extract_usage_snapshot_accepts_explicit_event_name_override() -> None:
    usage = extract_usage_snapshot(
        {
            "params": {
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                }
            },
        },
        event_name="turn/completed",
    )

    assert usage is not None
    assert usage.input_tokens == 10
    assert usage.output_tokens == 5
    assert usage.total_tokens == 15
    assert usage.is_absolute_total is True


def test_extract_usage_snapshot_reads_token_count_event_via_info_wrapper() -> None:
    # Codex app server sends: {"type": "token_count", "info": {"total_token_usage": {...}}}
    # No "method" field. total_token_usage inside info must be treated as an absolute total.
    usage = extract_usage_snapshot(
        {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": 17561,
                    "cached_input_tokens": 3456,
                    "output_tokens": 431,
                    "reasoning_output_tokens": 184,
                    "total_tokens": 17992,
                },
                "last_token_usage": {
                    "input_tokens": 17561,
                    "output_tokens": 431,
                    "total_tokens": 17992,
                },
                "model_context_window": 258400,
            },
        }
    )

    assert usage is not None
    assert usage.input_tokens == 17561
    assert usage.output_tokens == 431
    assert usage.total_tokens == 17992
    assert usage.is_absolute_total is True


def test_extract_usage_snapshot_token_count_with_null_info_returns_none() -> None:
    usage = extract_usage_snapshot({"type": "token_count", "info": None})
    assert usage is None
