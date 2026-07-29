"""Small runnable checks for parsing, validation and Bitrix serialization."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

try:
    import httpx
except ModuleNotFoundError:
    httpx = None

from invoice_bot.bitrix import BitrixClient, build_payload
from invoice_bot.config import load_settings
from invoice_bot.dadata import organization_name
from invoice_bot.models import Invoice
from invoice_bot.recognition import merge_lines, parse_fields


class CoreTests(unittest.IsolatedAsyncioTestCase):
    def test_dadata_secrets_load_from_environment(self) -> None:
        env = {
            "TELEGRAM_BOT_TOKEN": "telegram", "TELEGRAM_PROXY_URL": "socks5://127.0.0.1:10808",
            "BITRIX_ENDPOINT_URL": "https://bitrix.invalid", "DADATA_API_KEY": "api",
            "DADATA_SECRET_KEY": "secret",
        }
        with patch.dict("os.environ", env, clear=True):
            settings = load_settings("config.example.ini")
        self.assertEqual(settings.dadata_api_key, "api")
        self.assertEqual(settings.dadata_secret_key, "secret")

    def test_merge_removes_similar_line_with_same_numbers(self) -> None:
        merged = merge_lines("ИНН 1234567890", "инн  1234567890\nКПП 123456789")
        self.assertEqual(merged.count("1234567890"), 1)
        self.assertIn("КПП", merged)

    def test_parse_and_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invoice.xlsx"
            path.write_bytes(b"test")
            invoice = Invoice(1, path, "xlsx", datetime.now())
            parse_fields(
                invoice,
                "Счет на оплату № ЦТ-1934 от 27.07.2026\n"
                "Поставщик ИНН 434548571181 Покупатель ИНН 4345268662\n"
                "Всего к оплате 42 780,00",
            )
            invoice.description = "Оборудование"
            invoice.pay_before = "30.07.2026"
            invoice.invoice_type = 329
            invoice.dds_article = 114830
            invoice.task_number = 659223
            self.assertEqual(invoice.errors(), [])
            payload = build_payload(invoice)
            self.assertEqual(payload["UF_INVOICE_SUM_TO_PAY"], 42780)
            self.assertEqual(payload["UF_INVOICE_FILES"][0]["EXT"], "xlsx")

    def test_task_is_required_and_sent_as_integer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invoice.xlsx"
            path.write_bytes(b"test")
            invoice = Invoice(
                1, path, "xlsx", datetime.now(), number="7", date="27.07.2026",
                customer_inn="1234567890", supplier_inn="123456789012", amount="100",
                pay_before="30.07.2026", description="Оборудование", invoice_type=329,
                dds_article=114830,
            )
            self.assertIn("Не заполнено: task_number", invoice.errors())
            invoice.task_number = 42
            self.assertEqual(invoice.errors(), [])
            self.assertEqual(build_payload(invoice)["UF_SEARCH_TASK"], 42)

    @unittest.skipUnless(httpx, "httpx dependency is installed in Docker")
    async def test_nested_deal_link_is_returned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invoice.pdf"
            path.write_bytes(b"%PDF-")
            invoice = Invoice(1, path, "pdf", datetime.now(), amount="1")
            client = BitrixClient("https://bitrix.invalid", 1)
            client.client.post = AsyncMock(
                return_value=httpx.Response(200, json={"result": {"link_deal": "https://crm.invalid/deal/42/"}})
            )
            try:
                result = await client.send(invoice)
            finally:
                await client.close()
            self.assertEqual(result.link, "https://crm.invalid/deal/42/")

    def test_missing_fields_follow_automatic_question_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invoice.xlsx"
            path.write_bytes(b"test")
            invoice = Invoice(1, path, "xlsx", datetime.now())
            self.assertEqual(
                invoice.missing(),
                ["number", "date", "customer_inn", "supplier_inn", "amount", "pay_before", "description", "invoice_type", "dds_article", "task_number"],
            )

    def test_dadata_name_requires_exact_inn(self) -> None:
        payload = {"suggestions": [{"value": "ООО Полное", "data": {"inn": "1234567890", "name": {"short_with_opf": "ООО Короткое"}}}]}
        self.assertEqual(organization_name(payload, "1234567890"), "ООО Короткое")
        self.assertIsNone(organization_name(payload, "0000000000"))

    def test_same_inn_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invoice.pdf"
            path.write_bytes(b"%PDF-")
            invoice = Invoice(
                1, path, "pdf", datetime.now(), number="1", date="01.01.2026",
                customer_inn="1234567890", supplier_inn="1234567890", amount="1",
                description="x", invoice_type=1, dds_article=1, task_number=1,
            )
            self.assertIn("ИНН заказчика и поставщика должны различаться", invoice.errors())

    def test_russian_month_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invoice.xlsx"
            path.write_bytes(b"test")
            invoice = parse_fields(
                Invoice(1, path, "xlsx", datetime.now()),
                "Счёт № 7 от 27 июля 2026, оплатить до 5 августа 2026",
            )
            self.assertEqual(invoice.date, "27.07.2026")
            self.assertEqual(invoice.pay_before, "05.08.2026")

    def test_description_is_not_extracted_from_document_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invoice.xlsx"
            path.write_bytes(b"test")
            invoice = parse_fields(
                Invoice(1, path, "xlsx", datetime.now()),
                "Описание: это значение не должно извлекаться из документа",
            )
            self.assertIsNone(invoice.description)


if __name__ == "__main__":
    unittest.main()
