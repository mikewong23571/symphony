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
