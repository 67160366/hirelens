"""Which moves an application may make, and who may make them.

Pure: no session, no ORM, no HTTP. The same shape as `jobs.decide_retry` and
`pipeline/ranking.py` — facts in, a decision out — so the whole rule set can be
tested exhaustively without a database, and so `application_service` has nothing
left to get wrong except writing the row.

**The rule the milestone hangs on:** a transition is a claim about a person, so it
is derived from something checkable or it is refused. Two consequences are enforced
here rather than left to a caller's good manners:

*   `shortlisted` is reachable only from `screened` **and** only with the id of the
    screening it rests on. A shortlist with no evidence behind it is exactly the
    unverifiable assertion this project refuses everywhere else.
*   `rejected` requires a reason. Nothing about a person disappears silently.

And an illegal move is **refused with its reason**, never ignored. A state machine
that quietly drops a transition it dislikes produces a system where nobody can tell
a decision from a bug.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum

from app.models import Role
from app.models.application import TERMINAL_STATES, ApplicationState


class Mover(StrEnum):
    """Who is allowed to make a move, in terms the rules can be written in.

    Deliberately not `Role`. What matters for most of these is not "is a recruiter"
    but "owns *this* job" — a recruiter has no business rejecting someone else's
    applicant, and expressing that as a role would make it look like they did.
    """

    APPLICANT = "applicant"
    """The person whose application it is."""

    JOB_OWNER = "job_owner"
    """Whoever owns the posting. Admin counts, via `Actor.of`."""

    SYSTEM = "system"
    """A worker following a `Screening` row. Not a person, and never given a
    transition that expresses an opinion about anybody."""


@dataclass(frozen=True, slots=True)
class Actor:
    """Who is asking, resolved against this particular application."""

    mover: Mover
    role: Role | None = None
    """The role held right now, stored on the event so the audit entry says what
    was true at the time. `None` for the system, which holds no role."""

    account_id: uuid.UUID | None = None
    """**Which account**, carried rather than derived. An earlier version worked it
    out from the mover — the applicant's id is on the application — and had nowhere
    to get the job owner's, so every recruiter decision was logged as though the
    system had made it. A log that cannot tell a person from a worker is not an
    audit log, and no test caught it: the one that should have asserted the *role*
    and not the id. `None` only for `SYSTEM`."""

    @classmethod
    def of(
        cls, role: Role, *, account_id: uuid.UUID, is_applicant: bool, is_job_owner: bool
    ) -> Actor | None:
        """Resolve a signed-in account against one application, or `None` if it is
        neither party. An admin is treated as the job's owner: it is the wider of
        the two, and `require_role` already lets admin everywhere."""
        if is_job_owner or role is Role.ADMIN:
            return cls(Mover.JOB_OWNER, role, account_id)
        if is_applicant:
            return cls(Mover.APPLICANT, role, account_id)
        return None


SYSTEM = Actor(Mover.SYSTEM)
"""No role and no account: a worker following a `Screening` row is not a person."""


@dataclass(frozen=True, slots=True)
class Transition:
    """An approved move, ready to be written as a row and an event."""

    to_state: ApplicationState
    reason: str | None = None
    screening_id: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class Refused:
    """A move that may not be made, and why — in words a user can be shown."""

    why: str


# Who may move an application from where, to where. Read it as: from this state,
# this mover may reach these states.
_ALLOWED: dict[ApplicationState, dict[Mover, frozenset[ApplicationState]]] = {
    ApplicationState.APPLIED: {
        Mover.SYSTEM: frozenset({ApplicationState.SCREENING}),
        Mover.JOB_OWNER: frozenset({ApplicationState.REJECTED}),
        Mover.APPLICANT: frozenset({ApplicationState.WITHDRAWN}),
    },
    ApplicationState.SCREENING: {
        # Back to `applied` when the screening could not be produced: the honest
        # place for an application whose evidence never arrived is where it started,
        # not a state that implies somebody looked.
        Mover.SYSTEM: frozenset({ApplicationState.SCREENED, ApplicationState.APPLIED}),
        Mover.JOB_OWNER: frozenset({ApplicationState.REJECTED}),
        Mover.APPLICANT: frozenset({ApplicationState.WITHDRAWN}),
    },
    ApplicationState.SCREENED: {
        # A re-screen after the requirements changed puts it back in flight.
        Mover.SYSTEM: frozenset({ApplicationState.SCREENING}),
        Mover.JOB_OWNER: frozenset({ApplicationState.SHORTLISTED, ApplicationState.REJECTED}),
        Mover.APPLICANT: frozenset({ApplicationState.WITHDRAWN}),
    },
    ApplicationState.SHORTLISTED: {
        Mover.SYSTEM: frozenset({ApplicationState.SCREENING}),
        Mover.JOB_OWNER: frozenset({ApplicationState.REJECTED}),
        Mover.APPLICANT: frozenset({ApplicationState.WITHDRAWN}),
    },
    # `rejected` and `withdrawn` are terminal and appear here as empty on purpose,
    # so adding a state and forgetting its row is a KeyError rather than a silent
    # "no moves allowed".
    ApplicationState.REJECTED: {},
    ApplicationState.WITHDRAWN: {},
}

NEEDS_EVIDENCE = frozenset({ApplicationState.SHORTLISTED})
"""Moves that may not be made without naming the screening behind them."""

NEEDS_REASON = frozenset({ApplicationState.REJECTED})
"""Moves that may not be made silently."""


def plan_transition(
    current: ApplicationState,
    to_state: ApplicationState,
    *,
    actor: Actor,
    reason: str | None = None,
    screening_id: str | None = None,
    note: str | None = None,
) -> Transition | Refused:
    """Decide whether this move may be made, and on what terms.

    Everything it needs is an argument; nothing is looked up. The caller resolves
    who the actor is and finds the completed screening, and this decides.
    """
    if current in TERMINAL_STATES:
        return Refused(why=f"This application is {current.value} and cannot be moved again.")

    if to_state == current:
        # Not an error and not a move. Saying so beats writing an event that records
        # nothing happening, which would make the log lie about how much did.
        return Refused(why=f"This application is already {current.value}.")

    permitted = _ALLOWED[current].get(actor.mover, frozenset())
    if to_state not in permitted:
        return Refused(why=_refusal(current, to_state, actor))

    if to_state in NEEDS_REASON and not (reason or "").strip():
        return Refused(why=f"Moving an application to {to_state.value} needs a reason.")

    if to_state in NEEDS_EVIDENCE and not screening_id:
        # Unreachable through the state table above, which only allows `shortlisted`
        # from `screened` — and belt-and-braces on purpose, because the thing being
        # protected is the guarantee that no claim about a person is made without
        # evidence, and a future edit to that table should not be able to lose it.
        return Refused(
            why=(
                f"Moving an application to {to_state.value} needs a completed screening to rest on."
            )
        )

    return Transition(
        to_state=to_state,
        reason=(reason or "").strip() or None,
        screening_id=screening_id,
        note=note,
    )


def _refusal(current: ApplicationState, to_state: ApplicationState, actor: Actor) -> str:
    """Why the move was refused, distinguishing "not you" from "not from here"."""
    reachable_by_anyone = {state for moves in _ALLOWED[current].values() for state in moves}
    if to_state in reachable_by_anyone:
        return (
            f"An application can be moved to {to_state.value} by someone else, "
            f"not by the {actor.mover.value}."
        )
    if to_state is ApplicationState.SHORTLISTED:
        return (
            "An application can only be shortlisted once it has been screened, so "
            "there is cited evidence behind the decision."
        )
    return f"An application cannot go from {current.value} to {to_state.value}."


def replay(
    events: list[tuple[ApplicationState | None, ApplicationState]],
) -> ApplicationState | None:
    """The state the log says an application is in.

    The definition of `Application.state` being a projection rather than a fact:
    if this and the column ever disagree, the column is wrong. Used by the tests to
    hold that line, and cheap enough to use in an audit view.
    """
    state: ApplicationState | None = None
    for from_state, to_state in events:
        if from_state != state:
            return None
        state = to_state
    return state
