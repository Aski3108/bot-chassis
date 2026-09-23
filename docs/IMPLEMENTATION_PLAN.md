# Хирургический план реализации Bot Chassis (v2.10)

**Рабочий корень:** `C:\Python\bot_chassis`  
**Каноническая спецификация:** [docs/MODULAR_CHASSIS_SPEC.md](file:///c:/Python/bot_chassis/docs/MODULAR_CHASSIS_SPEC.md) (версия v2.10)  
**Текущий статус:** Этап 1 принят (28 тестов зелёные). Этап 1 НЕ откатывается, а дополняется в Задаче 2.0. Документы синхронизированы: аудит кода-плана v2.8 → v2.9, затем внешний аудит плана v2.9 → v2.10. Код Этапа 2 ещё не писать, пока не закрыта Задача 2.0.

> [!IMPORTANT]
> Инструкции для кодовой модели сформулированы строго и пошагово. Запрещено самовольно изменять сигнатуры методов Button Chassis или структуру его файлов. Все 19 базовых тестов кнопок `tests/test_chassis.py` обязаны оставаться нетронутыми и зелёными. Тесты `tests/test_storage.py` дополняются новыми проверками в Задаче 2.0. Реализация ведётся строго атомарно: задача → `pytest` → подтверждение. Пакет «весь Этап 2 разом» запрещён.

---

## Реестр правок по аудиту v2.8 → v2.9 (внесено в задачи ниже)

Закрыты до написания кода. Исполнитель следует уже исправленным задачам, этот реестр — журнал «почему так».

### Блокеры (обязательны)

| ID | Было в v2.8 | Стало в v2.9 |
|---|---|---|
| **B1** | Мягкий `ALTER` только для `users`. `CREATE TABLE IF NOT EXISTS` оставлял Stage 1 таблицу `transactions` без `provider`/`payment_id`. Тесты на tempfile были бы зелёные, dev-файл падал бы. | `initialize()` после DDL **пересобирает** `transactions`, если нет колонки `payment_id` (new → copy → drop → rename → индексы). Плюс тест на файл со старой схемой. |
| **B2** | `pre_checkout` описан как «проверка рубильника `WorkGatePort`». `can_accept_work` режет обычный бан и светит `ban_reason`. Матрица: бан → `ok=True`. | Платёжный гейт **не** равен WorkGate. Рубильник и тень — отдельно. Обычный `is_banned` на `pre_checkout` отвечает `ok=True`. |
| **B3** | Тень пропускает платежи. Троттлинг — нет. 5-й апдейт за секунду мог дропнуть `successful_payment` после списания Stars. | `ThrottlingMiddleware` **никогда** не режет `pre_checkout_query` и `Message.successful_payment`. |
| **B4** | Все мидлвари на `dp.update.outer_middleware`, но троттлинг писал `event.answer()` как для `CallbackQuery`. | Везде `event` — это `aiogram.types.Update`. Ответ через `event.callback_query` / `event.message` / `event.pre_checkout_query`. |

### Дыры и противоречия (закрыты в тексте задач)

| ID | Правка |
|---|---|
| **H1** | Успешный `ref_` дополнительно пишет `traffic_source` (first-touch). |
| **H2** | `set_traffic_source` — first-touch: обновляет только если колонка пуста. Парсинг `/start` учитывает `/start@BotName`. |
| **H3** | Кабинет обязан соответствовать §3.2 (ID + @username + дата; VIP бессрочно / до даты). Адаптер читает `get_active_subscription` у `subs_repo`. |
| **H4** | В 2.0 добавляется `mark_refunded` (`status='refunded'`, `voucher_status='cancelled'`), чтобы Этап 3 не вскрывал схему снова. |
| **H5** | Состояние рассылки живёт в `admin/broadcast.py`, **не** в `PendingInputKind`. Button Chassis не расширяем. |
| **H6** | Этап 5: синхронный `get_user_locale` читает RAM-кэш, который наполняет `UserActivityMiddleware`. Сигнатуру кнопок не менять. |
| **H7** | `/start` регистрируется на Этапе 5 как алиас меню (диплинк не ломает payload). Смена языка шлёт Reply-клавиатуру с теми же `domain_rows`, что и шасси кнопок. |
| **H8** | Троттлинг: после тоста колбэка обязателен `return None`. Словарик чистится от ключей старше окна, не только от текущего. |
| **H9** | `ErrorAlertMiddleware`: при `support_chat_id is None` алерт разработчику не шлётся; `parse_mode="HTML"`; `try/except` на ответ пользователю и на `send_message`; после обработки исключение **не** пробрасывается (кроме `enable_error_alerts=False`). |
| **H10** | `/backup` берёт тот же `asyncio.Lock`, что engine; файл — вызывающему суперадмину; лимит 50 МБ. Кнопка выгрузки на `/admin` — строго superadmin (обычному админу — тост). |
| **H11** | `send_sku_invoice` / `buy_sku:*` отвергают `sku_code='admin_grant'` и SKU вне `config.skus`. `pre_checkout` сверяет `user_id` из payload с `from_user.id`. |

### Устаревшие формулировки

- `record_successful_payment` **уже** возвращает `tuple[VoucherRecord, bool]` в Этапе 1. В 2.0 меняются поля, ключ идемпотентности и опционально порядок аргументов; существующую распаковку в тестах не ломать сверх новых полей.
- Счётчик «9 storage-тестов» в Задаче 2.5 заменён на «полный сьют `tests/`».
- `ports/storage.py` из дерева спеки **не** входит в Этап 2 (отложен, не блокирует v1).
- `set_shadow_ban`: при наложении на `admin`/`superadmin` — всегда `(False, "target_is_admin")`. Код `last_superadmin` остаётся у `set_ban` / `revoke_role`, в тень его не копировать. Снятие тени (`is_shadow_banned=False`) разрешено всегда, в том числе админам.
- Колонка `referrals.rewarded` в v1 — аудит-флаг без бонусной логики шасси. Сеттер не блокирует 2.0; метод `mark_referral_rewarded` добавляется тонким, чтобы колонка не была мёртвой.

---

## Реестр правок по внешнему аудиту плана v2.9 → v2.10

| ID | Правка |
|---|---|
| **P1** | `CREATE INDEX idx_users_bot_shbanned` в `schema.sql` падает на Stage 1 файле, если `executescript` идёт **до** `ALTER` (`no such column: is_shadow_banned`). Колонки `users` докатываются **до** DDL-индексов. |
| **P2** | Спека: `/shadowban` и досье больше не говорят «защита последнего суперадмина». Тень на любого admin/superadmin → `target_is_admin`. |
| **P3** | `build_cabinet_renderer(adapter, bot_id)` в 2.2 — клей слотов к неизменному `render_cabinet_callback`. |
| **P4** | Этап 5: датакласс `CompleteChassis`, сигнатура фабрики, порядок роутеров (кузов до кнопок), порты наружу. |
| **P5** | Payload `/start` целиком внутри `if`; `upsert_user` без второго `get_user`; троттлинг чистит текущий ключ всегда, глобально — раз в 60 с. |
| **P6** | `sku_code` из `invoice_payload`; `on_voucher_issued` только если consumer не None. |
| **P7** | Слоты 3/4 кабинета по тумблерам; `set_traffic_source` проверяет существование пользователя, не `rowcount`. |
| **P8** | `StorageEngine.backup(dest_path)` без `BEGIN IMMEDIATE`. `/refund`: `TelegramBadRequest` → без `mark_refunded`. |

---

## Решение по Этапу 1 и миграциям Storage

1. **Откат Этапа 1 исключен:** ядро Storage (`engine.py`, WAL-режим, `asyncio.Lock`, `BEGIN IMMEDIATE`, `SubscriptionsRepository` с 8 инвариантами, защита суперадмина в `roles.py`) уже написано чисто и работает.
2. **Правда о миграциях SQLite:** `ALTER TABLE` **не умеет** снимать `UNIQUE`, делать колонку nullable и менять типы. Поэтому:
   - В `schema.sql` — **цельный канонический DDL** (новые файлы и тесты поднимаются начисто).
   - `users`: мягкий `ADD COLUMN` (SQLite умеет `NOT NULL DEFAULT`).
   - `transactions`: если в существующем файле нет `payment_id` — **пересборка таблицы**, не `ALTER`.
   - `referrals`: новая таблица, достаточно `CREATE TABLE IF NOT EXISTS` из DDL.
3. **`:memory:` не использовать** в тестах и раннере: `StorageEngine` закрывает соединение после каждой операции, in-memory база при этом теряется. Только файловый путь (tempfile в тестах).

---

## Этап 2: Чистые порты, адаптеры и Middleware

Исполнять **по одной задаче**. После 2.0 — `pytest tests/test_storage.py tests/test_chassis.py`. К задачам 2.1–2.5 не переходить, пока 2.0 не зелёная.

### Задача 2.0: Синхронизация Storage Contour (доработка без отката)

1. **`src/bot_chassis/storage/schema.sql`**:
   - Обновить схему единым цельным DDL без разрывов (как в спецификации v2.10, раздел 3):
     - В `users`: `traffic_source TEXT`, `is_shadow_banned INTEGER NOT NULL DEFAULT 0`.
     - Индексы: `idx_users_bot_banned`, `idx_users_bot_shbanned ON users(bot_id, is_shadow_banned)`.
     - В `transactions`:
       - `provider TEXT NOT NULL DEFAULT 'telegram_stars'`
       - `payment_id TEXT NOT NULL`
       - `telegram_payment_charge_id TEXT` (nullable-алиас)
       - `amount INTEGER NOT NULL` (minor-units: целые Stars, копейки. **Никаких REAL!**)
       - `currency TEXT NOT NULL DEFAULT 'XTR'`
       - `status TEXT NOT NULL DEFAULT 'paid'` (`paid` | `refunded`)
       - `voucher_id TEXT NOT NULL`
       - `voucher_status TEXT NOT NULL DEFAULT 'issued'` (`issued` | `redeemed` | `cancelled`)
       - `redeemed_at TEXT`
       - Ограничение: `UNIQUE (bot_id, provider, payment_id)`
     - Таблица `referrals`:
       ```sql
       CREATE TABLE IF NOT EXISTS referrals (
           bot_id TEXT NOT NULL,
           referrer_id INTEGER NOT NULL,
           referee_id INTEGER NOT NULL,
           rewarded INTEGER NOT NULL DEFAULT 0,
           created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
           PRIMARY KEY (bot_id, referee_id),
           CHECK (referrer_id != referee_id),
           FOREIGN KEY (bot_id, referrer_id) REFERENCES users(bot_id, user_id),
           FOREIGN KEY (bot_id, referee_id) REFERENCES users(bot_id, user_id)
       );
       CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(bot_id, referrer_id);
       ```

2. **`src/bot_chassis/storage/engine.py`**:
   - Метод по-прежнему `initialize()` (не `init_schema`).
   - **Порядок в `_apply_schema` критичен** (`schema.sql` содержит `CREATE INDEX ... ON users(bot_id, is_shadow_banned)`; на файле Этапа 1 этой колонки ещё нет, индекс до `ALTER` даёт `OperationalError: no such column`):
     1. Если таблица `users` уже есть (`SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'`): докатить колонки **до** `executescript`. Если таблицы нет (новый файл) — пропустить ALTER, её создаст DDL.
        ```python
        def _add_column_if_missing(conn, sql: str) -> None:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
        if users_table_exists:
            _add_column_if_missing(conn, "ALTER TABLE users ADD COLUMN traffic_source TEXT")
            _add_column_if_missing(conn, "ALTER TABLE users ADD COLUMN is_shadow_banned INTEGER NOT NULL DEFAULT 0")
        ```
     2. `conn.executescript(schema_sql)` — `CREATE TABLE IF NOT EXISTS` (в т.ч. `referrals`) и индексы. На старой базе колонка тени уже есть, индекс создаётся. На новой — таблица из DDL уже с колонками.
     3. Пересборка `transactions`, если нет `payment_id`:
        ```python
        cols = {row[1] for row in conn.execute("PRAGMA table_info(transactions)").fetchall()}
        if cols and "payment_id" not in cols:
            # CREATE TABLE transactions_new (...канонический DDL без IF NOT EXISTS...);
            # INSERT INTO transactions_new (
            #   id, bot_id, user_id, provider, payment_id, telegram_payment_charge_id,
            #   provider_payment_charge_id, sku_code, amount, currency, status,
            #   voucher_id, voucher_status, redeemed_at, created_at, updated_at
            # )
            # SELECT
            #   id, bot_id, user_id, 'telegram_stars', telegram_payment_charge_id,
            #   telegram_payment_charge_id, provider_payment_charge_id, sku_code,
            #   amount, currency, status, voucher_id, voucher_status, redeemed_at,
            #   created_at, updated_at
            # FROM transactions;
            # DROP TABLE transactions;
            # ALTER TABLE transactions_new RENAME TO transactions;
            # CREATE INDEX idx_tx_bot_user; CREATE UNIQUE INDEX idx_tx_voucher;
        ```
   - Публичный метод **без** `BEGIN IMMEDIATE` (внутри транзакции `sqlite3.backup` блокируется; админка не лезет в `_lock`):
     ```python
     async def backup(self, dest_path: str) -> None:
         # async with self._lock: открыть src, sqlite3.connect(dest_path), src.backup(dest), закрыть оба.
     ```
     Не вызывать `self.run()` для бэкапа.

3. **`src/bot_chassis/storage/repositories/users.py`**:
   - В `UserRecord` добавить: `created_at: str`, `traffic_source: Optional[str] = None`, `is_shadow_banned: bool = False`.
   - В `_row_to_user` читать эти поля (`is_shadow_banned=bool(row["is_shadow_banned"])`).
   - **Язык не затирается.** В `upsert_user` при конфликте:
     `language_code = users.language_code,`  
     *(язык ставится только на первом INSERT; Telegram-клиент не имеет права сбрасывать выбор пользователя)*.
   - `async def set_language_code(self, bot_id: str, user_id: int, language_code: str) -> bool`.
   - `async def set_traffic_source(self, bot_id: str, user_id: int, traffic_source: str) -> bool`:
     - First-touch: `UPDATE ... SET traffic_source = ? WHERE bot_id = ? AND user_id = ? AND (traffic_source IS NULL OR traffic_source = '')`.
     - Возврат `True`, если пользователь **существует** (`SELECT 1 FROM users WHERE bot_id = ? AND user_id = ?`). Не опираться на `cur.rowcount` у UPDATE: при уже заполненной колонке rowcount = 0, это валидный no-op, не `False`. Нет пользователя → `False`.
   - `async def set_shadow_ban(self, bot_id: str, user_id: int, is_shadow_banned: bool) -> tuple[bool, Optional[str]]`:
     - Нет пользователя → `(False, "not_found")`.
     - Снятие тени (`is_shadow_banned=False`) — всегда разрешено, в том числе админам.
     - Наложение тени: если у цели роль `admin` или `superadmin` → `(False, "target_is_admin")`. Код `"last_superadmin"` сюда **не** ставить (он принадлежит `set_ban` / `revoke_role`).
   - `async def get_broadcast_user_ids(self, bot_id: str) -> list[int]`:
     - `SELECT user_id FROM users WHERE bot_id = ? AND is_banned = 0 AND is_shadow_banned = 0` (маска спамера не спадает при рассылках).

4. **`src/bot_chassis/storage/repositories/transactions.py`**:
   - Этап 1 уже возвращает `tuple[VoucherRecord, bool]`. Сохранить это.
   - В `VoucherRecord` добавить: `provider: str`, `payment_id: str`, `redeemed_at: Optional[str] = None`. Поле `telegram_payment_charge_id` оставить (алиас Stars).
   - В `_row_to_voucher` читать новые поля; `redeemed_at` уже есть в таблице Этапа 1.
   - Сигнатура (порядок аргументов канонизируется; существующие тесты перевести на **keyword**-вызовы, если ещё позиционные):
     ```python
     async def record_successful_payment(
         self,
         bot_id: str,
         user_id: int,
         sku_code: str,
         amount: int,
         telegram_payment_charge_id: str,
         provider: str = "telegram_stars",
         payment_id: Optional[str] = None,
         provider_payment_charge_id: Optional[str] = None,
         currency: str = "XTR",
         voucher_id: Optional[str] = None,
     ) -> tuple[VoucherRecord, bool]:
     ```
     - Если `payment_id is None`: `payment_id = telegram_payment_charge_id`.
     - Поиск: `WHERE bot_id = ? AND provider = ? AND payment_id = ?`.
     - Повтор → `(existing, False)`. Новая вставка → `(new, True)`.
   - Новый метод для Этапа 3 (схема больше не вскрывается):
     ```python
     async def mark_refunded(
         self,
         bot_id: str,
         payment_id: str,
         provider: str = "telegram_stars",
     ) -> tuple[bool, Optional[str]]:
     ```
     - Нет ряда → `(False, "not_found")`.
     - `provider != 'telegram_stars'` → `(False, "not_stars")` (талоны `admin_grant` сюда не переводятся).
     - Уже `status='refunded'` или `voucher_status='cancelled'` → `(False, "already_refunded")`.
     - Иначе: `status='refunded'`, `voucher_status='cancelled'`. Если талон уже `redeemed` — рефанд **разрешён** (решение админа: Stars вернули, услуга могла быть оказана).

5. **`src/bot_chassis/storage/repositories/referrals.py` [NEW]**:
   - `ReferralsRepository(engine: StorageEngine, users: UsersRepository)`:
     - `record_referral(bot_id, referrer_id, referee_id) -> tuple[bool, Optional[str]]`:
       - `referrer_id == referee_id` → `(False, "self_referral")`.
       - `await self._users.upsert_user` для обоих (заглушка FK).
       - `INSERT OR IGNORE INTO referrals (bot_id, referrer_id, referee_id, rewarded, created_at) VALUES (?, ?, ?, 0, ?)`.
       - `rowcount > 0` → `(True, None)`, иначе `(False, "already_exists")`.
     - `get_referrals_count(bot_id, referrer_id) -> int`.
     - `mark_referral_rewarded(bot_id, referee_id) -> bool` — тонкий `UPDATE rewarded = 1`. Шасси само бонусы не выдаёт.

6. **`src/bot_chassis/storage/__init__.py`**:
   - Зарегистрировать `referrals: ReferralsRepository` в `Storage` и `create_storage`.

7. **`tests/test_storage.py`**:
   - Оплаты: keyword-аргументы, распаковка `(record, created)` (уже есть — дополнить полями `provider`/`payment_id`/`redeemed_at`).
   - Язык не затирается повторным `upsert_user`.
   - `set_traffic_source` first-touch: второй вызов с другим хвостом **не** перезаписывает.
   - `set_shadow_ban`: обычный пользователь; наложение на admin/superadmin → `"target_is_admin"`; снятие тени с админа проходит.
   - `get_broadcast_user_ids` исключает `is_banned` и `is_shadow_banned`.
   - Рефералы: запись, `self_referral`, счётчик, `mark_referral_rewarded`.
   - `mark_refunded`: Stars-ряд → cancelled/refunded; `admin_grant` → `"not_stars"`.
   - **Миграция:** создать файл с DDL Этапа 1 (без `payment_id` / без тени), вызвать `initialize()`, проверить колонки `users`, индекс `idx_users_bot_shbanned`, ряд `transactions` с `provider='telegram_stars'`, `payment_id == telegram_payment_charge_id`.
   - `engine.backup(dest)`: копия открывается, исходная база после бэкапа читается.
   - Прогон: `pytest tests/test_storage.py tests/test_chassis.py` — все зелёные. К 2.1 не переходить.

---

### Задача 2.1: Тумблеры и аудит-чат в `src/bot_chassis/config.py`

В `BotChassisConfig` добавить поля (дефолты не ломают существующие конструкторы в тестах):
* `audit_chat_id: int | None = None`
* `enable_error_alerts: bool = True`
* `enable_throttling: bool = True`
* `notify_on_payment: bool = True`
* `enable_language_switch: bool = False`
* `enable_referrals: bool = False`

Прогон: `pytest tests/test_storage.py tests/test_chassis.py`.

---

### Задача 2.2: Чистые порты и адаптеры в `src/bot_chassis/ports/`

Файл `ports/storage.py` (протоколы репозиториев) в Этап 2 **не** входит — отложен, v1 на нём не стоит.

1. **`src/bot_chassis/ports/work_gate.py`**:
   - `WorkGatePort`: `async def can_accept_work(bot_id: str, user_id: int) -> tuple[bool, str | None]`.
   - `DefaultWorkGateAdapter(settings_repo, users_repo)` — **только задачи кузова**, не платежи:
     - Рубильник → `(False, reason)`.
     - Тень **первой** → `(False, None)` (маска; даже если одновременно обычный бан).
     - Обычный бан → `(False, ban_reason)`.
     - Иначе `(True, None)`.
   - Иммунитет админов к тени живёт в middleware, не здесь.

2. **`src/bot_chassis/ports/access.py`**:
   - `AccessPort` = трансляция в `SubscriptionsRepository` (`has_active_access`, `grant_gift_access`, `revoke_gift_access`).
   - Карточка кабинета **не** ограничена этим портом: слот доступа читает `subs_repo.get_active_subscription`.

3. **`src/bot_chassis/ports/payments.py`**:
   - `SkuVoucher`: `voucher_id`, `bot_id`, `user_id`, `sku_code`, `payment_id`, `amount: int`, `currency`, `status`, `redeemed_at`.
   - `VoucherManagerPort`: `get_active_vouchers`, `redeem_voucher`.
   - `SkuVoucherConsumerPort`: `on_voucher_issued`.
   - `DefaultVoucherManagerAdapter(tx_repo)` мапит `VoucherRecord` → `SkuVoucher`.

4. **`src/bot_chassis/ports/referrals.py`**:
   - `ReferralPort`: `record_referral`, `get_referrals_count` (и прокси `mark_referral_rewarded`, если порт его реэкспортирует — кузов сам решает, когда ставить флаг).

5. **`src/bot_chassis/ports/cabinet.py`**:
   - `CabinetSlot`: `slot_id`, `title`, `content`, `buttons: tuple = ()`.
   - `DefaultCabinetSlotsAdapter(subs_repo, tx_repo, users_repo=None, referrals_repo=None, bot_username="", enable_payments=True, enable_referrals=False)`.
   - Слот 3 только если `enable_payments`. Слот 4 только если `enable_referrals` **и** `referrals_repo` (фабрика при выключенном тумблере передаёт `referrals_repo=None` и/или флаг False).
   - Слоты **строго §3.2**, не упрощённые заглушки:
     - Слот 1: `ID: {user_id} | @{username или —} | Зарегистрирован: {created_at[:10]}`.
     - Слот 2: активная подписка через `get_active_subscription` → `VIP (Бессрочно)` / `VIP (до {expires_at[:10]})` / иначе `Базовый`.
     - Слот 3: число активных талонов.
     - Слот 4: счётчик и `https://t.me/{bot_username}?start=ref_{user_id}`.
   - **Клей к Button Chassis** (сигнатуру `create_button_chassis_router` не менять):
     ```python
     def build_cabinet_renderer(
         adapter: CabinetSlotsProviderPort,
         bot_id: str,
     ) -> Callable[[types.Message, int, Bot], Awaitable[Optional[types.Message]]]:
         async def _render(message: types.Message, user_id: int, bot: Bot) -> Optional[types.Message]:
             slots = await adapter.get_cabinet_slots(bot_id, user_id)
             # HTML-карточка: заголовок + title/content каждого слота, html.escape на пользовательских полях.
             return await message.answer(text, parse_mode="HTML")
         return _render
     ```
     Этап 5 передаёт `render_cabinet_callback=build_cabinet_renderer(adapter, config.bot_id)`. Без этого колбэк = None и экран останется заглушкой «Раздел настроен в шасси».

6. **`src/bot_chassis/ports/__init__.py`**: экспорт интерфейсов и дефолтных адаптеров.

Прогон: достаточно импорта пакета + существующие тесты, либо сразу 2.5 вместе с мидлварями — но **не** смешивать написание 2.2 и 2.3 в одном коммите-шаге: сначала 2.2, `pytest tests/`, затем 2.3.

---

### Задача 2.3: Middleware в `src/bot_chassis/middleware/`

Подключение строго через `dp.update.outer_middleware(...)`.  
`event` **всегда** `aiogram.types.Update`.  
Порядок регистрации (первый = самый внешний):
```
Входящий Update
  └── [1] ErrorAlertMiddleware
        └── [2] ThrottlingMiddleware
              └── [3] UserActivityMiddleware
                    └── Роутеры бота
```

Конструкторы (явная инъекция, не сюрприз из `data`):
- `ErrorAlertMiddleware(config: BotChassisConfig)`
- `ThrottlingMiddleware(bot_id: str, enabled: bool = True)`
- `UserActivityMiddleware(bot_id: str, storage: Storage, config: BotChassisConfig, locale_cache: dict[int, str] | None = None)`

1. **`error_monitor.py` (`ErrorAlertMiddleware`)**:
   - `enable_error_alerts is False` → `raise` (проброс).
   - `True`: обернуть `await handler(event, data)` в `try/except Exception`.
     - Ответ пользователю в `try/except Exception` (повторный `answer()` колбэка не роняет мидлварь):
       - `event.pre_checkout_query` → `answer(ok=False, error_message="⚠️ Ошибка при обработке платежа.")`.
       - `event.callback_query` → `answer("⚠️ Произошла непредвиденная ошибка. Мы уже разбираемся!", show_alert=True)`.
       - `event.message` → `answer("⚠️ Произошла непредвиденная ошибка. Мы уже разбираемся!")`.
     - Разработчику: только если `config.support_chat_id is not None`. Трейсбек `html.escape(traceback.format_exc()[-3500:])`, `parse_mode="HTML"`, `bot.send_message` в `try/except Exception: logger.exception(...)`.
     - После обработки **не** пробрасывать исключение (иначе двойной хэндлинг).

2. **`throttling.py` (`ThrottlingMiddleware`)**:
   - Если `enabled is False` — сразу `return await handler(event, data)`.
   - **Whitelist платежей (до счётчика):**
     - `event.pre_checkout_query is not None` → сразу handler.
     - `event.message is not None and event.message.successful_payment is not None` → сразу handler.
   - Пользователь: `data.get("event_from_user")`. Нет пользователя → handler без лимита.
   - Ключ: `(self._bot_id, user.id)`. Окно 1.0 сек, лимит 4.
     - На **каждом** заходе чистить метки старше окна **только у текущего ключа**; пустой ключ удалять.
     - Глобальный проход по всем ключам — не чаще чем раз в 60 секунд (или после N апдейтов), иначе O(N) на каждый Update.
   - Превышение:
     - Есть `event.callback_query` → `await event.callback_query.answer("⚠️ Слишком часто! Пожалуйста, помедленнее.", show_alert=False)` затем **`return None`** (хэндлер не вызывать).
     - Иначе (в т.ч. обычный `Message`) → `return None`.

3. **`user_activity.py` (`UserActivityMiddleware`)**:
   - `user = data.get("event_from_user")`. Нет пользователя → handler.
   - `user_record = await storage.users.upsert_user(bot_id, user.id, user.username, user.first_name, user.last_name, user.language_code)` — **без** второго `get_user` (`upsert_user` уже возвращает `UserRecord`).
   - Если передан `locale_cache` и есть `user_record` — `locale_cache[user.id] = user_record.language_code`.
   - **Тень:**
     1. Иммунитет: `has_any_role(..., ("admin", "superadmin"))` — не дропать.
     2. Платежи не дропать: `pre_checkout_query` и `message.successful_payment` → handler. Чек обязан записаться; `pre_checkout` ответит роутер (10 сек, без слова «бан»).
     3. `callback_query` → пустой `await event.callback_query.answer()`, затем `return None`.
     4. Прочее → `return None`.
   - Payload `/start` — **после** прохождения тени. Все обращения к `payload` **строго внутри** условия (иначе `UnboundLocalError`):
     ```python
     text = (event.message.text or "") if event.message else ""
     parts = text.split(maxsplit=1)
     cmd = parts[0].split("@")[0] if parts else ""
     if cmd == "/start" and len(parts) > 1:
         payload = parts[1].strip()
         if payload:
             if payload.startswith("ref_"):
                 try:
                     referrer_id = int(payload[4:])
                 except ValueError:
                     referrer_id = None
                 if referrer_id is not None and config.enable_referrals:
                     await storage.referrals.record_referral(bot_id, referrer_id, user.id)
             await storage.users.set_traffic_source(bot_id, user.id, payload)
     ```

Прогон: `pytest tests/test_chassis.py` (кнопки не сломаны). Полные тесты мидлварей — в 2.5.

---

### Задача 2.4: Переключение языков в `src/bot_chassis/localization.py`

- `ALLOWED_LOCALES = frozenset({"ru", "en"})`.
- `build_language_switch_row() -> list[InlineKeyboardButton]` с `core_lang:ru` / `core_lang:en`.
- Роутер `localization_router`. Хэндлер `F.data.startswith("core_lang:")`.
- Невалидный код → `await call.answer()` и выход.
- Тумблер выключен → `await call.answer("Смена языка отключена", show_alert=False)`.
- Тумблер включён: `set_language_code`; обновить `locale_cache` если передан; `await call.answer("Язык изменён / Language updated")`.
- Reply-клавиатуру **нельзя** слать через `editMessageText`. Новое сообщение:
  `await call.message.answer(..., reply_markup=build_main_menu_keyboard(locale=lang, domain_rows=domain_rows, ...))`.
- `domain_rows` и тумблеры кабинета/info/support — **те же**, что у Button Chassis, через замыкание фабрики роутера (в изоляции 2.4 допустим `domain_rows=None`).
- Если `call.message` недоступен (`InaccessibleMessage`) — только `answer()`, без падения.
- Динамическая подтяжка языка в `/menu` — Этап 5 через `get_user_locale` + кэш.

Прогон: `pytest tests/test_chassis.py`.

---

### Задача 2.5: Тесты Этапа 2 в `tests/test_ports_and_middleware.py`

1. `test_work_gate_adapter`: рубильник, бан с причиной, тень первой даёт `(False, None)`.
2. `test_access_adapter_invariants`: 8 инвариантов через `DefaultAccessAdapter`.
3. `test_voucher_manager_adapter`: маппинг и погашение.
4. `test_cabinet_slots_adapter`: §3.2 (ID, @username, дата, VIP бессрочно/до даты); слот талонов скрыт при `enable_payments=False`; слот рефералок скрыт при `enable_referrals=False`; `build_cabinet_renderer` возвращает callable с сигнатурой `render_cabinet_callback`.
5. `test_throttling_middleware`: 4 проходят, 5-й тост + хэндлер не вызван; чистка ключей; платежный апдейт **не** режется даже сверх лимита; конструктор с `bot_id`.
6. `test_error_monitor_middleware`: HTML-escape; нет цикла; ветка `PreCheckoutQuery`; `enable_error_alerts=False` → `raise`; `support_chat_id is None` → пользователю ответили, `send_message` не звали.
7. `test_user_activity_middleware_language_retention`: `language_code="ru"` от Telegram не затирает `"en"` в БД.
8. `test_user_activity_middleware_shadow_ban_silent_drop`: Message → `None`; CallbackQuery — пустой `answer()`; `upsert_user` был.
9. `test_user_activity_middleware_shadow_ban_payment_pass`: pre_checkout и `successful_payment` доходят до хэндлера.
10. `test_user_activity_middleware_shadow_ban_admin_immunity`: admin/superadmin под тенью не дропаются.
11. `test_user_activity_middleware_referrals`: `ref_123`, `ref_invalid_abc`, `/start@BotName ref_1`, first-touch, запись `traffic_source` при успешной рефералке.
12. `test_localization_router`: белый список, Reply-клавиатура через `answer`, `domain_rows` сохраняются если переданы.
13. Полный прогон: `pytest tests/` (19 кнопок + storage после 2.0 + порты/мидлвари — 100% зелёные).

---

## Этап 3: Admin Chassis

1. **`src/bot_chassis/admin/filters.py`**: `AdminRoleFilter`, `SuperadminRoleFilter`.

2. **`src/bot_chassis/admin/audit.py`**: `send_admin_audit(bot, config, text)`:
   - `audit_chat_id is None` → no-op.
   - Бот — админ канала с правом отправки.
   - Пользовательские поля через `html.escape`.
   - `send_message(..., parse_mode="HTML")` в `try/except Exception: logger.exception(...)`.

3. **`src/bot_chassis/admin/router.py`**:
   - `/admin`: сводка; инлайн без FSM: рубильник, выгрузка, рассылка.
   - Выгрузка на главном экране — **только superadmin** (152-ФЗ). Обычный admin → `show_alert=True`.
   - Команды: `/user`, `/ban`, `/unban`, `/shadowban`, `/grant`, `/revoke`, `/gift`, `/gift_revoke`, `/export` (superadmin), `/backup` (superadmin), `/refund`, `/maintenance`.
   - `/shadowban` зовёт `set_shadow_ban` с контрактом 2.0 (`target_is_admin` на админов).
   - `/refund <user_id> <payment_id>`: только `provider=='telegram_stars'`; `bot.refund_star_payment(user_id=..., telegram_payment_charge_id=...)` по колонке charge_id в `try/except TelegramBadRequest` (и общий `TelegramAPIError`). Если Telegram отклонил возврат — **не** звать `mark_refunded`, отдать админу текст ошибки. Успех → `mark_refunded`. `admin_grant` не передавать в Bot API.
   - `/backup`: `await storage.engine.backup(dest_path)` (публичный метод, lock внутри, **без** `run()`/`BEGIN IMMEDIATE`); отправка **вызывающему** суперадмину. Если файл ≥ 50 МБ — ошибка в чат, не слать. Не рассылать всем из `superadmin_ids`. Не читать `engine._lock` из роутера.
   - Досье `adm_usr:*` — как в спецификации §6.3 (gift30 замена ряда, `addvouch` через `admin_grant` + uuid, аудит).

4. **`src/bot_chassis/admin/broadcast.py`**:
   - Состояние ввода **изолировано здесь** (свой RAM-флаг/текст, ключ по `user_id`). **Не** добавлять `PendingInputKind.BROADCAST_CONTENT` в `followup.py` (19 тестов кнопок неприкосновенны, конфликт с тикетом поддержки исключается отдельным store).
   - 25 msg/s, backoff на `RetryAfter`.
   - Получатели: `get_broadcast_user_ids`.
   - Предпросмотр, прогресс, `adm_bcast:stop`, отчёт + `send_admin_audit`.

5. Тесты: `tests/test_admin.py`.

---

## Этап 4: Платежи v1 — Telegram Stars (Bot API 7.x)

1. **Только Stars в v1.** Нет HTTP-сервера, нет CryptoBot/ЮKassa в коде рамы. Схема мульти-провайдерная, код v1 пишет `provider='telegram_stars'`, `currency='XTR'`.

2. **Инвойс:** `currency="XTR"`, `provider_token=""`, `LabeledPrice.amount = sku.stars_price` (целые Stars, **не** ×100), `payload = f"sku:{sku_code}:{user_id}:{uuid.uuid4().hex[:8]}"` при `len(payload.encode()) <= 128`, `is_flexible=False`.

3. **Запреты:**
   - `send_sku_invoice` / колбэк `buy_sku:*` отвергают `sku_code == "admin_grant"` и SKU, которого нет в `config.skus`.
   - `admin_grant` эмитируется только суперадмином из досье `/user`.

4. **`pre_checkout_query` — отдельный платёжный гейт, не `WorkGatePort.can_accept_work()`:**
   - Рубильник опущен → `answer(ok=False, error_message=reason)`.
   - `is_shadow_banned` → `answer(ok=False, error_message="Оплата временно недоступна")` (без слова «бан»).
   - Обычный `is_banned` → **`ok=True`** (матрица).
   - Сверить `user_id` из payload с `query.from_user.id`; несовпадение → `ok=False` с нейтральным текстом.
   - Иначе `ok=True`.
   - Ответ обязан уйти за 10 секунд.

5. **`successful_payment`:**
   - `sku_code` и `user_id` из payload берутся из `message.successful_payment.invoice_payload` формата `sku:{sku_code}:{user_id}:{nonce}` (`try/except`). Битый payload: записать чек с `sku_code='invalid_payload'` (Stars уже списаны, идемпотентность по charge_id), **не** звать `on_voucher_issued`, алерт в support. `amount = successful_payment.total_amount`, `telegram_payment_charge_id = successful_payment.telegram_payment_charge_id`.
   - Только `created is True` **и** `voucher_consumer is not None` → `await voucher_consumer.on_voucher_issued(voucher)`. Алерт в `support_chat_id` при `notify_on_payment=True`.
   - `created is False` → стоп (идемпотентность). Чек пишется даже при рубильнике, бане и тени (деньги уже списаны).

6. **`/refund`:** как в Этапе 3: сначала Bot API в try/except, при успехе `mark_refunded`.

7. Тесты: `tests/test_payments.py` (включая: бан не режет pre_checkout; тень режет нейтрально; admin_grant нельзя купить; whitelist троттлинга не дропает чек).

---

## Этап 5: Сборка рамы, раннер, верификация

1. **`src/bot_chassis/factory.py`**:
   ```python
   @dataclass(slots=True)
   class CompleteChassis:
       dp: Dispatcher
       bot: Bot
       config: BotChassisConfig
       storage: Storage
       work_gate: WorkGatePort
       access: AccessPort
       vouchers: VoucherManagerPort
       referrals: ReferralPort
       cabinet: CabinetSlotsProviderPort
       locale_cache: dict[int, str]

   async def create_complete_chassis(
       bot: Bot,
       config: BotChassisConfig,
       dp: Dispatcher | None = None,
       storage: Storage | None = None,
       voucher_consumer: SkuVoucherConsumerPort | None = None,
       cabinet_provider: CabinetSlotsProviderPort | None = None,
       domain_router: Router | None = None,
       domain_rows: Sequence[Sequence[str]] | None = None,
   ) -> CompleteChassis:
   ```
   - Если `storage is None` → `create_storage(config)`. Если `dp is None` → `Dispatcher()`.
   - Собирает дефолтные адаптеры портов. `cabinet_provider` если передан — вместо дефолтного. Фабрика передаёт в кабинет `enable_payments=config.enable_payments`, `referrals_repo` только при `config.enable_referrals`.
   - Регистрирует middleware на `dp.update.outer_middleware` в порядке 2.3. `locale_cache: dict[int, str]` пишут UserActivity и смена языка; `get_user_locale=lambda uid: cache.get(uid) or config.default_locale`. Сигнатуру `create_button_chassis_router` **не** менять.
   - **Порядок `dp.include_router` (первый видит апдейт раньше при совпадении фильтров):**
     1. Admin
     2. Payments
     3. Localization (те же `domain_rows`/тумблеры, что кнопки)
     4. **`domain_router` кузова** (если передан) — до кнопок, чтобы доменные `F.text` / команды кузова не были перекрыты.
     5. Button Chassis с `render_cabinet_callback=build_cabinet_renderer(cabinet, config.bot_id)`.
   - Хэндлер `Command("start")` на служебном роутере шасси **до** кнопок: то же меню, что `/menu`. Middleware уже отработал payload.
   - Посев суперадминов уже делает `create_storage`; повторный `seed_superadmins` допустим (`INSERT OR IGNORE`).
   - Возвращает `CompleteChassis`. Кузов берёт порты с объекта (`chassis.work_gate.can_accept_work(...)`) — шасси кузов сам не вызывает.

2. **`examples/run_complete_chassis.py`** вместо наращивания `examples/run_example.py`.

3. **`tests/test_integration.py`:** сквозной цикл (старт с payload, тень × платёж, кабинет §3.2 через renderer, досье, рефанд).

---

## Порядок исполнения (напоминание)

1. Задача 2.0 → `pytest tests/test_storage.py tests/test_chassis.py`.
2. Задача 2.1 → те же тесты.
3. Задача 2.2 → `pytest tests/`.
4. Задача 2.3 → `pytest tests/`.
5. Задача 2.4 → `pytest tests/`.
6. Задача 2.5 → полный `pytest tests/`.
7. Этап 3 → `tests/test_admin.py` + полный сьют.
8. Этап 4 → `tests/test_payments.py` + полный сьют.
9. Этап 5 → интеграция + полный сьют.
