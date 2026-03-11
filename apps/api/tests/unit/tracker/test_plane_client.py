from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(
    reason=(
        "Plane tracker client tests land with the Plane-backed write adapter; "
        "MIK-40 only neutralizes the generic write contract."
    )
)


def test_plane_client_placeholder_for_milestone_4_validation_command() -> None:
    pass
