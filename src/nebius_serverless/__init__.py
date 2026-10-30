"""Cloud Jobs client for Nebius Serverless AI Jobs.

Constructing a ``Job`` does not import the Nebius SDK. The SDK is
imported on the call that resolves a profile or contacts Nebius.
"""

from .errors import (
    AccessError,
    CapacityError,
    Error,
    KeyConflict,
    SubmissionUncertain,
    TransportError,
    UnsupportedFeature,
    ValidationError,
    WaitTimeout,
)
from .job import Job
from .run import Run, jobs

__version__ = "0.0.1"

__all__ = [
    "AccessError",
    "CapacityError",
    "Error",
    "Job",
    "KeyConflict",
    "Run",
    "SubmissionUncertain",
    "TransportError",
    "UnsupportedFeature",
    "ValidationError",
    "WaitTimeout",
    "jobs",
]
