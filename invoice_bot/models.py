"""Invoice state and validation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
INN_RE = re.compile(r"^\d{10}(?:\d{2})?$")


@dataclass
class Invoice:
    """One user's active invoice."""

    user_id: int
    path: Path
    extension: str
    uploaded_at: datetime
    number: str | None = None
    date: str | None = None
    customer_inn: str | None = None
    supplier_inn: str | None = None
    amount: str | None = None
    pay_before: str | None = None
    description: str | None = None
    invoice_type: int | None = None
    dds_article: int | None = None
    task_number: int | None = None
    attempts_used: int = 0
    stage: str = "распознавание"
    sending: bool = False
    processed_callbacks: set[str] = field(default_factory=set)

    def missing(self) -> list[str]:
        """Return missing required form fields in dialogue order."""

        fields = (
            "number", "date", "customer_inn", "supplier_inn", "amount",
            "description", "invoice_type", "dds_article", "task_number",
        )
        return [name for name in fields if getattr(self, name) in (None, "")]

    def errors(self) -> list[str]:
        """Validate all fields required by Bitrix."""

        errors = [f"Не заполнено: {name}" for name in self.missing()]
        for name in ("date", "pay_before"):
            value = getattr(self, name)
            if value and not DATE_RE.fullmatch(value):
                errors.append(f"Некорректная дата: {name}")
        for name in ("customer_inn", "supplier_inn"):
            value = getattr(self, name)
            if value and not INN_RE.fullmatch(value):
                errors.append(f"Некорректный ИНН: {name}")
        if self.customer_inn and self.customer_inn == self.supplier_inn:
            errors.append("ИНН заказчика и поставщика должны различаться")
        try:
            if self.amount is not None and Decimal(self.amount.replace(",", ".")) <= 0:
                errors.append("Сумма должна быть положительной")
        except InvalidOperation:
            errors.append("Некорректная сумма")
        if self.task_number is not None and self.task_number <= 0:
            errors.append("Номер задачи должен быть положительным")
        if not self.path.is_file():
            errors.append("Исходный файл отсутствует")
        return errors

    def bitrix_amount(self) -> int:
        """Convert rubles to Bitrix integer field using ordinary rounding."""

        return int(Decimal(self.amount.replace(",", ".")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
