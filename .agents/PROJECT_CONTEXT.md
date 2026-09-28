# PROJECT_CONTEXT — Bot Chassis

**Обновлено:** 2026-09-28

## Продукт

Универсальная несущая рама Telegram-бота на aiogram v3. Кузов
(PsyBot, Profiling Framework, Chat Listener, любой новый домен)
монтируется на неё и сам вызывает порты **перед** своей работой.
Рама кузов не запускает.

## Рабочая модель

`.agents` — control plane. Основной агент читает bootstrap, сверяет
очередь и пишет код только по подтверждённому пункту. Соседние кузова
не правятся из этого корня.

## Зафиксированные границы

- Один пакет `src/bot_chassis`, Python 3.10+ (разработка на 3.14),
  aiogram 3.13+, SQLite WAL, изоляция `bot_id`.
- Фабрика всегда собирает рабочую раму. Часть узлов подменяется
  аргументами, часть всегда дефолтная (`WorkGatePort`, `AccessPort`,
  админ-роутер, платежный роутер, middleware).
- Новые параметры фабрики — только keyword-only, в конец, `None` =
  старое поведение.
- v1 платежи — только официальные Telegram Stars (XTR).
- `tests/test_chassis.py` заморожен. `bot_gateway.py` не ломать.
- Секреты только в локальном `.env`. В Git — `examples/.env.example`.

## Текущая документация

- Канон подключения и состав: `docs/CHASSIS.md`
- Стык с PsyBot (не очередь работ): `docs/PSYBOT_INTEGRATION.md`
- История проектирования: `docs/archive/` — не backlog
- Версии: `CHANGELOG.md`, `VERSION_LOG.md`
- Эталон запуска: `examples/run_complete_chassis.py`

## Потребители

Рама одна. Кузова — отдельные Git-root:

- PsyBot / `psybot_test` — `C:\Python\tg_psy_tests`
- Chat Listener — `C:\Python\tg_chat_listener`
- Profiling Framework — отдельный репозиторий; hold рамы = tag `profiling`

## Технический вектор

Кнопки + админка + Stars + SQLite. Не тащить в раму PostgreSQL, Alembic,
Redis, клинический контент, LLM и чужие платёжные шлюзы.
