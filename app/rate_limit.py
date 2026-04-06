import time
from collections import defaultdict
from fastapi import HTTPException, Request
from app.config import get_settings


class RateLimiter:
    def __init__(self):
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._window = 60.0  # 1 minute window

    def check(self, client_id: str):
        settings = get_settings()
        now = time.time()
        window_start = now - self._window

        self._requests[client_id] = [
            ts for ts in self._requests[client_id] if ts > window_start
        ]

        if len(self._requests[client_id]) >= settings.api_rate_limit:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Try again later.",
            )

        self._requests[client_id].append(now)


rate_limiter = RateLimiter()


async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    rate_limiter.check(client_ip)
    response = await call_next(request)
    return response
