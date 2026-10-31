"""Track queued and active work in the local, single-process API server."""

from threading import RLock

_lock = RLock()
_active: set[str] = set()


def reserve(job_id: str) -> bool:
    with _lock:
        if job_id in _active:
            return False
        _active.add(job_id)
        return True


def release(job_id: str) -> None:
    with _lock:
        _active.discard(job_id)


def is_active(job_id: str) -> bool:
    with _lock:
        return job_id in _active
