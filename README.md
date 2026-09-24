# Bot Chassis (Шасси бота)

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![aiogram 3.13+](https://img.shields.io/badge/aiogram-3.13+-blue.svg)](https://docs.aiogram.dev/)
[![Tests](https://img.shields.io/badge/tests-80%20passed-brightgreen.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Универсальное переносимое модульное шасси для Telegram-ботов на `aiogram v3`.**  
> Единый UX, неисчезающие клавиатуры, рантайм-защита от гонок и повторных кликов, двусторонний мост поддержки, админка, Telegram Stars, SQLite WAL.  
> **Канон:** [docs/CHASSIS.md](docs/CHASSIS.md). История проектирования: [docs/archive/](docs/archive/README.md).

---

## 🚗 Концепция: почему именно «Шасси» (Chassis)?

В классической автоинженерии **шасси** — это готовая несущая рама: двигатель, ходовая часть, подвеска, рулевое управление и тормоза.
На одно и то же шасси можно установить любой кузов:
- кузов седана (`Profiling Bot` — психолингвистический анализ переписок),
- кузов внедорожника (`PsyBot` — клиническая психологическая самодиагностика),
- кузов фургона (`Chat Listener` — мониторинг чатов и лидогенерация).

При этом водителю гарантированы одинаковые стандарты безопасности, управляемости и стабильности.

**Bot Chassis** решает ту же задачу для Telegram-ботов: системная несущая часть пишется один раз, стабилизируется тестами и подключается в любой проект через единую фабрику с отключаемыми тумблерами.

---

## 🏗️ Модульная архитектура: 3 суб-шасси + общее хранилище

Шасси состоит из 3 независимых суб-шасси, объединённых общим мультитенантным хранилищем:

```text
┌────────────────────────────────────────────────────────────────────────┐
│                      Bot Chassis (Общее ядро)                          │
├──────────────────┬──────────────────────┬──────────────────────────────┤
│ 1. Шасси кнопок  │  2. Шасси админки    │      3. Шасси платежей       │
│ (Button Chassis) │   (Admin Chassis)    │      (Payment Chassis)       │
│                  │                      │                              │
│ • Нижнее меню    │ • Super-Admin / Admin│ • Telegram Stars             │
│ • Команды /menu  │ • Назначение в TG    │ • Инвойсы и чеки             │
│ • Мост поддержки │ • Рубильник (Maint.) │ • Идемпотентность charge_id  │
│ • Lifecycle карт │ • User Inspector     │ • Выдача талона (услуги)     │
├──────────────────┴──────────────────────┴──────────────────────────────┤
│            4. Общий контур хранения данных (Storage Contour)           │
│    user_id | bot_id | role | balance_stars | consent_at | charge_id    │
└────────────────────────────────────────────────────────────────────────┘
```

### 1. Суб-шасси кнопок (Button Chassis) — ГОТОВО (19 тестов)
- **Транспортная безопасность:** Неисчезающая `ReplyKeyboardMarkup` (`is_persistent=True`, `resize_keyboard=True`).
- **Единый носитель клавиатуры:** Клавиатура привязана к постоянному сообщению `/start` или `/menu` и никогда не удаляется менеджером экранов.
- **Системное меню:** Автоматическая регистрация команд в Bot API (`set_my_commands`) через хук запуска `register_button_chassis_startup(dp, bot)`. Команды `/start`, `/menu`, `/help`, `/support` объединяются с кастомными командами шлюза без затирания.
- **Сессионная гигиена:** Хранилище `PendingInputStore` со строгим TTL (15 мин). Клик по любой служебной или доменной кнопке мгновенно сбрасывает режим ввода тикета поддержки.
- **Двусторонний мост поддержки:** Связка по композитному ключу `(chat_id, message_id) -> user_id`, фиксация карточки-шапки и копии сообщения пользователя. Атомарное сохранение на диск (`temp/support_threads.json` через `.tmp` и `os.replace`). Лимит активных тикетов без ответа (`max_active_tickets=5`). Полная тишина на служебную переписку админов между собой (`UNKNOWN_THREAD`).
- **Слоты контента (Дырки, а не содержимое):** Карточки Кабинета и Info подключаются через внешние колбэки (`render_cabinet_callback`, `render_info_callback`) с автоматическим запоминанием в `UserScreenTracker`.

### 2. Суб-шасси администрирования (Admin Chassis) — ГОТОВО
- **Двухуровневая модель доступа:**
  - `SUPER_ADMIN` (из конфига/env) — полный контроль, управление админами прямо из Telegram.
  - `ADMIN` — просмотр дашборда, поиск пользователя, прямая связь.
- **Динамический персистентный реестр:** Назначение и отзыв прав админа на лету без правки `.env` и без рестарта процесса.
- **Дашборд здоровья и статистики:** Uptime, потребление RAM процесса, количество пользователей, открытые тикеты.
- **User Inspector:** Поиск пользователя по Telegram ID, просмотр профиля, кнопка `[✉️ Написать пользователю]`, блокировка/разблокировка.
- **Аварийный рубильник (Maintenance Mode):** Стопорит приём новых задач с вежливой заглушкой, не ломая навигацию.
- **2-Step Confirmation:** Защита деструктивных операций одноразовыми токенами с подтверждением.

### 3. Суб-шасси платежей (Payment Chassis) — ГОТОВО (v1, Telegram Stars)
- **Выдача талона, а не прикладного анализа:** Шасси отвечает за инвойс Telegram Stars, предоплату (`pre_checkout_query`), успешную оплату (`successful_payment`) и идемпотентность по `telegram_payment_charge_id`.
- **Каталог SKU:** Настраиваемый список услуг (`sku_code`, `stars_price`, `title`, `description`).
- При успешной оплате шасси начисляет баланс / талон и уведомляет кузов: `on_purchase_completed(user_id, sku, bot_id)`. Что означает этот талон — решает кузов.

### 4. Общий контур хранения (Storage Contour)
- Мультитенантная модель: обязательный ключ `bot_id` (или `project_id`), гарантирующий, что пользователи, роли и звёзды разных ботов не перемешаются в одной базе данных.

---

## 🚫 Чего НЕТ и НЕ БУДЕТ внутри рамы шасси
Шасси остаётся чистым транспортом и каркасом. В раму **запрещено** помещать:
- Специфические опросники, клинические шкалы и диагнозы (кузов PsyBot).
- Расчёты стилометрии, лемм, токсичности и PDF C1–C6 (кузов Profiling).
- Списки отслеживаемых чатов и ключевые слова (кузов Chat Listener).
- Модули сбора отзывов и витрины кросс-промо экосистемы.
- LLM-операторов саппорта и кризисные протоколы.

---

## 📦 Быстрый старт

Полная рама (кнопки + storage + админка + Stars):

```python
from aiogram import Bot
from bot_chassis.config import BotChassisConfig
from bot_chassis.factory import create_complete_chassis
from bot_chassis.commands import register_button_chassis_startup

async def main(bot: Bot) -> None:
    config = BotChassisConfig(bot_id="demo", superadmin_ids=(108234567,))
    chassis = await create_complete_chassis(bot, config, domain_rows=(("📊 Задачи",),))
    register_button_chassis_startup(chassis.dp, bot)
    await chassis.dp.start_polling(bot)
```

Эталон: `examples/run_complete_chassis.py`. Как цепляется кузов и порты — [docs/CHASSIS.md](docs/CHASSIS.md).

Только кнопки (без БД и админки): `create_button_chassis_router` и `examples/run_example.py`. Этот пример не наращивать.

### Только кнопки

```python
import asyncio
from aiogram import Bot, Dispatcher, types
from bot_chassis import (
    create_button_chassis_router,
    register_button_chassis_startup,
    CardClosePolicy,
)

bot = Bot(token="YOUR_BOT_TOKEN")
dp = Dispatcher()

# 1. Регистрируем синюю кнопку «Меню» в клиенте Telegram при старте
register_button_chassis_startup(dp, bot)

# 2. Создаем роутер шасси с нужными тумблерами и портами
chassis_router = create_button_chassis_router(
    support_chat_id=-100123456789,
    enable_cabinet=True,
    enable_info=True,
    enable_support=True,
    domain_rows=[["📊 Ваши чаты", "🔍 Ваши слова"]],
    project_label="Демо-Сервис",
)

dp.include_router(chassis_router)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 🧪 Тестирование

Сьют тестов шасси изолирован и не требует подключения к реальному Telegram Bot API:

```bash
pytest tests/ -v
```

Полная рама: **80 passed**. Замороженные тесты кнопок: `pytest tests/test_chassis.py -v` (19 шт.).
