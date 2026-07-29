"""Telegram long-polling dialogue for invoice review and sending."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest

from .bitrix import BitrixClient
from .config import Choice, Settings
from .models import DATE_RE, INN_RE, Invoice
from .recognition import FileRejected, extract_text, parse_fields, validate_file

logger = logging.getLogger(__name__)

FIELD_LABELS = {
    "number": "Номер счёта", "date": "Дата счёта", "customer_inn": "ИНН заказчика",
    "supplier_inn": "ИНН поставщика", "amount": "Сумма", "pay_before": "Оплатить до",
    "description": "Описание", "invoice_type": "Тип счёта", "dds_article": "Статья ДДС",
    "task_number": "Номер задачи Битрикс",
}


class BotRuntime:
    """In-memory active invoices and synchronization primitives."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.invoices: dict[int, Invoice] = {}
        self.user_locks: dict[int, asyncio.Lock] = {}
        self.capacity = settings.max_concurrent
        self.bitrix = BitrixClient(settings.bitrix_url, settings.bitrix_timeout)

    def lock(self, user_id: int) -> asyncio.Lock:
        """Return the stable lock for one Telegram user."""

        return self.user_locks.setdefault(user_id, asyncio.Lock())

    def delete(self, user_id: int) -> None:
        """Delete active state and its temporary directory."""

        invoice = self.invoices.pop(user_id, None)
        if invoice:
            shutil.rmtree(invoice.path.parent, ignore_errors=True)

    def try_acquire(self) -> bool:
        """Reserve technical capacity without creating a queue."""

        if self.capacity <= 0:
            return False
        self.capacity -= 1
        return True

    def release(self) -> None:
        """Return one technical-processing slot."""

        self.capacity += 1


def summary(invoice: Invoice, settings: Settings) -> str:
    """Render all Bitrix fields with human-readable labels."""

    types = {item.code: item.name for item in settings.invoice_types}
    articles = {item.code: item.name for item in settings.dds_articles}
    values = {
        "number": invoice.number, "date": invoice.date, "customer_inn": invoice.customer_inn,
        "supplier_inn": invoice.supplier_inn, "amount": invoice.amount,
        "pay_before": invoice.pay_before, "description": invoice.description,
        "invoice_type": types.get(invoice.invoice_type), "dds_article": articles.get(invoice.dds_article),
        "task_number": invoice.task_number,
    }
    return "Проверьте данные:\n" + "\n".join(
        f"{FIELD_LABELS[key]}: {value if value not in (None, '') else 'не указано'}" for key, value in values.items()
    )


def review_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Продолжить", callback_data="review:continue")],
        [InlineKeyboardButton("Изменить", callback_data="review:edit")],
        [InlineKeyboardButton("Отменить", callback_data="review:cancel")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show onboarding or current status without resetting state."""

    runtime: BotRuntime = context.application.bot_data["runtime"]
    if update.effective_user.id in runtime.invoices:
        await status(update, context)
        return
    await update.effective_message.reply_text(
        "Отправьте счёт PDF или XLSX до 5 МБ. PDF — не более 2 страниц."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show concise bot usage."""

    await update.effective_message.reply_text(
        "Команды: /start, /status, /cancel. Отправьте PDF/XLSX, проверьте поля и подтвердите отправку."
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show active invoice stage, retention and attempts."""

    runtime: BotRuntime = context.application.bot_data["runtime"]
    invoice = runtime.invoices.get(update.effective_user.id)
    if not invoice:
        await update.effective_message.reply_text("Активного счёта нет.")
        return
    expires = invoice.uploaded_at + timedelta(days=runtime.settings.retention_days)
    left = runtime.settings.max_attempts - invoice.attempts_used
    await update.effective_message.reply_text(
        f"Этап: {invoice.stage}\nНомер: {invoice.number or 'не указан'}\n"
        f"Загружен: {invoice.uploaded_at:%d.%m.%Y %H:%M}\nХранится до: {expires:%d.%m.%Y %H:%M}\n"
        f"Попыток отправки осталось: {left}"
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Immediately discard the current invoice."""

    runtime: BotRuntime = context.application.bot_data["runtime"]
    runtime.delete(update.effective_user.id)
    context.user_data.clear()
    message = update.callback_query.message if update.callback_query else update.effective_message
    if update.callback_query:
        await update.callback_query.answer()
    await message.reply_text("Обработка счёта отменена.")


async def receive_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Download, validate and recognize a new invoice without queuing."""

    runtime: BotRuntime = context.application.bot_data["runtime"]
    user_id = update.effective_user.id
    document = update.effective_message.document
    extension = Path(document.file_name or "").suffix.lower().lstrip(".")
    if user_id in runtime.invoices:
        await update.effective_message.reply_text("Сначала завершите текущий счёт или выполните /cancel.")
        return
    if not runtime.try_acquire():
        await update.effective_message.reply_text("Бот сейчас занят. Попробуйте отправить счёт позже")
        return
    directory = runtime.settings.temp_dir / f"{user_id}-{uuid4().hex}"
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / f"invoice.{extension or 'bin'}"
    try:
        telegram_file = await document.get_file()
        await telegram_file.download_to_drive(path)
        validate_file(path, extension, runtime.settings.max_file_size, runtime.settings.max_pdf_pages)
        invoice = Invoice(user_id, path, extension, datetime.now())
        runtime.invoices[user_id] = invoice
        await update.effective_message.reply_text("Файл принят, распознаю данные…")
        text = await asyncio.to_thread(
            extract_text, path, extension, runtime.settings.ocr_language, runtime.settings.ocr_dpi
        )
        parse_fields(invoice, text)
        invoice.stage = "проверка данных"
        await update.effective_message.reply_text(summary(invoice, runtime.settings), reply_markup=review_keyboard())
    except FileRejected as error:
        shutil.rmtree(directory, ignore_errors=True)
        await update.effective_message.reply_text(str(error))
    except Exception:
        logger.exception("Не удалось обработать входной файл user_id=%s", user_id)
        runtime.delete(user_id)
        shutil.rmtree(directory, ignore_errors=True)
        await update.effective_message.reply_text("Не удалось прочитать файл. Проверьте файл и отправьте его повторно.")
    finally:
        runtime.release()


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle review, edit, choice, confirmation and retry buttons."""

    query = update.callback_query
    runtime: BotRuntime = context.application.bot_data["runtime"]
    invoice = runtime.invoices.get(update.effective_user.id)
    if not invoice:
        await query.answer("Счёт уже не активен", show_alert=True)
        return
    data = query.data
    callback_id = f"{query.message.message_id}:{data}"
    if callback_id in invoice.processed_callbacks and data.startswith(("choose:", "send:")):
        await query.answer("Этот выбор уже обработан")
        return
    if data == "review:cancel":
        await cancel(update, context)
        return
    if data == "review:edit":
        buttons = [[InlineKeyboardButton(label, callback_data=f"field:{name}")] for name, label in FIELD_LABELS.items()]
        await query.answer()
        await query.edit_message_reply_markup(InlineKeyboardMarkup(buttons))
        return
    if data.startswith("field:"):
        field = data.split(":", 1)[1]
        if field in {"invoice_type", "dds_article"}:
            await _show_choices(query, field, runtime.settings)
        else:
            context.user_data["edit_field"] = field
            await query.answer()
            await query.edit_message_reply_markup(None)
            await query.message.reply_text(f"Введите новое значение: {FIELD_LABELS[field]}")
        return
    if data.startswith("choose:"):
        _, field, key = data.split(":", 2)
        choices = runtime.settings.invoice_types if field == "invoice_type" else runtime.settings.dds_articles
        choice = next((item for item in choices if item.key == key), None)
        if not choice:
            await query.answer("Вариант больше недоступен", show_alert=True)
            return
        setattr(invoice, field, choice.code)
        invoice.processed_callbacks.add(callback_id)
        invoice.attempts_used = 0
        await query.answer()
        try:
            await query.edit_message_reply_markup(None)
        except Exception:
            logger.exception("Не удалось удалить устаревшую клавиатуру user_id=%s", invoice.user_id)
        await query.message.reply_text(summary(invoice, runtime.settings), reply_markup=review_keyboard())
        return
    if data == "review:continue":
        await query.answer()
        await query.edit_message_reply_markup(None)
        missing = invoice.missing()
        if missing:
            await _request_field(query.message, context, missing[0], runtime.settings)
        else:
            invoice.stage = "подтверждение"
            await query.message.reply_text(
                summary(invoice, runtime.settings),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отправить", callback_data="send:now")], [InlineKeyboardButton("Изменить", callback_data="review:edit")], [InlineKeyboardButton("Отменить", callback_data="review:cancel")]]),
            )
        return
    if data in {"send:now", "send:retry"}:
        invoice.processed_callbacks.add(callback_id)
        await query.answer()
        await query.edit_message_reply_markup(None)
        await _send_invoice(query.message, invoice, runtime)


async def _show_choices(query, field: str, settings: Settings) -> None:
    choices = settings.invoice_types if field == "invoice_type" else settings.dds_articles
    keyboard = [[InlineKeyboardButton(item.name, callback_data=f"choose:{field}:{item.key}")] for item in choices]
    await query.answer()
    await query.edit_message_reply_markup(InlineKeyboardMarkup(keyboard))


async def _request_field(message, context: ContextTypes.DEFAULT_TYPE, field: str, settings: Settings) -> None:
    if field in {"invoice_type", "dds_article"}:
        choices = settings.invoice_types if field == "invoice_type" else settings.dds_articles
        keyboard = [[InlineKeyboardButton(item.name, callback_data=f"choose:{field}:{item.key}")] for item in choices]
        await message.reply_text(f"Выберите: {FIELD_LABELS[field]}", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        context.user_data["edit_field"] = field
        await message.reply_text(f"Введите: {FIELD_LABELS[field]}")


async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Validate and store a manually entered field."""

    runtime: BotRuntime = context.application.bot_data["runtime"]
    invoice = runtime.invoices.get(update.effective_user.id)
    field = context.user_data.get("edit_field")
    if not invoice or not field:
        await update.effective_message.reply_text("Отправьте PDF или XLSX либо используйте /status.")
        return
    value = update.effective_message.text.strip()
    error = _input_error(field, value)
    if error:
        await update.effective_message.reply_text(error)
        return
    setattr(invoice, field, int(value) if field == "task_number" else value.replace(",", ".") if field == "amount" else value)
    invoice.attempts_used = 0
    context.user_data.pop("edit_field", None)
    invoice.stage = "проверка данных"
    await update.effective_message.reply_text(summary(invoice, runtime.settings), reply_markup=review_keyboard())


def _input_error(field: str, value: str) -> str | None:
    if field in {"customer_inn", "supplier_inn"} and not INN_RE.fullmatch(value):
        return "Введите ИНН из 10 или 12 цифр."
    if field in {"date", "pay_before"} and value and not DATE_RE.fullmatch(value):
        return "Введите дату в формате ДД.ММ.ГГГГ."
    if field == "task_number" and (not value.isdigit() or int(value) <= 0):
        return "Введите положительный номер задачи."
    if field == "amount" and not re.fullmatch(r"\d+(?:[.,]\d{1,2})?", value):
        return "Введите положительную сумму, например 42780.00."
    if not value and field != "pay_before":
        return "Значение не должно быть пустым."
    return None


async def _send_invoice(message, invoice: Invoice, runtime: BotRuntime) -> None:
    errors = invoice.errors()
    if errors:
        invoice.stage = "проверка данных"
        await message.reply_text("Исправьте данные:\n" + "\n".join(errors), reply_markup=review_keyboard())
        return
    if invoice.sending:
        await message.reply_text("Отправка уже выполняется.")
        return
    if not runtime.try_acquire():
        await message.reply_text("Бот сейчас занят. Нажмите «Повторить» позже.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Повторить", callback_data="send:retry")]]))
        return
    invoice.sending = True
    invoice.stage = "отправляется в Битрикс"
    try:
        async with runtime.lock(invoice.user_id):
            result = await runtime.bitrix.send(invoice)
        if result.success:
            logger.info("Bitrix success user_id=%s status=%s response=%s", invoice.user_id, result.status_code, result.response_text)
            text = "Счёт успешно отправлен в Битрикс"
            if result.link and result.link.startswith(("http://", "https://")):
                text += f"\n{result.link}"
            runtime.delete(invoice.user_id)
            try:
                await message.reply_text(text)
            except Exception:
                logger.exception("Не удалось доставить сообщение об успехе user_id=%s", invoice.user_id)
            return
        if result.connection_error:
            text = "Не удалось связаться с Битрикс. Попытка не израсходована."
        else:
            invoice.attempts_used += 1
            logger.warning("Bitrix HTTP error user_id=%s status=%s response=%s", invoice.user_id, result.status_code, result.response_text)
            text = f"Битрикс вернул ошибку HTTP {result.status_code}."
        left = runtime.settings.max_attempts - invoice.attempts_used
        invoice.stage = "ошибка отправки"
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("Повторить", callback_data="send:retry")], [InlineKeyboardButton("Изменить", callback_data="review:edit")], [InlineKeyboardButton("Отменить", callback_data="review:cancel")]]) if left > 0 else InlineKeyboardMarkup([[InlineKeyboardButton("Изменить", callback_data="review:edit")], [InlineKeyboardButton("Отменить", callback_data="review:cancel")]])
        await message.reply_text(f"{text}\nПопыток осталось: {left}", reply_markup=markup)
    finally:
        invoice.sending = False
        runtime.release()


async def cleanup(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete invoices and orphan directories older than retention."""

    runtime: BotRuntime = context.application.bot_data["runtime"]
    cutoff = datetime.now() - timedelta(days=runtime.settings.retention_days)
    for user_id, invoice in list(runtime.invoices.items()):
        if invoice.uploaded_at < cutoff and not invoice.sending:
            runtime.delete(user_id)
    if runtime.settings.temp_dir.exists():
        for path in runtime.settings.temp_dir.iterdir():
            if path.is_dir() and datetime.fromtimestamp(path.stat().st_mtime) < cutoff:
                shutil.rmtree(path, ignore_errors=True)


def build_application(settings: Settings) -> Application:
    """Build a long-polling application with Telegram-only SOCKS5 proxy."""

    request = HTTPXRequest(proxy=settings.telegram_proxy_url, connection_pool_size=20)
    application = Application.builder().token(settings.telegram_token).request(request).get_updates_request(request).build()
    runtime = BotRuntime(settings)
    application.bot_data["runtime"] = runtime
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CallbackQueryHandler(callback))
    application.add_handler(MessageHandler(filters.Document.ALL, receive_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text))
    hours, minutes = map(int, settings.cleanup_time.split(":"))
    application.job_queue.run_daily(cleanup, datetime.now().replace(hour=hours, minute=minutes, second=0, microsecond=0).timetz())

    async def post_init(app: Application) -> None:
        settings.temp_dir.mkdir(parents=True, exist_ok=True)
        await app.bot.delete_webhook(drop_pending_updates=False)
        await app.bot.set_my_commands([BotCommand("start", "Начать"), BotCommand("help", "Помощь"), BotCommand("status", "Статус"), BotCommand("cancel", "Отменить")])

    async def post_shutdown(app: Application) -> None:
        await runtime.bitrix.close()

    application.post_init = post_init
    application.post_shutdown = post_shutdown
    return application
