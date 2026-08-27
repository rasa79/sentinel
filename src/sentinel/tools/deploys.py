"""Deploy-event query interface (reads the shared deployments table)."""

from __future__ import annotations

from sentinel.agent.schemas import DeployEvent
from sentinel.config import Settings
from sentinel.db.models import Deployment
from sentinel.db.session import create_engine_from_url, make_session_factory


def query_deploys(service: str, limit: int = 20) -> list[DeployEvent]:
    """Return the most recent deploy events for ``service`` from the shared deployments table."""
    settings = Settings()
    engine = create_engine_from_url(settings.database.url)
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        rows = (
            session.query(Deployment)
            .filter(Deployment.service == service)
            .order_by(Deployment.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            DeployEvent(
                service=row.service,
                version=row.version,
                event=row.event,
                created_at=row.created_at,
            )
            for row in rows
        ]
