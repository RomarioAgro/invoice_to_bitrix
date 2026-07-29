"""Telegram rendering checks, runnable in the production image."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from invoice_bot.config import Choice
from invoice_bot.models import Invoice

try:
    from invoice_bot.telegram_app import review_keyboard, summary
except ModuleNotFoundError:
    summary = review_keyboard = None


@unittest.skipUnless(summary, "telegram dependency is installed in Docker")
class TelegramRenderingTests(unittest.TestCase):
    def test_summary_escapes_values_and_marks_only_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invoice.xlsx"
            path.write_bytes(b"test")
            invoice = Invoice(1, path, "xlsx", datetime.now(), number="<b>7</b>")
            settings = SimpleNamespace(
                invoice_types=(Choice("type", 329, "Оборудование"),),
                dds_articles=(Choice("dds", 114830, "Оргтехника"),),
            )
            text = summary(invoice, settings)
            self.assertIn("&lt;b&gt;7&lt;/b&gt;", text)
            self.assertIn("❗ <b>Дата счёта: не указано</b>", text)
            self.assertIn("Номер задачи Битрикс: не указано (необязательно)", text)
            self.assertNotIn("❗ <b>Номер задачи", text)
            labels = [[button.text for button in row] for row in review_keyboard(invoice).inline_keyboard]
            self.assertNotIn("Продолжить", sum(labels, []))


if __name__ == "__main__":
    unittest.main()
