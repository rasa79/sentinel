"""Shared pytest fixtures for node unit tests."""

from __future__ import annotations

import pytest

from sentinel.agent.schemas import AlertInfo


@pytest.fixture
def alert() -> AlertInfo:
    return AlertInfo(
        name="high-latency", service="orders", severity="high", raw={"alert": "latency"}
    )
