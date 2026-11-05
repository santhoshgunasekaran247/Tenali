import asyncio
import os
import threading
import time
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from app.services.tenant_context import TenantBoundary


class TenantConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_database_checks_overlap_without_blocking_event_loop(self):
        app = FastAPI()

        @app.get("/auth/probe")
        async def probe():
            return {"ok": True}

        app.add_middleware(TenantBoundary)
        loop_thread = threading.get_ident()
        threads = []
        active = 0
        peak = 0
        lock = threading.Lock()

        def slow_host_lookup(_db, _request):
            nonlocal active, peak
            with lock:
                threads.append(threading.get_ident())
                active += 1
                peak = max(peak, active)
            time.sleep(0.1)
            with lock:
                active -= 1
            return None

        with patch.dict(os.environ, {"TENALI_ENV": "development"}), \
                patch("app.services.tenant_context.SessionLocal"), \
                patch("app.services.tenant_context.host_company", side_effect=slow_host_lookup):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
                responses = await asyncio.gather(*(client.get("/auth/probe") for _ in range(4)))
        self.assertTrue(all(response.status_code == 200 for response in responses))
        self.assertGreater(peak, 1, "Independent request checks must not be serialized")
        self.assertNotIn(loop_thread, threads, "Synchronous database work must not run on the event-loop thread")
