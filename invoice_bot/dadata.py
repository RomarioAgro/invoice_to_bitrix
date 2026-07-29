"""Direct, failure-tolerant DaData organization lookup."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def organization_name(payload: object, inn: str) -> str | None:
    """Return a matching organization's preferred display name."""

    if not isinstance(payload, dict) or not isinstance(payload.get("suggestions"), list):
        return None
    for item in payload["suggestions"]:
        if not isinstance(item, dict) or not isinstance(item.get("data"), dict):
            continue
        data = item["data"]
        if str(data.get("inn", "")) != inn:
            continue
        names = data.get("name") if isinstance(data.get("name"), dict) else {}
        name = names.get("short_with_opf") or item.get("value") or names.get("full_with_opf")
        return str(name) if name else None
    return None


class DaDataClient:
    """Look up organizations directly, never through Telegram's proxy."""

    def __init__(self, url: str, api_key: str, timeout: float, transport=None) -> None:
        import httpx

        self.client = httpx.AsyncClient(
            timeout=timeout,
            trust_env=False,
            headers={"Authorization": f"Token {api_key}", "Accept": "application/json"},
            transport=transport,
        )
        self.url = url

    async def close(self) -> None:
        """Close the HTTP connection pool."""

        await self.client.aclose()

    async def find_name(self, inn: str) -> str | None:
        """Return a matching name, degrading safely on any service failure."""

        import httpx

        try:
            response = await self.client.post(self.url, json={"query": inn, "branch_type": "MAIN", "count": 1})
            if not response.is_success:
                logger.warning("DaData HTTP error inn=%s status=%s", inn, response.status_code)
                return None
            return organization_name(response.json(), inn)
        except (httpx.HTTPError, ValueError) as error:
            logger.warning("DaData lookup failed inn=%s error=%s", inn, type(error).__name__)
            return None
