from __future__ import annotations

from datetime import UTC, datetime

from sentinel.tools.loki import _parse_loki_ts


def test_parse_loki_ts():
    ns = 1700000000000000000  # 2023-11-14T22:13:20Z
    ts = _parse_loki_ts(str(ns))
    assert ts is not None
    assert ts == datetime.fromtimestamp(ns / 1e9, tz=UTC)


def test_parse_loki_ts_invalid():
    assert _parse_loki_ts("not-a-number") is None
    assert _parse_loki_ts(None) is None
