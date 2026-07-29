"""Direct, proxy-free Bitrix HTTP client."""

from __future__ import annotations

import base64
from dataclasses import dataclass

from .models import Invoice


@dataclass(frozen=True)
class BitrixResult:
    """Classified Bitrix response."""

    success: bool
    status_code: int | None = None
    link: str | None = None
    connection_error: bool = False
    response_text: str = ""


class BitrixClient:
    """Send invoices directly without environment proxy inheritance."""

    def __init__(self, url: str, timeout: float) -> None:
        import httpx

        self.url = url
        self.client = httpx.AsyncClient(timeout=timeout, trust_env=False)

    async def close(self) -> None:
        """Close the HTTP connection pool."""

        await self.client.aclose()

    async def send(self, invoice: Invoice) -> BitrixResult:
        """Send one request; any 2xx response is success."""

        import httpx

        payload = build_payload(invoice)
        try:
            response = await self.client.post(self.url, json=payload)
        except (httpx.TimeoutException, httpx.NetworkError):
            return BitrixResult(False, connection_error=True)
        text = response.text[:4000]
        link = None
        if response.is_success:
            try:
                data = response.json()
                link = data.get("url") or data.get("link") if isinstance(data, dict) else None
            except ValueError:
                pass
        return BitrixResult(response.is_success, response.status_code, link, response_text=text)


def build_payload(invoice: Invoice) -> dict:
    """Serialize the validated invoice and original file."""

    data = base64.b64encode(invoice.path.read_bytes()).decode("ascii")
    payload = {
        "TITLE": f"Счёт {invoice.number}",
        "UF_INVOICE_TYPE": invoice.invoice_type,
        "UF_INVOICE_NUM": invoice.number,
        "UF_INVOICE_DATE": invoice.date,
        "UF_INVOICE_FROM_COMPANY": invoice.customer_inn,
        "UF_INVOICE_TO_COMPANY": invoice.supplier_inn,
        "UF_INVOICE_SUM_TO_PAY": invoice.bitrix_amount(),
        "UF_INVOICE_PAY_BEFORE": invoice.pay_before or "",
        "UF_INVOICE_DESCRIPTION": invoice.description,
        "UF_ARTICLES_DDS": invoice.dds_article,
        "UF_INVOICE_FILES": [{"DATA": data, "EXT": invoice.extension}],
    }
    if invoice.task_number is not None:
        payload["UF_SEARCH_TASK"] = invoice.task_number
    return payload
