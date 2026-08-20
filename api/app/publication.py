"""Which publication moves a posting may make, and who may make them.

Pure: no session, no ORM, no HTTP. The same shape as `applications.py`,
`jobs.decide_retry` and `pipeline/ranking.py` — facts in, a decision out — so the whole
rule set is testable without a database.

**This is deliberately a different kind of state machine from `applications.py`, and the
difference is the point.** An application's state is a claim about a *person*, so it is
derived from an append-only log and nothing may be undone. A posting's status is an
**editorial** fact about a document the employer wrote: it says nothing about anybody, and
taking a posting down and putting it back up is an ordinary thing to do. So this one is
reversible and keeps no history — a log of "published, unpublished, published" would be
ceremony, and pretending otherwise would make the append-only rule look like a house style
rather than the specific answer it is to claims about people.

**One rule carries the security of every public route that comes after it.** Only an
`ADMIN` may publish. `SelfServiceRole` (`api/app/api/routes/auth.py`) lets anyone register
as a recruiter, so if a recruiter could publish, then anyone who can register can put a
posting on the public careers site. `ADMIN` is the one role that is deliberately not
self-selectable, which is exactly why it is the one that may publish.

The owner is not powerless: they draft, they edit, they close, and they may take their own
posting back down to a draft. What they may not do is decide that something appears on the
site under HireLens's name.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.models import JobStatus, Role


class Publisher(StrEnum):
    """Who is asking, in the terms these rules are written in.

    Not `Role`, for the reason `applications.Mover` gives: what matters for most of
    these is not "is a recruiter" but "owns *this* posting". A recruiter has no business
    unpublishing somebody else's job, and saying it with a role would imply they had.
    """

    OWNER = "owner"
    """Whoever owns the posting."""

    ADMIN = "admin"
    """An administrator, who owns every posting for this purpose and is the only one
    who may make a posting public."""

    @classmethod
    def of(cls, role: Role, *, is_owner: bool) -> Publisher | None:
        """Resolve a signed-in account against one posting, or `None` if it is neither.

        Admin is checked first and is *wider* than owner: an admin who happens to own
        the posting still gets the admin's powers, which is the opposite of the
        narrowing that `require_role` would produce.
        """
        if role is Role.ADMIN:
            return cls.ADMIN
        if is_owner:
            return cls.OWNER
        return None


@dataclass(frozen=True, slots=True)
class Refused:
    """A move that may not be made, and why — in words a user can be shown."""

    why: str


# From this status, this mover may reach these statuses. Read it as a table rather than
# as a chain: there is no ordering here, which is what "reversible" means.
_ALLOWED: dict[JobStatus, dict[Publisher, frozenset[JobStatus]]] = {
    JobStatus.DRAFT: {
        Publisher.ADMIN: frozenset({JobStatus.PUBLISHED, JobStatus.CLOSED}),
        # Not `PUBLISHED`. The whole slice rests on this one omission.
        Publisher.OWNER: frozenset({JobStatus.CLOSED}),
    },
    JobStatus.PUBLISHED: {
        Publisher.ADMIN: frozenset({JobStatus.DRAFT, JobStatus.CLOSED}),
        # An owner may take their own posting *down*, and that asymmetry is
        # deliberate: withdrawing something you wrote needs no gatekeeper, while
        # putting it in front of the public does.
        Publisher.OWNER: frozenset({JobStatus.DRAFT, JobStatus.CLOSED}),
    },
    JobStatus.CLOSED: {
        Publisher.ADMIN: frozenset({JobStatus.DRAFT, JobStatus.PUBLISHED}),
        Publisher.OWNER: frozenset({JobStatus.DRAFT}),
    },
}


def decide(
    *, current: JobStatus, target: JobStatus, publisher: Publisher | None
) -> JobStatus | Refused:
    """Approve a publication move, or refuse it with a reason.

    Refused rather than ignored, for the reason `applications.py` gives: a state machine
    that quietly drops a move it dislikes produces a system where nobody can tell a
    decision from a bug.
    """
    if publisher is None:
        return Refused("This posting is not yours to publish or withdraw.")

    if current is target:
        # Not an error, and not a no-op that lies about it either. Saying so lets a
        # caller answer 200 rather than 409 for a request that asks for what is
        # already true — the same instinct as a duplicate upload answering 200.
        return target

    allowed = _ALLOWED[current][publisher]
    if target in allowed:
        return target

    if target is JobStatus.PUBLISHED and publisher is Publisher.OWNER:
        return Refused(
            "Only an administrator can publish a posting to the public careers site. "
            "Anyone can register as a recruiter, so publishing is deliberately not "
            "something an account can grant itself."
        )
    return Refused(f"A posting cannot go from {current.value} to {target.value}.")


def is_public(status: JobStatus) -> bool:
    """May somebody who does not own this posting read it?

    One function rather than `status is PUBLISHED` written at each call site, because
    the answer is about to be asked by a public board, a public posting page and a
    signed-in candidate's list, and three copies of a security predicate is three
    chances to get it wrong once.
    """
    return status is JobStatus.PUBLISHED
