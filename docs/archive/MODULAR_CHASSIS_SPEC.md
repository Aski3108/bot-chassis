> **Архив.** Канон v1: [../CHASSIS.md](../CHASSIS.md). Этот файл — чертёж реализации v2.10, не очередь работ.

# Полная рама Bot Chassis — пакеты, Storage, порты

**Статус:** Согласованная архитектурная спецификация (v2.10, правки по аудиту плана).  
**Корень:** `C:\Python\bot_chassis` (не Profiling_Framework).  
**Шлюз `bot_gateway.py` не трогать.**  
**Очередь работ:** `docs/IMPLEMENTATION_PLAN.md` (v2.10).  
**Архив, не очередь работ:** `docs/UNIVERSAL_BOT_CHASSIS_SPEC.md`.  
**Сломанный пример:** `examples/run_example.py` не наращивать; позже заменить на `examples/run_complete_chassis.py`.

---

## 1. Архитектурный принцип: «Один дом»

Один пакет `src/bot_chassis`: кнопки уже стоят, к ним добавлены Storage Contour (мульти-провайдерный), Middleware-защита, Admin, Payments и Access Grants.

### Разделение ответственности трёх независимых портов:
Кузов обращается к портам **сам перед соответствующим действием**. Шасси не склеивает их в один вызов.

| Порт | Отвечает за | НЕ отвечает за |
|---|---|---|
| **`WorkGatePort`** | Рубильник (`is_maintenance`) + тень + бан — **только допуск задачи кузова** | Доступ, дни, оплату. `pre_checkout` этот порт целиком **не** вызывает |
| **`AccessPort`** | Подарочный доступ по времени / Lifetime (`subscriptions`) | Списание штучной задачи |
| **`VoucherManagerPort`** | 1 талон = 1 задача (`transactions`) | Дни и сроки доступа |

Подарочный доступ **не пишется** в `transactions` (нет чека оплаты). Рекуррент Telegram и «SKU, открывающий подписку» — за рамками v1.

Контур `AccessPort` остаётся полностью функциональным даже при `enable_payments=False`.

### Чёрный список (в раму не класть)
Отзывы · витрина · LLM · кризис · скоры · приём произвольного JSON.  
Также не в v1: баланс Stars / кошелёк (только чек → талон), автозапуск анализа, RAM-дашборды, сторонние платежные шлюзы в коде шасси (CryptoBot, ЮKassa — только в кузове), WebApp / кастомные цвета кнопок / математический юникод, Telegram Business (`business_connection`), кнопка админки в Reply-клавиатуре (только `/admin` по роли).  
*(Досье пользователя `/user`, теневой бан `is_shadow_banned` и канал аудита `audit_chat_id` подтверждены архитектором и входят в каноническую спецификацию рамы).*

---

## 2. Базовый конфиг и структура пакетов (`src/bot_chassis`)

### 2.1 Конфиг рамы с тумблерами (`BotChassisConfig`)
```python
@dataclass(slots=True, frozen=True)
class SkuItem:
    sku_code: str
    title: str
    description: str
    stars_price: int

@dataclass(slots=True, frozen=True)
class BotChassisConfig:
    bot_id: str
    enable_buttons: bool = True
    enable_admin: bool = True
    enable_payments: bool = True
    db_path: str = "bot_chassis.db"
    superadmin_ids: tuple[int, ...] = ()      # Посев из CHASSIS_SUPERADMIN_IDS (.env)
    skus: tuple[SkuItem, ...] = ()            # Каталог SKU из конфига, не из кода
    support_chat_id: int | None = None        # Чат поддержки / ошибок
    audit_chat_id: int | None = None          # Канал аудита действий администрации (Audit Trail)
    default_locale: str = "ru"
    
    # Платформенные тумблеры:
    enable_error_alerts: bool = True          # Алерты об ошибках разработчику (включено)
    enable_throttling: bool = True            # Защита от кликеров и флуда (включено)
    notify_on_payment: bool = True            # Мгновенные алерты об оплатах Stars (включено)
    enable_language_switch: bool = False      # Переключатель языков RU/EN (код готов, выключен заглушкой)
    enable_referrals: bool = False            # 1-уровневая рефералка (код готов, выключен заглушкой)
```

### 2.2 Структура пакетов
Фиксированный фасад кнопок (`__init__.py`, `contracts.py`, `keyboards.py`, `lifecycle.py`, `dispatcher.py`, `followup.py`, `commands.py`, `support_bridge.py`, `router.py`) **не переименовывать**.

```
src/bot_chassis/
├── __init__.py                 # Публичный фасад шасси
├── config.py                   # SkuItem, BotChassisConfig
├── contracts.py                # Константы кнопок, callback-префиксы, MenuLabels
├── keyboards.py                # Фабрики Reply и Inline клавиатур
├── lifecycle.py                # UserScreenTracker, CardClosePolicy, edit_or_send
├── dispatcher.py               # ActiveTaskTracker (дедупликация и отмена)
├── followup.py                 # PendingInputStore (TTL 15 мин; SUPPORT_MESSAGE / CUSTOM_INPUT). Рассылка — свой store в admin/broadcast.py
├── commands.py                 # setup_bot_commands (публичные /menu, /help, /support)
├── support_bridge.py           # Мост поддержки (JSON для обратной совместимости тестов)
├── router.py                   # create_button_chassis_router
├── factory.py                  # create_complete_chassis → CompleteChassis (порты наружу; domain_router до кнопок)
├── localization.py             # Хэндлер смены языка core_lang:{code} + build_language_switch_row
│
├── middleware/                 # Сервисные мидлвари в строгом порядке
│   ├── __init__.py
│   ├── error_monitor.py        # 1-й слой: перехват Exception, алерт в саппорт, вежливый ответ
│   ├── throttling.py           # 2-й слой: отсечка спамеров ДО базы (max 4/sec; платежи НЕ режет)
│   └── user_activity.py        # 3-й слой: upsert, first-touch traffic_source и referrals; кэш локали
│
├── ports/                      # Protocol (без I/O) и адаптеры реализации
│   ├── __init__.py
│   ├── work_gate.py            # WorkGatePort + DefaultWorkGateAdapter
│   ├── cabinet.py              # CabinetSlot + адаптер + build_cabinet_renderer (клей к render_cabinet_callback)
│   ├── payments.py             # SkuVoucher, VoucherManagerPort + DefaultVoucherManagerAdapter
│   ├── access.py               # AccessPort + DefaultAccessAdapter
│   ├── referrals.py            # ReferralPort + DefaultReferralAdapter
│   └── storage.py              # Протоколы репозиториев Storage (отложено, не в v1 / не Этап 2)
│
├── storage/                    # Контур данных (SQLite, WAL, мульти-провайдерный)
│   ├── __init__.py
│   ├── engine.py               # WAL, lock, initialize (ALTER users ДО индексов), backup() без BEGIN IMMEDIATE
│   ├── schema.sql              # DDL с обязательным bot_id
│   └── repositories/           # users, roles, transactions, subscriptions, referrals, support_threads, bot_settings
│
├── admin/                      # Скрытый /admin + команды по id + экспорт + рассылка + аудит
│   ├── __init__.py
│   ├── router.py               # /admin, /user, /ban, /unban, /shadowban, /grant, /revoke, /gift, /gift_revoke, /export, /backup, /refund, adm_usr:*
│   ├── filters.py              # AdminRoleFilter, SuperadminRoleFilter
│   ├── export.py               # Экспорт базы в CSV (utf-8-sig для Excel) и ZIP
│   ├── audit.py                # send_admin_audit (логгер в audit_chat_id с try/except и html.escape)
│   └── broadcast.py            # Рассылка (свой RAM-store, 25 msg/s, adm_bcast:stop, фильтр тени)
│
└── payments/                   # Платежи (Stars v1 + мульти-провайдерная схема БД)
    ├── __init__.py
    ├── router.py               # pre_checkout, successful_payment, callback buy_sku:*
    └── service.py              # send_sku_invoice (запрет admin_grant), отдельный платёжный гейт, чек → талон, mark_refunded
```

---

## 3. Таблицы Storage (Цельный DDL `schema.sql`)

Все таблицы содержат поле `bot_id TEXT NOT NULL`. Единый канонический DDL:

```sql
-- 1. Пользователи (хранение профиля, UTM/трафика и отметки 152-ФЗ)
CREATE TABLE IF NOT EXISTS users (
    bot_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    language_code TEXT NOT NULL DEFAULT 'ru',
    is_banned INTEGER NOT NULL DEFAULT 0,
    ban_reason TEXT,
    is_shadow_banned INTEGER NOT NULL DEFAULT 0, -- 1 = тихий сброс спамера (подтверждено архитектором)
    consent_at TEXT,                         -- ISO-8601 отметка 152-ФЗ; сбор согласия — в кузове
    traffic_source TEXT,                     -- UTM/реферальный хвост из /start <payload>; first-touch (не перезаписывается)
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (bot_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_users_bot_banned ON users(bot_id, is_banned);
CREATE INDEX IF NOT EXISTS idx_users_bot_shbanned ON users(bot_id, is_shadow_banned);

-- 2. Роли доступа (строго admin и superadmin)
CREATE TABLE IF NOT EXISTS roles (
    bot_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,                      -- 'admin' | 'superadmin'
    granted_by INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (bot_id, user_id, role),
    FOREIGN KEY (bot_id, user_id) REFERENCES users(bot_id, user_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_roles_lookup ON roles(bot_id, user_id, role);

-- 3. Транзакции и талоны (Мульти-провайдерные поля; v1: Stars)
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    provider TEXT NOT NULL DEFAULT 'telegram_stars', -- 'telegram_stars' | 'yookassa' | 'cryptobot'
    payment_id TEXT NOT NULL,                       -- charge_id / invoice_id
    telegram_payment_charge_id TEXT,                -- Алиас для совместимости со Stars
    provider_payment_charge_id TEXT,
    sku_code TEXT NOT NULL,                         -- Артикул из BotChassisConfig.skus
    amount INTEGER NOT NULL,                        -- Внимание: INTEGER minor-units (целые Stars, копейки RUB). Никаких REAL!
    currency TEXT NOT NULL DEFAULT 'XTR',           -- 'XTR', 'RUB', 'USDT'
    status TEXT NOT NULL DEFAULT 'paid',            -- 'paid' | 'refunded'
    voucher_id TEXT NOT NULL,                       -- Уникальный UUID талона
    voucher_status TEXT NOT NULL DEFAULT 'issued',  -- 'issued' | 'redeemed' | 'cancelled'
    redeemed_at TEXT,                               -- Дата погашения талона кузовом
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (bot_id, provider, payment_id),
    FOREIGN KEY (bot_id, user_id) REFERENCES users(bot_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_tx_bot_user ON transactions(bot_id, user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_voucher ON transactions(bot_id, voucher_id);

-- 4. Доступ и подарочные подписки (Access & Gift Grants)
CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    plan_code TEXT NOT NULL DEFAULT 'default',
    is_lifetime INTEGER NOT NULL DEFAULT 0,    -- 1 = бессрочно (навсегда)
    expires_at TEXT,                           -- ISO-8601 дата истечения (NULL если бессрочно)
    granted_by INTEGER NOT NULL,               -- ID суперадмина
    grant_reason TEXT,                         -- Заметка ('gift', 'friend', 'promo')
    status TEXT NOT NULL DEFAULT 'active',     -- 'active' | 'revoked'
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK ((is_lifetime = 1 AND expires_at IS NULL) OR (is_lifetime = 0 AND expires_at IS NOT NULL)),
    FOREIGN KEY (bot_id, user_id) REFERENCES users(bot_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_subs_user_active ON subscriptions(bot_id, user_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_subs_one_active
    ON subscriptions(bot_id, user_id, plan_code) WHERE status = 'active';

-- 5. Треды поддержки (схема готова, миграция с JSON позже)
CREATE TABLE IF NOT EXISTS support_threads (
    bot_id TEXT NOT NULL,
    support_chat_id INTEGER NOT NULL,
    support_message_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    ticket_status TEXT NOT NULL DEFAULT 'open',  -- 'open' | 'answered' | 'closed'
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (bot_id, support_chat_id, support_message_id),
    FOREIGN KEY (bot_id, user_id) REFERENCES users(bot_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_support_user ON support_threads(bot_id, user_id, ticket_status);

-- 6. Системные настройки и флаги шасси (Рубильник)
CREATE TABLE IF NOT EXISTS bot_settings (
    bot_id TEXT NOT NULL PRIMARY KEY,
    is_maintenance INTEGER NOT NULL DEFAULT 0, -- 1 = рубильник опущен, приём задач остановлен
    maintenance_reason TEXT,                  -- Причина сервисного режима для пользователей
    updated_by INTEGER,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 7. Реферальные связи (1-уровневая виральная система)
CREATE TABLE IF NOT EXISTS referrals (
    bot_id TEXT NOT NULL,
    referrer_id INTEGER NOT NULL,            -- Кто пригласил
    referee_id INTEGER NOT NULL,             -- Кого пригласили
    rewarded INTEGER NOT NULL DEFAULT 0,     -- 1 = бонус выдан (аудит-флаг)
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (bot_id, referee_id),
    CHECK (referrer_id != referee_id),       -- Запрет реферала на самого себя
    FOREIGN KEY (bot_id, referrer_id) REFERENCES users(bot_id, user_id),
    FOREIGN KEY (bot_id, referee_id) REFERENCES users(bot_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(bot_id, referrer_id);
```

### 3.1 Восемь инвариантов подарочного доступа (Access / Gift Grants)
| # | Инвариант | Реализация в коде / схеме |
|---|---|---|
| **1** | Взаимоисключение срока и lifetime | `CHECK ((is_lifetime = 1 AND expires_at IS NULL) OR (is_lifetime = 0 AND expires_at IS NOT NULL))` на уровне SQLite DDL |
| **2** | Ленивая проверка срока действия | Без крон-демонов и фоновых задач: `status = 'active' AND (is_lifetime = 1 OR expires_at > CURRENT_TIMESTAMP)` при чтении |
| **3** | Ровно одна активная запись на пользователя | Частичный уникальный индекс `WHERE status = 'active'`. При выдаче новой подписки старая переводится в `revoked` |
| **4** | Авто-создание профиля (Upsert Stub) | Перед записью подписки вызывается `upsert_user(bot_id, user_id)`, исключая падение по внешнему ключу FK |
| **5** | Единственный тариф в v1 | `plan_code = 'default'`. В v1 нет фиктивных `'pro'/'vip'`; тариф строго один |
| **6** | Полный жизненный цикл (Grant + Revoke) | Симметричные методы: выдача `/gift` (`grant_gift_access`) и отзыв `/gift_revoke` (`revoke_gift_access`) |
| **7** | Ограничение прав (Только Superadmin) | Выдавать и отзывать подарки разрешено строго роли `superadmin` |
| **8** | Политика бана и тени | Забаненному и тене-баненному пользователю технически можно подарить доступ, но `WorkGatePort.can_accept_work` и `UserActivityMiddleware` продолжат блокировать задачи до снятия бана/тени |

### 3.2 Слот Личного Кабинета (`CabinetSlot`)
Интерфейс `CabinetSlotsProviderPort` позволяет шасси и доменному кузову динамически наполнять экран «Личный кабинет»:
* **Слот 1 (Профиль):** `ID: {user_id} | @{username} | Зарегистрирован: {created_at}`
* **Слот 2 (Доступ):** 
  - Если активен бессрочный подарок: `🎁 Доступ: VIP (Бессрочно)`
  - Если активен срочный подарок: `🎁 Доступ: VIP (до {expires_at})`
  - Иначе: `Доступ: Базовый`
* **Слот 3 (Талоны / Квоты):** `🎟 Доступно талонов: {count}` (при `enable_payments=True`)
* **Слот 4 (Рефералы):** `👥 Приглашено друзей: {count} | Ваша ссылка: https://t.me/{bot}?start=ref_{user_id}` (при `enable_referrals=True`)

### 3.3 Ключевое правило: «Upsert не затирает язык»
В `UsersRepository.upsert_user` при конфликте `(bot_id, user_id)` колонка `language_code` **НЕ** обновляется:
```sql
ON CONFLICT(bot_id, user_id) DO UPDATE SET
    username = COALESCE(excluded.username, users.username),
    first_name = COALESCE(excluded.first_name, users.first_name),
    last_name = COALESCE(excluded.last_name, users.last_name),
    language_code = users.language_code, -- НЕ перезаписывать язык из Telegram!
    updated_at = excluded.updated_at
```
Сменить язык в базе данных может **только** специализированный метод `set_language_code(bot_id, user_id, code)`.

`set_traffic_source` пишет хвост **только если колонка пуста** (first-touch). Успешная рефералка `ref_{id}` тоже сохраняет payload в `traffic_source`, чтобы досье «Источник / Реф» не было пустым.

`set_shadow_ban(..., True)` на пользователя с ролью `admin` или `superadmin` возвращает `(False, "target_is_admin")`. Код `"last_superadmin"` принадлежит `set_ban` / `revoke_role`, в тень его не копировать. Снятие тени разрешено всегда.

---

## 4. Матрица состояний Рубильника и Блокировок (Gate & Ban Matrix)

| Действие / Компонент | Состояние: `is_maintenance == 0` | Состояние: `is_maintenance == 1` (Рубильник опущен) | Статус: `is_banned == 1` (Обычный бан) | Статус: `is_shadow_banned == 1` (Теневой бан) |
|---|---|---|---|---|
| **`/admin` и админ-команды** | Разрешено | **Разрешено** (админ обязан иметь доступ для снятия) | Заблокировано (кроме защиты последнего суперадмина) | **Разрешено** (админ не может заблокировать себе админку) |
| **Навигация кнопок (`/menu`, `/help`)** | Разрешено | **Разрешено** (пользователь не видит «мёртвого» бота) | Разрешено (кнопки отвечают) | **Дроп в Middleware** (`return None`, тишина) |
| **Покупка SKU (`buy_sku:*`)** | Разрешено | **Заблокировано** (выводится `maintenance_reason`) | Разрешено / по усмотрению кузова | **Дроп в Middleware** (`return None`, тишина) |
| **Проверка платежа (`pre_checkout`)** | Подтверждается (`ok=True`) | **Отклоняется** (`ok=False`) | Подтверждается (`ok=True`) | **Отклоняется** (`ok=False`) |
| **Оплаченный чек (`successful_payment`)** | Чек пишется, талон выдаётся | **Чек пишется, талон выдаётся** | Чек пишется, талон выдаётся | Чек пишется, талон выдаётся |
| **Задача кузова (`can_accept_work`)** | Возвращает `(True, None)` | **Возвращает `(False, reason)`** | **Возвращает `(False, ban_reason)`** (открытый бан) | **Возвращает `(False, None)`** (БЕЗ причины, маска цела) |

> [!NOTE]
> **Ортогональность подарков и банов (Инвариант 8):** Пользователю с `is_banned = 1` или `is_shadow_banned = 1` дарить доступ разрешено (запись подписки создаётся). Однако `WorkGatePort.can_accept_work` и `UserActivityMiddleware` продолжают блокировать выполнение задач кузова до тех пор, пока бан не будет снят администратором.
>
> **Платежный гейт ≠ WorkGate.** `pre_checkout` проверяет рубильник и тень отдельно. Обычный `is_banned` на `pre_checkout` отвечает `ok=True` (колонка матрицы). Вызов `WorkGatePort.can_accept_work()` целиком в платежах запрещён: он режет бан и может показать `ban_reason` в UI Telegram. `successful_payment` всегда пишет чек (Stars уже списаны), в том числе при рубильнике, бане и тени. `ThrottlingMiddleware` не режет `pre_checkout_query` и `Message.successful_payment`.

---

## 5. Порты и Адаптеры (Clean Architecture)

Каждый порт объявляется как `Protocol` в `src/bot_chassis/ports/`, а его базовая реализация над Storage — как адаптер в `src/bot_chassis/ports/`.

### 5.1 WorkGate
```python
class WorkGatePort(Protocol):
    async def can_accept_work(self, bot_id: str, user_id: int) -> tuple[bool, str | None]: ...

class DefaultWorkGateAdapter(WorkGatePort):
    def __init__(self, settings_repo: BotSettingsRepository, users_repo: UsersRepository):
        self._settings = settings_repo
        self._users = users_repo

    async def can_accept_work(self, bot_id: str, user_id: int) -> tuple[bool, str | None]:
        is_maint, reason = await self._settings.get_maintenance_status(bot_id)
        if is_maint:
            return False, reason or "Сервис временно приостановлен."
        user = await self._users.get_user(bot_id, user_id)
        if user:
            if user.is_shadow_banned:
                return False, None  # Тень ПЕРВОЙ! БЕЗ причины: кузов не показывает 'Вы забанены', маска спамера цела
            if user.is_banned:
                return False, user.ban_reason or "Доступ к сервису ограничен."
        return True, None
```

### 5.2 AccessPort (8 инвариантов подписок)
```python
class AccessPort(Protocol):
    async def has_active_access(self, bot_id: str, user_id: int, plan_code: str = "default") -> bool: ...
    async def grant_gift_access(self, bot_id: str, user_id: int, granted_by: int, days: int | None = None, plan_code: str = "default", reason: str = "gift") -> tuple[bool, str | None]: ...
    async def revoke_gift_access(self, bot_id: str, user_id: int, plan_code: str = "default") -> tuple[bool, str | None]: ...

class DefaultAccessAdapter(AccessPort):
    def __init__(self, subs_repo: SubscriptionsRepository):
        self._subs = subs_repo

    async def has_active_access(self, bot_id: str, user_id: int, plan_code: str = "default") -> bool:
        return await self._subs.has_active_access(bot_id, user_id, plan_code=plan_code)

    async def grant_gift_access(self, bot_id: str, user_id: int, granted_by: int, days: int | None = None, plan_code: str = "default", reason: str = "gift") -> tuple[bool, str | None]:
        return await self._subs.grant_gift_access(bot_id, user_id, granted_by=granted_by, days=days, plan_code=plan_code, reason=reason)

    async def revoke_gift_access(self, bot_id: str, user_id: int, plan_code: str = "default") -> tuple[bool, str | None]:
        return await self._subs.revoke_gift_access(bot_id, user_id, plan_code=plan_code)
```

### 5.3 VoucherManagerPort
```python
@dataclass(slots=True, frozen=True)
class SkuVoucher:
    voucher_id: str
    bot_id: str
    user_id: int
    sku_code: str
    payment_id: str
    amount: int  # minor-units (целые Stars, копейки)
    currency: str
    status: str  # 'issued' | 'redeemed' | 'cancelled'
    redeemed_at: str | None = None

class VoucherManagerPort(Protocol):
    async def get_active_vouchers(self, bot_id: str, user_id: int, sku_code: str | None = None) -> Sequence[SkuVoucher]: ...
    async def redeem_voucher(self, bot_id: str, user_id: int, voucher_id: str) -> tuple[bool, str | None]: ...

class SkuVoucherConsumerPort(Protocol):
    async def on_voucher_issued(self, voucher: SkuVoucher) -> None: ...

class DefaultVoucherManagerAdapter(VoucherManagerPort):
    def __init__(self, tx_repo: TransactionsRepository):
        self._tx = tx_repo

    async def get_active_vouchers(self, bot_id: str, user_id: int, sku_code: str | None = None) -> Sequence[SkuVoucher]:
        records = await self._tx.get_active_vouchers(bot_id, user_id, sku_code=sku_code)
        return [
            SkuVoucher(
                voucher_id=r.voucher_id,
                bot_id=r.bot_id,
                user_id=r.user_id,
                sku_code=r.sku_code,
                payment_id=r.payment_id,
                amount=r.amount,
                currency=r.currency,
                status=r.voucher_status,
                redeemed_at=r.redeemed_at,
            )
            for r in records
        ]

    async def redeem_voucher(self, bot_id: str, user_id: int, voucher_id: str) -> tuple[bool, str | None]:
        return await self._tx.redeem_voucher(bot_id, user_id, voucher_id)
```

### 5.4 ReferralPort
```python
class ReferralPort(Protocol):
    async def record_referral(self, bot_id: str, referrer_id: int, referee_id: int) -> tuple[bool, str | None]: ...
    async def get_referrals_count(self, bot_id: str, referrer_id: int) -> int: ...

class DefaultReferralAdapter(ReferralPort):
    def __init__(self, referrals_repo: ReferralsRepository):
        self._referrals = referrals_repo

    async def record_referral(self, bot_id: str, referrer_id: int, referee_id: int) -> tuple[bool, str | None]:
        return await self._referrals.record_referral(bot_id, referrer_id, referee_id)

    async def get_referrals_count(self, bot_id: str, referrer_id: int) -> int:
        return await self._referrals.get_referrals_count(bot_id, referrer_id)
```

### 5.5 CabinetSlotsProviderPort
```python
@dataclass(slots=True, frozen=True)
class CabinetSlot:
    slot_id: str
    title: str
    content: str
    buttons: tuple = ()

class CabinetSlotsProviderPort(Protocol):
    async def get_cabinet_slots(self, bot_id: str, user_id: int) -> Sequence[CabinetSlot]: ...

class DefaultCabinetSlotsAdapter(CabinetSlotsProviderPort):
    def __init__(
        self,
        subs_repo: SubscriptionsRepository,
        tx_repo: TransactionsRepository,
        users_repo: UsersRepository | None = None,
        referrals_repo: ReferralsRepository | None = None,
        bot_username: str = "",
        enable_payments: bool = True,
        enable_referrals: bool = False,
    ):
        self._subs = subs_repo
        self._tx = tx_repo
        self._users = users_repo
        self._referrals = referrals_repo
        self._bot_username = bot_username
        self._enable_payments = enable_payments
        self._enable_referrals = enable_referrals

    async def get_cabinet_slots(self, bot_id: str, user_id: int) -> Sequence[CabinetSlot]:
        slots: list[CabinetSlot] = []
        # Слот 1: Профиль (§3.2) — ID всегда, username если есть
        if self._users:
            u = await self._users.get_user(bot_id, user_id)
            if u:
                uname = f"@{u.username}" if u.username else "—"
                reg_date = u.created_at[:10] if u.created_at else "—"
                slots.append(CabinetSlot(
                    "profile", "Профиль",
                    f"ID: {u.user_id} | {uname} | Зарегистрирован: {reg_date}",
                ))
        # Слот 2: Доступ — бессрочно / до даты / базовый
        sub = await self._subs.get_active_subscription(bot_id, user_id)
        if sub and sub.is_lifetime:
            access_text = "🎁 Доступ: VIP (Бессрочно)"
        elif sub and sub.expires_at:
            access_text = f"🎁 Доступ: VIP (до {sub.expires_at[:10]})"
        else:
            access_text = "Доступ: Базовый"
        slots.append(CabinetSlot("access", "Доступ", access_text))
        # Слот 3: Талоны — только enable_payments
        if self._enable_payments:
            vouchers = await self._tx.get_active_vouchers(bot_id, user_id)
            slots.append(CabinetSlot("vouchers", "Талоны", f"🎟 Доступно талонов: {len(vouchers)}"))
        # Слот 4: Рефералы — только тумблер + репозиторий
        if self._enable_referrals and self._referrals:
            refs = await self._referrals.get_referrals_count(bot_id, user_id)
            link = f"https://t.me/{self._bot_username}?start=ref_{user_id}" if self._bot_username else f"ref_{user_id}"
            slots.append(CabinetSlot("referrals", "Рефералы", f"👥 Приглашено друзей: {refs} | Ваша ссылка: {link}"))
        return slots
```

Клей к неизменному `render_cabinet_callback` Button Chassis — `build_cabinet_renderer(adapter, bot_id)` (см. план v2.10, Задача 2.2). Фабрика Этапа 5 обязана его передать, иначе экран кабинета останется заглушкой шасси.

---

## 6. Админка: скрытый `/admin`, выгрузка в Excel и безопасная рассылка (Этап 3)

### 6.1 Главный экран `/admin`
* Доступ строго по ролям `admin` или `superadmin`.
* Экспресс-сводка: число пользователей (всего/бан), оплаты (сумма), активные подарки, рубильник.
* Инлайн-кнопки (без подвешивания FSM-стейтов):
  `[🔴/🟢 Переключить рубильник]`
  `[📥 Выгрузка базы (Excel)]`
  `[📢 Новая рассылка]`

### 6.2 Прямые команды с аргументом ID (без зависания стейтов):
* `/user <user_id>` — карточка досье пользователя с кнопками действий в один тап.
* `/ban <user_id> [причина]` и `/unban <user_id>` (защита последнего суперадмина).
* `/shadowban <user_id> [0|1]` — управление теневым баном. Наложение на любого `admin`/`superadmin` запрещено (`target_is_admin`). Снятие тени разрешено.
* `/grant <user_id> <role>` и `/revoke <user_id> <role>` (только `superadmin`, обязательный аргумент роли, защита последнего).
* `/gift <user_id> [days]` и `/gift_revoke <user_id>` (только `superadmin`, дни опциональны: без дней = lifetime).
* `/export [users|payments|gifts|all]` — **строго для роли `superadmin`** (защита персональных данных 152-ФЗ). Генерация CSV (`utf-8-sig`) и ZIP без внешних библиотек.
* `/broadcast` — безопасная рассылка от имени бота (троттлинг 25 msg/s, Bot API, изолированный store в `admin/broadcast.py` без пересечения с `PendingInputKind` поддержки, предпросмотр, отчёт, кнопка экстренной остановки).
* `/backup` — снапшот через публичный `StorageEngine.backup(dest_path)` (WAL-safe, без `BEGIN IMMEDIATE`) и отправка `.db` вызывающему суперадмину.
* `/refund <charge_id>` или `/refund <user_id> <payment_id>` — официальный возврат Stars через `bot.refund_star_payment` с переводом талона в `cancelled` (только для платежей `telegram_stars`).
* `/maintenance [on|off] [причина]` — управление рубильником.

### 6.3 Интерактивное досье пользователя (`/user <user_id>`) [Подтверждено архитектором]
Позволяет администратору мгновенно просмотреть профиль и совершить действия в 1 клик:
* **Доступ к просмотру:** разрешён ролям `admin` и `superadmin`.
* **Формат карточки:**
  ```text
  👤 Досье пользователя: @username (ID: {user_id})
  Имя: {first_name} {last_name}
  📅 Первый визит: {created_at} UTC
  🌐 Язык: {language_code} | Источник / Реф: {traffic_source}
  🔒 Статус: {Активен | Забанен} (Теневой бан: {ДА | НЕТ})
  👑 Роли: {roles}
  🎁 VIP Доступ: {Бессрочно | до YYYY-MM-DD | Отсутствует}
  🎟 Талоны: {active_vouchers_count} шт. (Оплат всего: {total_payments})
  👥 Пригласил рефералов: {referrals_count}
  ```
* **Инлайн-клавиатура и разграничение прав (Инвариант 7):**
  - `[ 🔴 Забанить ]` / `[ 🟢 Разбанить ]` (callback: `adm_usr:ban:{id}`) — доступно `admin` и `superadmin`.
  - `[ 👻 Теневой бан: ВКЛ/ВЫКЛ ]` (callback: `adm_usr:shban:{id}`) — доступно `admin` и `superadmin`.
  - `[ 🎁 +30 дней VIP ]` (callback: `adm_usr:gift30:{id}`) — **строго `superadmin`**. При клике обычного `admin` выдаётся всплывающий тост `show_alert=True, text="Только для суперадмина"`.
    - Вызывает `grant_gift_access(days=30)` с **заменой** активного ряда (старая подписка в `revoked`, новая на 30 дней от текущего момента; сроки НЕ суммируются).
  - `[ 🎟 +1 талон ]` (callback: `adm_usr:addvouch:{id}`) — **строго `superadmin`**.
    - Админская эмиссия талона в ту же таблицу транзакций:
      `provider = 'admin_grant'`, `payment_id = f'admin:{uuid.uuid4()}'`, `telegram_payment_charge_id = payment_id`, `amount = 0`, `currency = 'XTR'`, `sku_code = 'admin_grant'`.
      Вызов `record_successful_payment(...)` $\rightarrow$ `(record, created)`. При `created is True` вызывается аудит.
  - `[ 👑 Роль Admin ]` / `[ 🚫 Снять Admin ]` (callback: `adm_usr:role_adm:{id}`) — **строго `superadmin`**.
  - `[ « Главное меню админки ]` (callback: `adm_home`) — возврат на экран сводки `/admin`.
* **Защита ролей с досье:** банить и снимать роль у **последнего** активного суперадмина запрещено (алерт `show_alert=True`). Теневой бан с карточки на любого `admin`/`superadmin` запрещён (`target_is_admin`), не только на последнего суперадмина.
* **Обновление экрана:** После выполнения колбэка карточка обновляется на месте через `edit_text` (Reply-клавиатур здесь нет, `editMessageText` полностью валиден) + вызывается `send_admin_audit`.

### 6.4 Теневой бан (Shadow-ban) [Подтверждено архитектором]
* Метод репозитория: `UsersRepository.set_shadow_ban(bot_id, user_id, is_shadow_banned: bool)`.
  - Наложение тени на `admin` / `superadmin` запрещено: `(False, "target_is_admin")`. Код `"last_superadmin"` сюда не ставится (он у `set_ban` / `revoke_role`).
  - Снятие тени разрешено всегда, в том числе админам.
* Метод проверки в адаптере: `WorkGatePort.can_accept_work` проверяет `is_shadow_banned` **первым** и возвращает `(False, None)` (без текста причины).
* Поведение в `UserActivityMiddleware` (Bot API 7.x правила):
  1. Вызывается **после** `upsert_user` (факт активности зафиксирован в БД).
  2. **Иммунитет администрации:** если пользователь имеет роль `admin` или `superadmin`, теневой бан его **не** сбрасывает (администратор не может случайно заблокировать себе админку).
  3. **Платёжные события НЕ дропаются:** события `PreCheckoutQuery` и сообщения с `successful_payment` **пропускаются** в платёжный роутер!
     - `successful_payment`: деньги уже списаны Telegram, чек обязан записаться в базу данных, а талон выдан (сохранение целостности оплат).
     - `PreCheckoutQuery`: если пользователь тене-банен, платёжный роутер отвечает в течение 10 секунд нейтральным `ok=False` (например, «Оплата временно недоступна», без слова «бан»), предотвращая зависание клиента.
  4. **Сброс CallbackQuery:** пустой `await event.callback_query.answer()` (event — `Update`), затем `return None`. Это предотвращает вечную анимацию часов и ошибку `QUERY_ID_INVALID`.
  5. **Сброс обычных сообщений:** `return None` без ответа пользователю.

### 6.5 Канал аудита действий администрации (Audit Trail Channel, `admin/audit.py`) [Подтверждено архитектором]
* Создаётся выделенный модуль `src/bot_chassis/admin/audit.py` с хелпером `send_admin_audit(bot: Bot, config: BotChassisConfig, text: str) -> None`.
* **Требование Bot API:** Бот обязан быть добавлен в канал `audit_chat_id` в статусе **администратора с правом отправки сообщений**.
* **Экранирование:** Все пользовательские строки (`@username`, причины бана/подарка) экранируются через `html.escape`, чтобы символы `<` или `>` не ломали режим `parse_mode="HTML"`.
* **Защита от сбоев:** Отправка лога в канал аудита ОБЯЗАТЕЛЬНО оборачивается в `try...except Exception: logger.exception(...)`. Сбой сети или Telegram в канале аудита **никогда не прерывает** саму админ-команду.
* Логируются: бан/разбан (включая досье), теневой бан, выдача/отзыв подарка, выдача талона `[🎟 +1 талон]`, смена роли, переключение рубильника, старт/стоп рассылки, экспорт базы.

### 6.6 Безопасная рассылка с кнопкой экстренной остановки (`admin/broadcast.py`)
* Скорость отправки: 25 сообщений в секунду с экспоненциальным backoff при `RetryAfter`.
* **Фильтрация получателей:** метод `UsersRepository.get_broadcast_user_ids(bot_id)` исключает пользователей с `is_shadow_banned = 1` и `is_banned = 1` (`SELECT user_id FROM users WHERE bot_id = ? AND is_banned = 0 AND is_shadow_banned = 0`), чтобы для заблокированных пользователей и спамеров под тенью бот оставался строго «мёртвым».
* Состояние ввода текста живёт в `admin/broadcast.py` (изолированный RAM-store по `user_id`). В `PendingInputKind` Button Chassis ключ рассылки **не** добавляется.
* Предпросмотр текста перед стартом.
* Во время рассылки админ видит статус-сообщение с прогрессом и инлайн-кнопкой `[🛑 Экстренно остановить]` (колбэк `adm_bcast:stop`).
* Нажатие на кнопку взводит флаг отмены цикла рассылки без усложнения FSM-машины, процесс плавно завершается, в чат админа выводится итоговый отчёт (доставлено/ошибок/остановлено), а в канал аудита направляется уведомление.

---

## 7. Платежи v1: Telegram Stars (Этап 4)

В v1 контур платежей реализует **строго Telegram Stars** через официальный Bot API 7.x:
* Никаких внешних HTTP-серверов или сторонних провайдеров (CryptoBot, ЮKassa) в коде v1 нет.
* Схема базы данных содержит поля `provider` и `payment_id` для совместимости, но в v1 `provider = 'telegram_stars'`.
* **Параметры инвойса Stars (`send_invoice`):**
  - `currency = "XTR"`
  - `provider_token = ""` (пустая строка согласно спецификации Telegram Stars)
  - `LabeledPrice.amount = item.stars_price` (целое число Stars, **НЕ** умножать на 100!)
  - `payload = f"sku:{sku_code}:{user_id}:{uuid.uuid4().hex[:8]}"` с проверкой `len(payload.encode('utf-8')) <= 128`
  - `is_flexible = False`
* **Эмиссия талонов администратора (`sku_code='admin_grant'`):**
  - Не требует наличия в `config.skus` каталога; разрешена только через инлайн-досье `/user` для роли `superadmin`.
* **Возврат платежей (`/refund <charge_id>` или `/refund <user_id> <payment_id>`):**
  - Официальный возврат Stars через Bot API `bot.refund_star_payment(user_id=user_id, telegram_payment_charge_id=payment_id)`.
  - Разрешён только для транзакций с `provider == 'telegram_stars'`. Админские талоны `admin_grant` туда не передаются.
* **Поток обработки оплаты:**
  1. `pre_checkout_query` — **отдельный платёжный гейт, не** `WorkGatePort.can_accept_work()`:
     - Рубильник опущен $\rightarrow$ `ok=False` с `maintenance_reason`.
     - Тень $\rightarrow$ `ok=False`, текст «Оплата временно недоступна» (без слова «бан»).
     - Обычный бан $\rightarrow$ `ok=True`.
     - `user_id` в payload должен совпасть с `from_user.id`.
     - Иначе `ok=True`. Ответ за 10 секунд.
  2. `buy_sku:*` / `send_sku_invoice` отвергают `sku_code='admin_grant'` и SKU вне `config.skus`.
  3. `successful_payment`:
     - `sku_code` берётся из `invoice_payload` (`sku:{sku_code}:{user_id}:{nonce}`), не из полей `SuccessfulPayment`.
     - Вызывается `storage.transactions.record_successful_payment(...)`.
     - Метод возвращает `(record, created: bool)`.
     - Только если `created is True` и передан `voucher_consumer`: `on_voucher_issued(voucher)` и алерт в `support_chat_id` (при `notify_on_payment=True`).
     - Если `created is False`: повторный вебхук игнорируется (идемпотентность).
     - Чек пишется даже при рубильнике, бане и тени (Stars уже списаны).
  4. Возврат: сначала `refundStarPayment` в `try/except TelegramBadRequest`; при отказе Telegram `mark_refunded` **не** вызывать. Успех → `mark_refunded`. Талоны `admin_grant` в Bot API не передаются.

---

## 8. Порядок реализации

1. **Storage Contour & Config**: **ГОТОВО** (дополняется Задачей 2.0 по плану v2.10: ALTER users **до** индексов, пересбор `transactions`, `backup()`, `mark_refunded`).
2. **Clean Ports, Middleware & Localization (Этап 2)**: атомарно 2.0 → 2.5 плана v2.10 (`build_cabinet_renderer`, payload `/start` внутри `if`, whitelist платежей).
3. **Admin Chassis (Этап 3)**: план v2.10 (`engine.backup`, refund try/except).
4. **Payment Chassis v1 Stars (Этап 4)**: `sku_code` из `invoice_payload`, consumer опционален.
5. **Единая фабрика и раннер (Этап 5)**: `CompleteChassis`, кузовной роутер до кнопок, порты на возвращаемом объекте.
