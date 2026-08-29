"""CLI entry point for Sentinel (PLAN.md Task 5.5 / Task 2.3).

Typer app wiring ``sentinel incidents list|show|approve|reject|watch``, the ``sentinel demo``
orchestration, and the ``sentinel ingest-runbooks`` command. The module is the
``[project.scripts]`` target so ``uv run sentinel`` works from the very first commit.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import typer
from rich.console import Console
from rich.table import Column, Table

from sentinel.cli.demo import run_demo, watch_incident
from sentinel.rag.ingest import ingest_runbooks

app = typer.Typer()
incidents_app = typer.Typer()
app.add_typer(incidents_app, name="incidents")
evals_app = typer.Typer()
app.add_typer(evals_app, name="evals")

console = Console()
_DEFAULT_API = "http://localhost:8000"

# Mock mode must be perfect (the harness knows the answer); live mode accepts a small miss rate
# because a real model is allowed to be less than perfect (D13 / plan Task 7.2).
_THRESHOLD = {"mock": 1.0, "live": 0.75}


def _client(api: str) -> httpx.Client:
    """Build an httpx client for the API, tolerating a trailing slash on the base URL."""
    return httpx.Client(base_url=api.rstrip("/"), timeout=10)


@app.callback()
def main() -> None:
    """Sentinel — Agentic Incident Triage Assistant (SRE Copilot)."""
    return None


# --------------------------------------------------------------------------- incidents group


@incidents_app.command("list")
def incidents_list(
    status: str | None = typer.Option(None, "--status", help="Filter by incident status"),
    page: int = typer.Option(1, "--page", help="Page number"),
    per_page: int = typer.Option(20, "--per-page", help="Rows per page"),
    api: str = typer.Option(_DEFAULT_API, "--api", "-a", help="API base URL"),
) -> None:
    """List incidents, optionally filtered by status."""
    params: dict[str, Any] = {"page": page, "per_page": per_page}
    if status:
        params["status"] = status
    try:
        with _client(api) as client:
            resp = client.get("/incidents", params=params)
            resp.raise_for_status()
            body: dict[str, Any] = resp.json()
    except httpx.HTTPError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    table = Table(Column("id", width=36, no_wrap=True), "alert", "service", "severity", "status")
    for item in body["items"]:
        table.add_row(
            item["id"], item["alert_name"], item["service"], item["severity"], item["status"]
        )
    console.print(table)
    console.print(f"page {body['page']} / total {body['total']}")


@incidents_app.command("show")
def incidents_show(
    incident_id: str,
    api: str = typer.Option(_DEFAULT_API, "--api", "-a", help="API base URL"),
) -> None:
    """Show an incident: its summary, ordered agent trace and graph state."""
    try:
        with _client(api) as client:
            resp = client.get(f"/incidents/{incident_id}")
            resp.raise_for_status()
            body: dict[str, Any] = resp.json()
    except httpx.HTTPError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print_json(json.dumps(body, default=str))


@incidents_app.command("approve")
def incidents_approve(
    incident_id: str,
    api: str = typer.Option(_DEFAULT_API, "--api", "-a", help="API base URL"),
) -> None:
    """Resume the incident's investigation with a human approval (D6)."""
    _resume(incident_id, "approve", api)


@incidents_app.command("reject")
def incidents_reject(
    incident_id: str,
    api: str = typer.Option(_DEFAULT_API, "--api", "-a", help="API base URL"),
) -> None:
    """Resume the incident's investigation with a rejection (routes to report as rejected)."""
    _resume(incident_id, "reject", api)


def _resume(incident_id: str, decision: str, api: str) -> None:
    try:
        with _client(api) as client:
            resp = client.post(f"/incidents/{incident_id}/{decision}")
            resp.raise_for_status()
            body: dict[str, Any] = resp.json()
    except httpx.HTTPError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"incident {incident_id}: {body.get('status', decision)}")


@incidents_app.command("watch")
def incidents_watch(
    incident_id: str,
    api: str = typer.Option(_DEFAULT_API, "--api", "-a", help="API base URL"),
) -> None:
    """Tail an incident's SSE stream, rendering live node-by-node updates until it completes."""
    code = watch_incident(api, incident_id, console)
    if code:
        raise typer.Exit(code=code)


# --------------------------------------------------------------------------- top-level commands


@app.command("demo")
def demo_cmd(
    api: str = typer.Option(_DEFAULT_API, "--api", "-a", help="API base URL"),
    service_url: str = typer.Option(
        "http://localhost:9001", "--service-url", help="Orders service base URL (chaos target)"
    ),
    alertname: str = typer.Option(
        "error-burst-after-deploy", "--alertname", help="Alert name to fire"
    ),
    service: str = typer.Option("orders", "--service", help="Service label on the alert"),
    chaos: str = typer.Option("bad_deploy", "--chaos", help="Chaos fault to inject"),
    duration: int = typer.Option(60, "--duration", help="Chaos duration (seconds)"),
) -> None:
    """Drive one full investigation: inject a fault, fire the webhook, wait, approve, stream."""
    code = run_demo(api, service_url, alertname, service, chaos, duration, console)
    if code:
        raise typer.Exit(code=code)


@app.command("ingest-runbooks")
def ingest_runbooks_cmd() -> None:
    """Chunk, embed and upsert the runbook corpus into the `runbooks` table (Task 2.3)."""
    ingested = ingest_runbooks()
    typer.echo(f"Ingested {ingested} runbook chunk(s).")


# --------------------------------------------------------------------------- evals group


@evals_app.command("run")
def evals_run(
    mode: str = typer.Option(
        "mock", "--mode", help="eval mode: mock (deterministic) or live (real LLM)"
    ),
    dataset: str | None = typer.Option(None, "--dataset", help="path to a dataset dir"),
) -> None:
    """Run the eval harness over the dataset and print a per-incident + aggregate table."""
    from sentinel.evals.dataset import DEFAULT_DATASET_DIR
    from sentinel.evals.harness import run_all

    ds = dataset or str(DEFAULT_DATASET_DIR)
    results = run_all(mode, ds)
    if not results:
        typer.echo("no dataset entries found")
        raise typer.Exit(code=1)

    table = Table("incident", "chaos", "hypothesis", "remediation")
    for r in results:
        table.add_row(
            r.entry_id,
            r.chaos,
            "ok" if r.hypothesis_ok else "FAIL",
            "ok" if r.remediation_ok else "FAIL",
        )
    console.print(table)

    total = len(results)
    hyp = sum(1 for r in results if r.hypothesis_ok)
    rem = sum(1 for r in results if r.remediation_ok)
    pass_count = sum(1 for r in results if r.hypothesis_ok and r.remediation_ok)
    accuracy = pass_count / total
    threshold = _THRESHOLD.get(mode, 1.0)
    console.print(
        f"{mode}: hypothesis {hyp}/{total}, remediation {rem}/{total}, "
        f"overall {pass_count}/{total} ({accuracy:.0%}) — threshold {threshold:.0%}"
    )
    if accuracy < threshold:
        console.print(f"[red]below threshold ({accuracy:.0%} < {threshold:.0%})[/red]")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
