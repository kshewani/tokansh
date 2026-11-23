"""Synchronous test bridge for the local FastAPI test environment.

The installed AnyIO worker portal and Starlette TestClient both block in this
environment.  This keeps the existing synchronous tests while using HTTPX's
ASGI transport on a dedicated asyncio loop with explicit lifespan handling.
"""
import asyncio

import anyio.to_thread
import httpx


async def _run_sync_inline(func, *args, **kwargs):
    """Test-only replacement for AnyIO's unavailable worker pool."""
    # FastAPI passes AnyIO's CapacityLimiter when closing sync context
    # managers.  It is a worker-pool concern and must not reach the target.
    kwargs.pop("limiter", None)
    kwargs.pop("cancellable", None)
    kwargs.pop("abandon_on_cancel", None)
    return func(*args, **kwargs)


class SyncASGIClient:
    def __init__(self, app, base_url="http://testserver"):
        self.app = app
        self.base_url = base_url
        self._previous_run_sync = None

    async def _request(self, method, url, **kwargs):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app),
            base_url=self.base_url,
        ) as client:
            return await client.request(method, url, **kwargs)

    def request(self, method, url, **kwargs):
        return asyncio.run(self._request(method, url, **kwargs))

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self.request("PUT", url, **kwargs)

    def patch(self, url, **kwargs):
        return self.request("PATCH", url, **kwargs)

    def delete(self, url, **kwargs):
        return self.request("DELETE", url, **kwargs)

    def options(self, url, **kwargs):
        return self.request("OPTIONS", url, **kwargs)

    def __enter__(self):
        self._previous_run_sync = anyio.to_thread.run_sync
        anyio.to_thread.run_sync = _run_sync_inline
        try:
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            # ASGITransport intentionally does not manage lifespan.  TokANSH's
            # lifespan has no startup work; fixture teardown closes its clients
            # and database explicitly.  Avoid holding an async context across
            # the independent asyncio.run() calls used by sync tests.
            pass
        finally:
            if self._previous_run_sync is not None:
                anyio.to_thread.run_sync = self._previous_run_sync
        return False
