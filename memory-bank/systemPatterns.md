# System Patterns

## Архитектура

`telegram_app` управляет in-memory состояниями и вызывает `recognition` и `bitrix`; `config` строго загружает INI/env; Docker использует host network только для доступа к loopback SOCKS5.

## Принятые решения

Telegram использует `HTTPXRequest` с SOCKS5. Bitrix использует отдельный `httpx.AsyncClient(trust_env=False)`. Техническая обработка не ставится в очередь, а занимает счётчик доступной ёмкости.

## Инварианты

Не логировать токены, Base64 и полный текст. Не использовать proxy для Битрикс. Не принимать второй активный счёт и не отправлять production-тест без подтверждения.
