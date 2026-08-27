"""Unit test for the Loki retry policy with a stub transport (2 failures then success)."""

from __future__ import annotations

from datetime import timedelta

import httpx

from sentinel.tools.loki import query_logs


class _FlakyTransport(httpx.BaseTransport):
    """Raises a connect error on the first two requests, then returns a valid Loki response."""

    def __init__(self) -> None:
        self.calls = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.calls <= 2:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(
            200,
            json={
                "data": {
                    "result": [
                        {
                            "stream": {"service": "orders"},
                            "values": [
                                ["1", '{"service":"orders","message":"boom","level":"error"}']
                            ],
                        }
                    ]
                }
            },
            request=request,
        )


def test_query_logs_retries_transient_failures_then_succeeds() -> None:
    transport = _FlakyTransport()
    client = httpx.Client(transport=transport)
    try:
        logs = query_logs(
            "orders", since=timedelta(minutes=5), limit=10, base_url="http://loki", client=client
        )
    finally:
        client.close()
    assert transport.calls == 3  # 2 failures + 1 success
    assert len(logs) == 1
    assert logs[0].message == "boom"
    assert logs[0].level == "error"
