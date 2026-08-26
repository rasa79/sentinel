"""CLI entry point for Sentinel (Task 0.1 placeholder).

This is a no-op typer app for now. Phase 5 fills in real commands
(``incidents list|show|approve|reject|watch``, ``demo``, ``ingest-runbooks``)
and the eval runner. The module is kept as the ``[project.scripts]`` target so
``uv run sentinel`` works from the very first commit.
"""

import typer

app = typer.Typer()


@app.callback()
def main() -> None:
    """Sentinel — Agentic Incident Triage Assistant (SRE Copilot)."""
    return None


if __name__ == "__main__":
    app()
