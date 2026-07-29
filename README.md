# Telegram-бот счетов для Битрикс

Бот принимает PDF/XLSX, локально извлекает реквизиты, автоматически запрашивает недостающие обязательные поля и отправляет исходный файл с полями в Битрикс. Для корректных ИНН бот справочно получает названия организаций через DaData. Состояние хранится только в памяти; после перезапуска диалоги не восстанавливаются, оставшиеся файлы удаляет ежедневная очистка.

## Архитектура

- `python-telegram-bot` long polling; его `HTTPXRequest` использует только SOCKS5 из `TELEGRAM_PROXY_URL`.
- Отдельный `httpx.AsyncClient(trust_env=False)` отправляет запросы Битрикс напрямую и не наследует proxy.
- Ещё один прямой `httpx.AsyncClient(trust_env=False)` обращается к DaData; ошибки сервиса не блокируют диалог и отправку.
- Для каждого пользователя допускается один `Invoice`; отправка защищена пользовательским lock, распознавание и HTTP-запросы — общим семафором.
- XLSX читает `openpyxl` без внешних ссылок. PDF: `pypdf` + `pdf2image` 300 DPI + Tesseract `rus`.
- OCR-строка считается дублем при сходстве `difflib.SequenceMatcher >= 0.90` и полном совпадении числовых последовательностей. Значение текстового слоя остаётся первым.
- Даты распознаются как числа (`27.07.2026`) и с русским месяцем (`27 июля 2026`), затем приводятся к `dd.mm.YYYY`.
- Callback выбора одноразовый: после сохранения клавиатура удаляется, повторный идентификатор не меняет данные.
- Сводка отправляется в HTML parse mode; пользовательские и внешние значения экранируются, а пропущенные обязательные поля выделяются `❗` и жирным текстом.
- Номер задачи Битрикс обязателен, запрашивается последним и валидируется как положительное целое число.
- Временный путь создаётся самим приложением из user id и UUID; исходное имя файла не используется.
- Очистка запускается ежедневно по времени VPS. Логи пишет `TimedRotatingFileHandler`: активный `invoice-bot.log`, архивы `invoice-bot.log.YYYY-MM-DD`, количество архивов равно `[logging] retention_days`.

## Конфигурация

Скопируйте `config.example.ini` в `config.ini`. Секреты передавайте переменными `TELEGRAM_BOT_TOKEN`, `BITRIX_ENDPOINT_URL`, `DADATA_API_KEY`, `DADATA_SECRET_KEY`, `TELEGRAM_PROXY_URL`; они имеют приоритет над INI. Не задавайте `HTTP_PROXY`, `HTTPS_PROXY` или `ALL_PROXY`.

Запрос Битрикс содержит `TITLE`, поля `UF_INVOICE_*`, `UF_ARTICLES_DDS`, обязательный положительный `UF_SEARCH_TASK` и один элемент `UF_INVOICE_FILES` с Base64 `DATA` и фактическим `EXT`. Любой HTTP 2xx считается успехом. Если ответ содержит `result.link_deal`, бот показывает пользователю эту ссылку. HTTP-ошибка расходует попытку; timeout/ошибка соединения — нет.

DaData вызывается POST-запросом `findById/party` с `branch_type=MAIN`. Название принимается только при точном совпадении ИНН и выбирается в порядке `short_with_opf`, `value`, `full_with_opf`. Результат, включая отсутствие названия, кэшируется на время активного счёта.

## Локальная проверка

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m compileall app.py invoice_bot tests
```

## Docker

```bash
cp config.example.ini config.ini
cp .env.example .env.production
mkdir -p data logs
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=100 bot
docker compose restart bot
docker compose down
```

Compose использует host network, чтобы контейнер видел SOCKS5 строго на `127.0.0.1`; приложение не слушает входящие порты. Контейнер запускается непривилегированным пользователем и монтирует постоянные `data`/`logs`. Для резервной копии остановите контейнер и архивируйте эти каталоги; для очистки удаляйте только их содержимое при остановленном контейнере.

## Xray на VPS

Xray должен быть systemd-службой и слушать только `127.0.0.1:10808`. Безопасные проверки:

```bash
sudo systemctl status xray --no-pager
sudo systemctl is-enabled xray
sudo ss -lntp | grep 10808
sudo xray run -test -config /usr/local/etc/xray/config.json
sudo systemctl restart xray
```

Обновление: сохраните Compose-файл, `.env.production`, `config.ini`, текущий image id и конфиг Xray; соберите новый образ, пересоздайте bot и проверьте healthcheck. Для отката верните сохранённые файлы/image. Xray обновляйте отдельно: резервная копия бинарника и конфига, `run -test`, restart, проверка SOCKS5; при ошибке восстановите обе копии.

## Ограничения MVP

Нет очереди, автоповторов, восстановления состояния, проверки дубликатов и внешнего AI. Реальный production smoke test выполняется только после подтверждения конкретного файла и задачи пользователем.
