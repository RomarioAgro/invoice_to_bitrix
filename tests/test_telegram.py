"""Telegram rendering checks, runnable in the production image."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from invoice_bot.config import Choice
from invoice_bot.models import Invoice

try:
    from telegram.ext import ApplicationHandlerStop
    from invoice_bot.telegram_app import _request_field, access_guard, normalize_caption, receive_text, review_keyboard, summary
except ModuleNotFoundError:
    ApplicationHandlerStop = None
    _request_field = access_guard = normalize_caption = receive_text = summary = review_keyboard = None


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
    def _context(self, allowed=(42,)):
        settings = SimpleNamespace(allowed_user_ids=frozenset(allowed))
        return SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": SimpleNamespace(settings=settings)}))

    async def test_access_guard_allows_whitelisted_private_user(self) -> None:
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42), effective_chat=SimpleNamespace(type="private"),
            effective_message=SimpleNamespace(), callback_query=None,
        )
        await access_guard(update, self._context())

    async def test_access_guard_rejects_private_user_and_group(self) -> None:
        message = SimpleNamespace(reply_text=AsyncMock())
        denied = SimpleNamespace(
            effective_user=SimpleNamespace(id=99), effective_chat=SimpleNamespace(type="private"),
            effective_message=message, callback_query=None,
        )
        with self.assertRaises(ApplicationHandlerStop):
            await access_guard(denied, self._context())
        message.reply_text.assert_awaited_once_with("У вас нет доступа к этому боту")

        group = SimpleNamespace(
            effective_user=SimpleNamespace(id=42), effective_chat=SimpleNamespace(type="group"),
            effective_message=SimpleNamespace(reply_text=AsyncMock()), callback_query=None,
        )
        with self.assertRaises(ApplicationHandlerStop):
            await access_guard(group, self._context())
        group.effective_message.reply_text.assert_not_awaited()

    async def test_access_guard_rejects_callback(self) -> None:
        query = SimpleNamespace(answer=AsyncMock())
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=99), effective_chat=SimpleNamespace(type="private"),
            effective_message=None, callback_query=query,
        )
        with self.assertRaises(ApplicationHandlerStop):
            await access_guard(update, self._context())
        query.answer.assert_awaited_once_with("У вас нет доступа к этому боту", show_alert=True)

    async def test_missing_description_uses_required_prompt(self) -> None:
        message = SimpleNamespace(reply_text=AsyncMock())
        context = SimpleNamespace(user_data={})
        await _request_field(message, context, "description", SimpleNamespace())
        message.reply_text.assert_awaited_once_with("Описание счёта не указано. Введите описание счёта.")
        self.assertEqual(context.user_data["edit_field"], "description")

    async def test_payment_date_accepts_commas_and_stores_dots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invoice.pdf"
            path.write_bytes(b"%PDF-")
            invoice = Invoice(42, path, "pdf", datetime.now())
            runtime = SimpleNamespace(invoices={42: invoice})
            context = SimpleNamespace(
                application=SimpleNamespace(bot_data={"runtime": runtime}),
                user_data={"edit_field": "pay_before"},
            )
            message = SimpleNamespace(text="05,08,2026", reply_text=AsyncMock())
            update = SimpleNamespace(effective_user=SimpleNamespace(id=42), effective_message=message)
            with patch("invoice_bot.telegram_app._advance", new=AsyncMock()) as advance:
                await receive_text(update, context)
            self.assertEqual(invoice.pay_before, "05.08.2026")
            advance.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
