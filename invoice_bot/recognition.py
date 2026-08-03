"""Local PDF/XLSX validation and invoice field extraction."""

from __future__ import annotations

import re
import zipfile
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from .models import Invoice

DATE_PATTERN = r"\d{1,2}(?:[./-]\d{1,2}[./-]|\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+)\d{4}"
MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}


class FileRejected(ValueError):
    """Raised with a safe user-facing file rejection message."""


def validate_file(path: Path, extension: str, max_size: int, max_pages: int) -> None:
    """Validate size, extension, magic and PDF page count."""

    if extension not in {"pdf", "xlsx"}:
        raise FileRejected("Поддерживаются только файлы PDF и XLSX.")
    if path.stat().st_size > max_size:
        raise FileRejected("Размер файла превышает 5 МБ.")
    try:
        if extension == "pdf":
            from pypdf import PdfReader

            if path.read_bytes()[:5] != b"%PDF-":
                raise ValueError
            if len(PdfReader(path).pages) > max_pages:
                raise FileRejected("PDF должен содержать не более 2 страниц.")
        else:
            with zipfile.ZipFile(path) as archive:
                if "[Content_Types].xml" not in archive.namelist():
                    raise ValueError
    except FileRejected:
        raise
    except Exception as error:
        raise FileRejected("Не удалось прочитать файл. Проверьте файл и отправьте его повторно.") from error


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("ё", "е").lower()).strip()


def merge_lines(text_layer: str, ocr_text: str) -> str:
    """Merge sources, dropping OCR lines with >=0.90 similarity and equal numbers."""

    text_lines = [line.strip() for line in text_layer.splitlines() if line.strip()]
    normalized = [_normalized(line) for line in text_lines]
    for line in (line.strip() for line in ocr_text.splitlines() if line.strip()):
        candidate = _normalized(line)
        numbers = re.findall(r"\d+", candidate)
        duplicate = any(
            re.findall(r"\d+", known) == numbers
            and SequenceMatcher(None, known, candidate).ratio() >= 0.90
            for known in normalized
        )
        if not duplicate:
            text_lines.append(line)
            normalized.append(candidate)
    return "\n".join(text_lines)


def extract_text(path: Path, extension: str, language: str, dpi: int) -> str:
    """Read displayed XLSX cells or combine PDF text layer with OCR."""

    if extension == "xlsx":
        import openpyxl

        workbook = openpyxl.load_workbook(path, data_only=True, read_only=True, keep_links=False)
        try:
            return "\n".join(
                str(cell)
                for sheet in workbook.worksheets
                for row in sheet.iter_rows(values_only=True)
                for cell in row if cell not in (None, "")
            )
        finally:
            workbook.close()
    import pytesseract
    from pdf2image import convert_from_path
    from pypdf import PdfReader

    reader = PdfReader(path)
    layers = [page.extract_text() or "" for page in reader.pages]
    images = convert_from_path(path, dpi=dpi, first_page=1, last_page=len(reader.pages))
    return "\n".join(
        merge_lines(layer, pytesseract.image_to_string(image, lang=language))
        for layer, image in zip(layers, images)
    )


def parse_fields(invoice: Invoice, text: str) -> Invoice:
    """Populate fields found by conservative Russian invoice patterns."""

    flat = re.sub(r"[\u00a0\s]+", " ", text)
    number = re.search(r"\bсч[её]т(?:\s+на\s+оплату)?\s*№\s*([\wА-Яа-яЁё./-]+)", flat, re.I) or re.search(
        r"\bсч[её]т\s+на\s+оплату\s+([\wА-Яа-яЁё./-]+)", flat, re.I
    )
    date = re.search(rf"(?:от\s*)?({DATE_PATTERN})", flat, re.I)
    inns = list(dict.fromkeys(re.findall(r"\bИНН(?:\s*/\s*КПП)?\s*[:№]?\s*(\d{10}|\d{12})\b", flat, re.I)))
    amount = re.search(
        r"(?:всего\s+к\s+оплате|к\s+оплате|итого\s+с\s+ндс|на\s+сумму)\D{0,30}([\d\s\u00a0]+[,.]\d{2})",
        flat,
        re.I,
    ) or re.search(r"итого\D{0,30}([\d\s\u00a0]+[,.]\d{2})", flat, re.I)
    pay_before = re.search(rf"(?:оплатить\s+до|срок\s+оплаты)\D{{0,20}}({DATE_PATTERN})", flat, re.I)
    if number:
        invoice.number = number.group(1)
    if date:
        invoice.date = _date(date.group(1))
    if inns:
        invoice.supplier_inn = inns[0]
    if len(inns) > 1:
        invoice.customer_inn = inns[1]
    if amount:
        invoice.amount = amount.group(1).replace(" ", "").replace("\u00a0", "").replace(",", ".")
    if pay_before:
        invoice.pay_before = _date(pay_before.group(1))
    return invoice


def _date(value: str) -> str:
    words = value.lower().split()
    if len(words) == 3 and words[1] in MONTHS:
        try:
            return datetime(int(words[2]), MONTHS[words[1]], int(words[0])).strftime("%d.%m.%Y")
        except ValueError:
            return value
    for separator in (".", "/", "-"):
        try:
            return datetime.strptime(value, f"%d{separator}%m{separator}%Y").strftime("%d.%m.%Y")
        except ValueError:
            pass
    return value
