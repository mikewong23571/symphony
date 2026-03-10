from __future__ import annotations

from symphony.agent_runner.events import extract_usage_snapshot


def test_extract_usage_snapshot_preserves_zero_token_values() -> None:
    usage = extract_usage_snapshot(
        {
            "params": {
                "usage": {
                    "input_tokens": 0,
                    "inputTokens": 42,
                    "output_tokens": 0,
                    "outputTokens": 11,
                    "total_tokens": 0,
                    "totalTokens": 53,
                }
            }
        }
    )

    assert usage is not None
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0
    assert usage.total_tokens == 0
