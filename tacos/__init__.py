"""T.A.C.O.S. — Talent Acquisition Career Operating System.

This package is intentionally optional. The production watcher must continue
working if T.A.C.O.S. cannot be imported or score a job.
"""

from .scoring import score_job

__all__ = ["score_job"]
