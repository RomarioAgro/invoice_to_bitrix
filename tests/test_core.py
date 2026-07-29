"""Small runnable checks for parsing, validation and Bitrix serialization."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from invoice_bot.bitrix import build_payload
from invoice_bot.models import Invoice
from invoice_bot.recognition import merge_lines, parse_fields


class CoreTests(unittest.TestCase):
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
            invoice.invoice_type = 329
            invoice.dds_article = 114830
            invoice.task_number = 659223
            self.assertEqual(invoice.errors(), [])
            payload = build_payload(invoice)
            self.assertEqual(payload["UF_INVOICE_SUM_TO_PAY"], 42780)
            self.assertEqual(payload["UF_INVOICE_FILES"][0]["EXT"], "xlsx")

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


if __name__ == "__main__":
    unittest.main()
