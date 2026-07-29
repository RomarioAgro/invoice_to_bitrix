# Technical Context

## Стек

Python 3.12 в Docker, python-telegram-bot 22.3, httpx 0.28.1, openpyxl, pypdf, pdf2image, Tesseract rus, Xray 26.3.27, Docker Compose.

## Запуск

Точка входа `python app.py`; production — `docker compose up -d` в `/opt/bitrix-invoice-bot` на VPS `u24`.

## Интеграции

Telegram Bot API через SOCKS5 `127.0.0.1:10808`; endpoint Битрикс напрямую. Production-секреты хранятся в root-only `.env.production`.
