"""CLI entry point for Sentinel.

This is a minimal typer app. Phase 5 fills in the incident/demo commands; Task 2.3 adds the
``ingest-runbooks`` command and the eval runner lands in Phase 7. The module is the
``[project.scripts]`` target so ``uv run sentinel`` works from the very first commit.
"""

from __future__ import annotations

import typer

from sentinel.rag.ingest import ingest_runbooks

app = typer.Typer()


@app.callback()
def main() -> None:
    """Sentinel — Agentic Incident Triage Assistant (SRE Copilot)."""
    return None


@app.command("ingest-runbooks")
def ingest_runbooks_cmd() -> None:
    """Chunk, embed and upsert the runbook corpus into the `runbooks` table (Task 2.3)."""
    ingested = ingest_runbooks()
    typer.echo(f"Ingested {ingested} runbook chunk(s).")


if __name__ == "__main__":
    app()
