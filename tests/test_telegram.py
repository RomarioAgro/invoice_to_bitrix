"""Telegram rendering checks, runnable in the production image."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from invoice_bot.config import Choice
from invoice_bot.models import Invoice

try:
    from invoice_bot.telegram_app import _request_field, normalize_caption, review_keyboard, summary
except ModuleNotFoundError:
    _request_field = normalize_caption = summary = review_keyboard = None


@unittest.skipUnless(summary, "telegram dependency is installed in Docker")
class TelegramRenderingTests(unittest.TestCase):
    def test_caption_is_trimmed_without_changing_internal_text(self) -> None:
        self.assertEqual(normalize_caption("  Поставка\nпо договору  "), "Поставка\nпо договору")
        self.assertIsNone(normalize_caption(None))
        self.assertIsNone(normalize_caption(" \n\t "))

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
            self.assertIn("❗ <b>Номер задачи Битрикс: не указано</b>", text)
            labels = [[button.text for button in row] for row in review_keyboard(invoice).inline_keyboard]
            self.assertNotIn("Продолжить", sum(labels, []))


@unittest.skipUnless(_request_field, "telegram dependency is installed in Docker")
class TelegramDialogueTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_description_uses_required_prompt(self) -> None:
        message = SimpleNamespace(reply_text=AsyncMock())
        context = SimpleNamespace(user_data={})
        await _request_field(message, context, "description", SimpleNamespace())
        message.reply_text.assert_awaited_once_with("Описание счёта не указано. Введите описание счёта.")
        self.assertEqual(context.user_data["edit_field"], "description")


if __name__ == "__main__":
    unittest.main()
