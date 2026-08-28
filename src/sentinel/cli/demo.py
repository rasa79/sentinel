"""The ``sentinel demo`` orchestration + the SSE ``watch`` consumer (PLAN.md Task 5.5).

Phase 5 wires a working demo: inject one chaos fault, fire the alert webhook, open the watch
stream, pause for the approval decision, then stream to a terminal status. Phase 8.2 polishes the
orchestration (health-check messaging, final report panel); here the goal is that one command
drives the whole run and the stream reflects the CLI approval.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any

import httpx
from rich.console import Console
from rich.panel import Panel

_DEFAULT_API = "http://localhost:8000"
_DEFAULT_ORDERS_URL = "http://localhost:9001"
_POLL_INTERVAL = 0.5
# The real DeepSeek call for hypothesize/remediate can take a while; don't race it with a short
# poll window.
_POLL_TIMEOUT = 180.0
# Pause after injecting chaos so the fault is captured by the metrics/log pipelines before the graph
# gathers evidence (a 5s scrape interval needs a couple of cycles to show a breach).
_CHAOS_SETTLE_SECONDS = 8.0
# /work requests to generate while the chaos is active, so the fault manifests as error logs + a
# non-zero error rate for the agent to observe (the chaos only affects /work, so without traffic the
# evidence would stay empty).
_TRAFFIC_HITS = 8
# Terminal statuses: the stream closes (and the graph has no more work) once one is reached.
_TERMINAL_STATUSES = frozenset({"resolved", "rejected", "escalated"})


class DemoError(RuntimeError):
    """Raised when the demo cannot proceed (stack down, bad response)."""


def _parse_frame(lines: list[str]) -> dict[str, Any] | None:
    """Parse one SSE frame into ``{event, data}``; None for a comment/heartbeat-only frame."""
    event: str | None = None
    data_lines: list[str] = []
    for line in lines:
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
    if not data_lines:
        return None
    try:
        data: Any = json.loads("\n".join(data_lines))
    except json.JSONDecodeError:
        return None
    return {"event": event, "data": data}


def _summarize(payload: Any, limit: int = 160) -> str:
    """Compact one-line JSON for a payload, capped and default-str-safe."""
    text = json.dumps(payload, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _render(console: Console, frame: dict[str, Any]) -> None:
    """Render one SSE frame as a human-readable, node-tagged line."""
    event = frame.get("event")
    data = frame.get("data") or {}
    payload = data.get("payload", {})
    node = data.get("node")
    if event == "run_complete":
        status = payload.get("status", "?")
        console.print(f"[green]run complete[/green] — status: [bold]{status}[/bold]")
    elif event == "history":
        console.print(f"[dim]replay[/dim] [{node}] {_summarize(payload)}")
    elif event == "node_update":
        console.print(f"[cyan][{node}][/cyan] {_summarize(payload)}")
    else:
        console.print(f"{event}: {_summarize(payload)}")


def watch_incident(api: str, incident_id: str, console: Console | None = None) -> int:
    """Consume an incident's SSE stream, rendering frames until it closes on terminal status."""
    console = console or Console()
    url = f"{api.rstrip('/')}/incidents/{incident_id}/stream"
    try:
        with httpx.Client(timeout=None) as client:
            with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    console.print(f"[red]stream failed (HTTP {resp.status_code})[/red]")
                    return 1
                frame_lines: list[str] = []
                for line in resp.iter_lines():
                    if line == "":
                        parsed = _parse_frame(frame_lines)
                        frame_lines = []
                        if parsed is not None:
                            _render(console, parsed)
                            if parsed.get("event") == "run_complete":
                                return 0
                    else:
                        frame_lines.append(line)
    except httpx.HTTPError as exc:  # noqa: PERF203 - network errors surface to the caller
        console.print(f"[red]stream error: {exc}[/red]")
        return 1
    return 0


def _alert(alertname: str, service: str, severity: str) -> dict[str, Any]:
    return {
        "status": "firing",
        "labels": {"alertname": alertname, "service": service, "severity": severity},
        "annotations": {"summary": f"{service} {alertname} detected"},
    }


def inject_chaos(service_url: str, chaos_type: str, duration_seconds: int) -> None:
    """POST a chaos fault to a demo service. Raises :class:`DemoError` if the service is down."""
    try:
        with httpx.Client(base_url=service_url, timeout=10) as client:
            resp = client.post(
                "/chaos", json={"type": chaos_type, "duration_seconds": duration_seconds}
            )
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise DemoError(f"could not reach demo service at {service_url}: {exc}") from exc


def generate_traffic(
    service_url: str, hits: int = _TRAFFIC_HITS, span: float = _CHAOS_SETTLE_SECONDS
) -> None:
    """Hit the service /work endpoint so an active chaos fault actually manifests (503s/error logs).

    The chaos types only change the behavior of /work, so without traffic the fault is invisible to
    the observability pipeline and the agent would see healthy metrics. 5xx responses are exactly
    the signal we want; transport errors are ignored.
    """
    url = f"{service_url.rstrip('/')}/work"
    step = span / hits if hits else span
    for _ in range(hits):
        try:
            httpx.get(url, timeout=5)
        except httpx.HTTPError:
            pass
        time.sleep(step)


def fire_alert(api: str, alertname: str, service: str, severity: str) -> str:
    """POST an Alertmanager-style webhook; return the (new or deduped) incident id."""
    try:
        with httpx.Client(base_url=api.rstrip("/"), timeout=10) as client:
            resp = client.post(
                "/alerts/webhook", json={"alerts": [_alert(alertname, service, severity)]}
            )
            resp.raise_for_status()
            body = resp.json()
    except httpx.HTTPError as exc:
        raise DemoError(f"could not reach the Sentinel API at {api}: {exc}") from exc
    return str(body["incident_id"])


def _wait_status(api: str, incident_id: str, targets: set[str], console: Console) -> str:
    """Poll the incident status until it reaches any of ``targets``; return the reached status.

    ``targets`` may contain ``awaiting_approval`` (the human gate) and/or terminal statuses, so the
    demo can proceed whether the investigation pauses for a decision or completes on its own.
    """
    url = f"{api.rstrip('/')}/incidents/{incident_id}"
    deadline = time.monotonic() + _POLL_TIMEOUT
    with httpx.Client(timeout=5) as client:
        while time.monotonic() < deadline:
            try:
                status = str(client.get(url).json()["incident"]["status"])
                if status in targets:
                    return status
            except (httpx.HTTPError, KeyError):
                pass
            time.sleep(_POLL_INTERVAL)
    raise DemoError(f"incident {incident_id} never reached {sorted(targets)!r}")


def run_demo(
    api: str = _DEFAULT_API,
    service_url: str = _DEFAULT_ORDERS_URL,
    alertname: str = "error-burst-after-deploy",
    service: str = "orders",
    chaos_type: str = "bad_deploy",
    duration_seconds: int = 60,
    console: Console | None = None,
) -> int:
    """Drive one full investigation end-to-end and stream it to a terminal status."""
    console = console or Console()
    base = api.rstrip("/")

    try:
        # 1. Inject the fault, then generate /work traffic so it manifests (the chaos only affects
        #    /work). The webhook fires immediately; the gather nodes retry briefly on empty evidence
        #    because the scrape/Loki pipelines lag (LEARN[28]).
        inject_chaos(service_url, chaos_type, duration_seconds)
        console.print(f"injected [bold]{chaos_type}[/bold] on [bold]{service}[/bold]")
        generate_traffic(service_url)
        # A unique alert name keeps repeated demo runs from colliding with the webhook's 60s
        # (alertname, service) dedupe window — each run is its own incident.
        alert_name = f"{alertname}-{uuid.uuid4().hex[:6]}"
        incident_id = fire_alert(base, alert_name, service, "critical")
        console.print(f"webhook accepted — incident [bold]{incident_id}[/bold]")

        # 2. Tail the stream live in a background thread so the approval prompt can run at the
        #    same time (the stream goes idle while the graph waits at the human gate).
        result: dict[str, int] = {"code": 0}

        def _watcher() -> None:
            result["code"] = watch_incident(base, incident_id, console)

        thread = threading.Thread(target=_watcher, daemon=True)
        thread.start()

        # 3. Wait for the graph to reach the human gate, or a terminal status if it found no action
        #    to take. Only a run paused at the gate needs a human decision.
        status = _wait_status(
            base, incident_id, set(_TERMINAL_STATUSES) | {"awaiting_approval"}, console
        )
        if status == "awaiting_approval":
            console.print(
                Panel.fit(
                    "The investigation has paused for a human decision.",
                    title="Approval required",
                    border_style="yellow",
                )
            )
            approved = _yes_no()
            decision = "approve" if approved else "reject"
            with httpx.Client(base_url=base, timeout=10) as client:
                resp = client.post(f"/incidents/{incident_id}/{decision}")
                resp.raise_for_status()
            console.print(f"sent [bold]{decision}[/bold]; streaming to terminal status…")

        # 4. Wait for the run to reach a terminal status, then summarize the final state.
        terminal = _wait_status(base, incident_id, set(_TERMINAL_STATUSES), console)
        thread.join(timeout=_POLL_TIMEOUT)
        with httpx.Client(base_url=base, timeout=10) as client:
            summary = client.get(f"/incidents/{incident_id}").json()
        report = summary.get("state", {}).get("report") or {}
        console.print(
            Panel.fit(
                f"status: {terminal}\n"
                f"summary: {report.get('summary', '') if isinstance(report, dict) else ''}",
                title="Final report",
                border_style="green",
            )
        )
        return result["code"]
    except DemoError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1


def _yes_no() -> bool:
    """Prompt the user for an approval decision (``y``/``n``)."""
    while True:
        answer = input("Approve the remediation? [y/n] ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer 'y' or 'n'.")
