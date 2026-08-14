"""The usage and quality dashboard's read route (M5 slice 2).

One route, one response, **no model call and no migration**. See
`app/schemas/metrics.py` for the idea and `app/services/metrics_service.py` for the
queries.

**Open to every role, and scoped by row rather than by route.** There is no
`require_role` here on purpose: a role check refuses a route, and what this endpoint
needs is a wider *WHERE clause* for one role. Gating it on `ADMIN` would 403 exactly
the candidates and recruiters who own the rows being counted — which is what
`docs/PLAN.md` originally specified before the mechanism was checked. Every account
sees its own figures; `ADMIN` sees all of them, decided with the owner on 2026-08-15.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CandidateDep, SessionDep
from app.schemas.metrics import UsageReport
from app.services import metrics_service

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/usage", response_model=UsageReport)
async def get_usage(candidate: CandidateDep, session: SessionDep) -> UsageReport:
    """What this account's model calls consumed, and how well the guardrail held.

    Reports; never re-asks. Nothing on this path spends a model call, which is the rule
    the whole slice is built to keep — an observability screen that could bill you for
    looking at it would be a strange kind of observability.
    """
    return await metrics_service.build_usage_report(session, candidate=candidate)
