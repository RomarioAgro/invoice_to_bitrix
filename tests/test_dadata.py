"""DaData HTTP behavior checks, runnable in the production image."""

from __future__ import annotations

import unittest

try:
    import httpx
except ModuleNotFoundError:
    httpx = None

from invoice_bot.dadata import DaDataClient


@unittest.skipUnless(httpx, "httpx dependency is installed in Docker")
class DaDataClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_error_degrades_to_missing_name(self) -> None:
        client = DaDataClient(
            "https://dadata.invalid", "secret", 1,
            transport=httpx.MockTransport(lambda request: httpx.Response(503)),
        )
        try:
            self.assertIsNone(await client.find_name("1234567890"))
        finally:
            await client.close()

    async def test_matching_response_returns_name(self) -> None:
        def handler(request):
            return httpx.Response(200, json={"suggestions": [{"value": "ООО Тест", "data": {"inn": "1234567890"}}]})

        client = DaDataClient("https://dadata.invalid", "secret", 1, transport=httpx.MockTransport(handler))
        try:
            self.assertEqual(await client.find_name("1234567890"), "ООО Тест")
        finally:
            await client.close()


if __name__ == "__main__":
    unittest.main()
