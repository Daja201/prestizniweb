# In-process sliding window rate limiter (no Redis required).
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock
from typing import Callable, Deque

from fastapi import Depends, HTTPException, Request

from app.core.deps import current_user

_windows: dict[str, Deque[float]] = defaultdict(deque)
_lock = Lock()


def rate_limit(name: str, limit: int, seconds: int) -> Callable:
    """Return a FastAPI dependency that enforces a sliding-window rate limit."""

    async def _dependency(
        request: Request,
        user=Depends(current_user),
    ) -> None:
        key = f"{name}:{user.id if user else request.client.host}"
        now = time.monotonic()
        cutoff = now - seconds

        with _lock:
            window = _windows[key]
            # Evict timestamps outside the window
            while window and window[0] < cutoff:
                window.popleft()

            if len(window) >= limit:
                raise HTTPException(
                    status_code=429,
                    detail=f"Příliš mnoho požadavků. Zkuste to znovu za chvíli.",
                )
            window.append(now)

    return _dependency