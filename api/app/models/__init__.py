"""SQLAlchemy models.

Everything is re-exported here so Alembic's autogenerate sees the full metadata
from a single import.
"""

from app.models.base import Base
from app.models.core import (
    Candidate,
    ExtractedProfileRow,
    LLMCallLog,
    Resume,
    ResumeStatus,
)
from app.models.matching import Job, JobRequirement, RequirementKind

__all__ = [
    "Base",
    "Candidate",
    "ExtractedProfileRow",
    "Job",
    "JobRequirement",
    "LLMCallLog",
    "RequirementKind",
    "Resume",
    "ResumeStatus",
]
