# Bot Chassis — канон v1

**Статус:** полная рама `0.3.0` (операционный контур). Git-тег — после B6 и команды владельца.
**Корень:** `C:\Python\bot_chassis`  
**Пакет:** `src/bot_chassis`  
**Платформа:** Python 3.10+ (разработка на 3.14), aiogram 3.13+, SQLite WAL  
**Тесты:** `pytest tests/`; кнопочный контракт `tests/test_chassis.py` заморожен.

Это рабочий факт рамы: как подключить, что внутри открыто, что заглушка с портом, чего в v1 нет.  
История версий: [CHANGELOG.md](../CHANGELOG.md). История проектирования лежит в [archive/](archive/README.md) и **не** является очередью работ.

Шлюз `src/bot_chassis/bot_gateway.py` и сигнатуры Button Chassis не менять.

---

## 1. Что это

Шасси — несущая рама Telegram-бота. Кузов (PsyBot, Profiling, Chat Listener, любой новый домен) монтируется на неё и сам вызывает порты **перед** своей работой. Рама кузов не запускает.

В v1 внутри одного пакета:

| Контур | Состояние |
|---|---|
| Button Chassis | Готово, контракт заморожен |
| Storage Contour | Готово, SQLite WAL, изоляция `bot_id` |
| Порты и middleware | Готово |
| Admin Chassis | Готово |
| Payment Chassis v1 | Готово, только Telegram Stars (XTR) |
| Фабрика полной рамы | Готово: `create_complete_chassis` |

В раму не класть: опросники, LLM, скоры, витрины, ЮKassa/CryptoBot, кризисные протоколы.

---

## 2. Подключение

Нормальный путь — полная рама. Кнопки отдельно оставляют только если админка и оплата не нужны.

```python
from aiogram import Bot, Dispatcher, Router
from bot_chassis.config import BotChassisConfig, SkuItem
from bot_chassis.factory import create_complete_chassis
from bot_chassis.commands import register_button_chassis_startup
from bot_chassis.user_lifecycle import CANON_ALLOWED_UPDATES

config = BotChassisConfig(
    bot_id="shop",
    db_path="shop.db",
    superadmin_ids=(108234567,),
    support_chat_id=-1001234567890,
    audit_chat_id=-1001234567891,
    origin_bot_id=None,
    support_thread_id=None,
    audit_thread_id=None,
    ops_thread_id=None,
    events_thread_id=None,
    skus=(SkuItem("vip", "VIP", "Месяц", 150),),
    enable_referrals=True,
    welcome_text=None,  # None → стандартное HTML-меню шасси
)

async def main(bot: Bot) -> None:
    domain = Router(name="body")
    chassis = await create_complete_chassis(
        bot,
        config,
        domain_router=domain,
        domain_rows=(("📊 Задачи",),),
        voucher_consumer=None,          # заглушка: чек пишется, кузов не зовут
        cabinet_provider=None,          # дефолтные слоты кабинета
        vouchers_provider=None,         # keyword-only, дефолтный адаптер
        referrals_provider=None,
        project_label="Shop",
        render_info_callback=None,
        extra_admin_actions=None,
        thread_store=None,               # None + постоянный db_path → SQLite; :memory: и явный JSON — одноразовый legacy
        extra_support_inline=None,
        pending_store=None,               # None → штатный PendingInputStore
        before_chassis_menu_action=None,
        extra_user_dossier_lines=None,
        extra_user_dossier_rows=None,
        backup_policy=None,               # None → без ночного ZIP
        reporting_policy=None,            # None → без вечернего отчёта
        process_control=None,             # None → кнопки рестарта нет
    )
    register_button_chassis_startup(chassis.dp, bot)
    await chassis.dp.start_polling(bot, allowed_updates=list(CANON_ALLOWED_UPDATES))
```

Эталон: [`examples/run_complete_chassis.py`](../examples/run_complete_chassis.py), переменные — [`examples/.env.example`](../examples/.env.example).

Polling и webhook передают `my_chat_member` в `allowed_updates`. Это событие не ограничивается throttling, поэтому блокировка не теряется после серии быстрых апдейтов. Если кузов передал в фабрику свой список без `my_chat_member`, старт пишет предупреждение. Статус `active` / `stopped` / `deleted` хранится отдельно для каждого фактического бота. Бан и теневой бан остаются санкцией всей сети. Нет ряда — статус `unknown`. Первый подтверждённый запуск в этом боте один раз пишет событие в events-тему, даже если перед `/start` пришёл active `my_chat_member`; повторный `/start` его не повторяет. Реальные изменения lifecycle тоже дают одно events-событие, одинаковые повторные updates молчат.

Только кнопки: `create_button_chassis_router` из `bot_chassis` и [`examples/run_example.py`](../examples/run_example.py). Этот пример не наращивать.

### Порядок роутеров (кто видит апдейт раньше)

1. Admin  
2. Payments  
3. Localization  
4. **Domain (кузов)**  
5. `/start` шасси  
6. Button Chassis

Кузов ставят **до** кнопок, иначе `F.text` меню перехватит доменные подписи.

### Что кузов обязан делать сам

```python
allowed, reason = await chassis.work_gate.can_accept_work(bot_id, user_id)
if not allowed:
    if reason:
        await message.answer(reason)  # тень: reason is None — тишина
    return
ok = await chassis.access.has_active_access(bot_id, user_id)
vouchers = await chassis.vouchers.get_active_vouchers(bot_id, user_id)
await chassis.vouchers.redeem_voucher(bot_id, user_id, voucher_id)
```

Шасси не вызывает `can_accept_work` за кузов. Платежный `pre_checkout` этот порт **не** использует.

---

## 3. Конфиг и тумблеры

`BotChassisConfig` (`src/bot_chassis/config.py`), frozen dataclass. Обязателен только `bot_id`.

| Поле | Дефолт | Смысл |
|---|---|---|
| `bot_id` | — | Арендатор во всех таблицах |
| `db_path` | `bot_chassis.db` | SQLite |
| `superadmin_ids` | `()` | Посев при `create_storage` |
| `skus` | `()` | Каталог Stars |
| `support_chat_id` | `None` | Тикеты поддержки |
| `audit_chat_id` | `None` | Закрытый служебный чат суперадминов. Имя переменной остаётся `AUDIT_CHAT_ID`. Если не задан, ошибки и оплаты падают в общий `support_chat_id` без audit/ops/events thread ID |
| `support_thread_id` | `None` | Тема обращений. `None` — общий чат, аргумент `message_thread_id` не передаётся |
| `audit_thread_id` | `None` | Тема действий администратора и оплат |
| `ops_thread_id` | `None` | Тема ошибок, рестартов и бэкапа |
| `events_thread_id` | `None` | Тема новых пользователей, статусов и отчётов |
| `welcome_text` | `None` | Текст носителя Reply-клавиатуры на `/start`. При выключенном переключателе языка и без `render_start_callback` остаётся прежний HTML шасси. При включённом переключателе носитель отделён от стартовой карточки с toggle |
| `default_locale` | `"ru"` | ru / en |
| `enable_buttons` | `True` | Нижнее меню |
| `enable_admin` | `True` | `/admin` и команды |
| `enable_payments` | `True` | Stars |
| `enable_throttling` | `True` | 5 апдейтов/с, whitelist платежей |
| `enable_error_alerts` | `True` | Падения в `audit_chat_id or support_chat_id` |
| `notify_on_payment` | `True` | Алерт об оплате в `audit_chat_id or support_chat_id` |
| `enable_language_switch` | `False` | Колбэк `core_lang:*` |
| `enable_referrals` | `False` | `/start ref_<id>` и слот кабинета |
| `origin_bot_id` | `None` | Логическое имя origin; `None` → значение `bot_id` |

Переменные окружения канона: `SUPPORT_CHAT_ID`, `AUDIT_CHAT_ID` и опциональные
`SUPPORT_THREAD_ID`, `AUDIT_THREAD_ID`, `OPS_THREAD_ID`, `EVENTS_THREAD_ID`.
Золотой набор — [`examples/.env.example`](../examples/.env.example). Кузов
копирует его и добавляет свои ключи. Ночной бэкап и вечерний отчёт — не env,
а `BackupPolicy` / `ReportingPolicy` на фабрике.

`BackupPolicy`: каталог ZIP, пояс UTC+5, слот 04:00, ротация 14 daily / 8 weekly.
`None` — автоматики нет, ручной `/backup` как раньше.

`ReportingPolicy`: слот 23:30 UTC+5 в events; ошибка доставки — в ops.
`None` — без вечерних отчётов.

---

## 4. Точки монтирования (открыто / заглушка / подмена)

Фабрика всегда собирает рабочую раму. Часть узлов можно заменить, часть — нет.

### Подменяются через аргументы фабрики

| Аргумент | Если `None` | Зачем кузову |
|---|---|---|
| `dp` | новый `Dispatcher()` | Свой диспетчер |
| `storage` | `create_storage(config)` | Общая БД |
| `domain_router` | не включается | Команды и кнопки кузова |
| `domain_rows` | нет доменных рядов | Подписи нижнего меню |
| `cabinet_provider` | `DefaultCabinetSlotsAdapter` | Свои слоты кабинета |
| `vouchers_provider` | `DefaultVoucherManagerAdapter` | Свой склад талонов |
| `referrals_provider` | `DefaultReferralAdapter` | Своя рефералка |
| `voucher_consumer` | **тишина** | Хук «талон выдан»; чек в БД всё равно пишется |
| `project_label` | `"Сервис"` | Название проекта в карточке поддержки |
| `render_info_callback` | `None` | Рендер кузовной карточки Info |
| `extra_admin_actions` | `None` | Ряды `home_rows()` только у root. Клики staff по extra-кнопкам досье остаются |
| `thread_store` | SQLite при постоянном `db_path` | Явный JSON остаётся одноразовым. SQLite: `open → in_progress → closed`, без текста сообщений |
| `extra_support_inline` | пусто | Дополнительные кнопки на форме запроса. Донатные SKU туда больше не подставляются |
| `pending_store` | `PendingInputStore()` | Тот же объект в `CompleteChassis.pending_store`. Scope `user_navigation` не стирает админский поиск |
| `before_chassis_menu_action` | ничего не вызывать | `async (user_id)` перед Кабинетом, Info и Поддержкой |
| `extra_user_dossier_lines` | старый текст `/user` | Доп. строки внизу досье; `callable(user_id) -> sequence[str]` |
| `extra_user_dossier_rows` | старые кнопки `/user` | Ряды кнопок перед «Назад» / «В главное меню»; клики — `extra_admin_actions` |
| `render_start_callback` | `None` | Единый стартовый экран кузова. `ChassisScreen` рама отправляет и отслеживает второй карточкой; возвращённый `Message` тоже отслеживается. При `None` и включённом языке рама сама даёт безопасную двуязычную карточку с toggle |
| `on_locale_changed` | `None` | После ручной смены языка. `None` — рама обновляет только свои экраны |
| `initial_locale_policy` | группа RU из плана | Базовые коды Telegram, которые дают `ru`; остальное → `en` |
| `initial_locale_resolver` | `None` | Замена политики. `None` — штатный разбор `language_code` |
| `bot_display_name_provider` | `None` | Подпись бота в досье и событии первого запуска. `None` — `origin_bot_id` |
| `allowed_updates` | `None` | Список кузова для диагностики. Без `my_chat_member` старт предупреждает, что мгновенный `stopped` не придёт |
| `donation_catalog` | SKU с `issues_voucher=False` | Внешний каталог донатов. Пустой список скрывает «Поддержать проект». Суммы 50/100/500 задаёт кузов |
| `donation_hint` | `None` | Необязательная рублёвая подсказка на экране доната, не курс и не шлюз |
| `review_sink` | `None` | Если нет — кнопка отзыва скрыта. Сток копирует материал в очередь модерации и публикует в канал; SQLite хранит только ID и согласие |
| `backup_policy` | `None` | Ночной ZIP в каталог, claim сети, ротация 14/8. `None` — без планировщика, ручной `/backup` как раньше |
| `reporting_policy` | `None` | Вечерний отчёт рамы в 23:30 UTC+5 в events (ошибка доставки — в ops). `None` — без отчётов |
| `process_control` | `None` | Внешний `ProcessControlPort`. `None` — кнопки рестарта нет. Адаптер и имена процессов живут в кузове |

`voucher_consumer` — единственная чистая заглушка-колбэк: без него оплата валидна, кузов просто не узнаёт о выдаче, пока сам не прочитает `chassis.vouchers`.

### Всегда дефолтные (подмены в фабрике нет)

- `WorkGatePort` → `DefaultWorkGateAdapter`  
- `AccessPort` → `DefaultAccessAdapter`  
- Админ-роутер, платёжный роутер, middleware

### Порты: контракт кузова

| Порт | Дефолт | Роль | Не роль |
|---|---|---|---|
| `WorkGatePort` | открыт | Рубильник, тень, бан **задачи кузова** | Оплата, дни, талоны |
| `AccessPort` | открыт | Подарок / VIP по времени | Списание задачи |
| `VoucherManagerPort` | открыт, подменяем | 1 талон = 1 задача | Сроки доступа |
| `ReferralPort` | открыт, подменяем | Связь и счётчик | Начисление бонуса (это кузов) |
| `CabinetSlotsProviderPort` | открыт, подменяем | Слоты карточки кабинета | Вёрстка кнопочного шасси |
| `SkuVoucherConsumerPort` | нет адаптера | Уведомление кузова о выдаче | Запись чека |

Правило трёх портов не склеивать: доступ, талон и гейт задачи — разные вызовы кузова.

---

## 5. Что внутри рамы

### 5.1 Кнопки

Постоянный `ReplyKeyboardMarkup`: включённые служебные кнопки стоят в одном ряду.
RU: `[👤 Аккаунт] [ℹ️ Инфо/FAQ] [Поддержка]`; EN: `[👤 Account] [ℹ️ Info/FAQ]
[💬 Support]`. Старые подписи (`👤 Личный кабинет`, `ℹ️ Info/FAQ` как RU-клик,
`💬 Поддержка` и прочие алиасы) остаются распознаваемыми **навсегда** — у
пользователя может висеть старая Reply-клавиатура до следующего `/start`;
кузову ничего делать не нужно. Приватные `/start`, `/help` и `/support`
работают, но в синее меню не входят. Синее меню — канонический `/menu`
(«📱 Восстановить кнопки меню») плюс команды, которые кузов передал явно;
переданные кузовом `menu`, `start`, `help`, `support` игнорируются. Один клик
Info вызывает `render_info_callback` один раз и не добавляет вторую карточку.
Без кузовного рендера рама показывает двуязычный Info; при включённом языке
на нём есть toggle.
Кнопка «Поддержка» открывает обзор (запрос, отзыв если есть sink, донат если есть каталог, назад на `render_start_callback`). Скрытая `/support` сразу включает ожидание нового обращения. Донатные суммы рама не зашивает.
SQLite-тикет не закрывается первым ответом: оператор отвечает несколько раз, пользователь жмёт «Ответить поддержке», слот освобождает только «Закрыть обращение». JSON-store по-прежнему одноразовый.
Отзыв (если есть `review_sink`) принимает текст или одно медиа, спрашивает согласие на публикацию и уходит в очередь модерации без копирования содержимого в SQLite. Суперадмин публикует или отклоняет один раз; после публикации пользователь получает прямую ссылку.
Карточки: `UserScreenTracker`, `CardClosePolicy`.  
Ввод: `PendingInputStore`, TTL 15 мин. Фабрика принимает внешний `pending_store` или создаёт штатный; тот же экземпляр отдаётся start-router, button-router и `CompleteChassis.pending_store`. `before_chassis_menu_action(user_id)` вызывается перед открытием Кабинета, Info и Поддержки (для поддержки — строго до `pending.set`); `None` — ничего не вызывать.  
Клики: `ActiveTaskTracker`.
Мост поддержки: при постоянном `db_path` и `thread_store=None` фабрика сама
создаёт продолжаемый `SqliteSupportThreadStore`. Одноразовый JSON
`SupportThreadStore` используется только при `db_path=":memory:"` или когда
кузов передал его явно; dual-write нет.

#### Миграция кузова на единый `/start`

Рама — единственный владелец `Command("start")`. Кузов удаляет свой обработчик и передаёт `render_start_callback`.

1. Удалить кузовной `Command("start")`. Если он остаётся на `domain_router`, фабрика останавливает сборку с `ValueError`, чтобы конфликт не ушёл в прод молча.
2. Передать `render_start_callback(context)`. `context` содержит `message`, `user_id`, `bot` и `locale`.
3. Не слать из callback второе приветствие с Reply-клавиатурой. Клавиатуру уже несёт сообщение рамы: `welcome_text` либо короткое «Главное меню».
4. Вернуть из callback `ChassisScreen` (рама отправит, добавит toggle и запомнит его) либо уже отправленный `Message` (рама только запомнит; toggle тогда добавляет кузов). Иначе lifecycle карточки не сможет закрыть её автоматически.
5. Проверить живой `/start`: ровно один носитель клавиатуры и ровно одна стартовая карточка callback. Третье сообщение значит, что миграция не закончена.
6. «Назад» из поддержки позже вызывает тот же callback. Отдельный стартовый экран для возврата не писать.

#### Миграция Info renderer

Рама владеет кнопкой Info (`ℹ️ Инфо/FAQ` / `ℹ️ Info/FAQ`) и `/help`. Второй FAQ-хэндлер кузова даёт вторую карточку.

1. Удалить кузовной обработчик Info/`/help`, если он дублирует раму.
2. Передать `render_info_callback(message, user_id, bot)`.
3. Вернуть `ChassisScreen`: рама отправит карточку, вставит языковой toggle и запомнит её. Уже отправленный `Message` тоже запоминается, но toggle тогда добавляет кузов (`decorate_info_markup` до отправки).
4. Один клик Info — одна карточка. Не слать второе FAQ-сообщение из callback.
5. Без колбэка рама показывает нейтральную двуязычную карточку; при включённом языке на ней есть toggle.

#### Миграция SQLite-поддержки

1. При постоянном `db_path` не передавать JSON-`SupportThreadStore`, если нужен продолжаемый тикет. Фабрика сама создаёт `SqliteSupportThreadStore`.
2. Явный JSON и `db_path=":memory:"` остаются одноразовым legacy: первый ответ закрывает слот.
3. SQLite идёт `open → in_progress → closed`. Оператор отвечает несколько раз; пользователь жмёт «Ответить поддержке»; слот снимает только «Закрыть обращение».
4. Dual-write JSON+SQLite нет. Тексты сообщений в SQLite не копируются.

#### Миграция `allowed_updates`

1. Polling и webhook передают `list(CANON_ALLOWED_UPDATES)`: `message`, `callback_query`, `pre_checkout_query`, `my_chat_member`.
2. Без `my_chat_member` мгновенный `stopped` не придёт; фабрика пишет предупреждение, если кузов передал свой список без этого апдейта.
3. Не вырезать `my_chat_member` своим фильтром: событие не троттлится специально, чтобы блок не потерялся после серии апдейтов.

### 5.2 Storage

`create_storage(config)` → `Storage` с репозиториями: users, roles, transactions, subscriptions, support_threads, reviews, bot_settings, referrals.

WAL, одна связь на транзакцию, `bot_id` везде. `amount` только INTEGER.  
Посев суперадминов: `INSERT OR IGNORE`.

Таблицы: `users`, `roles`, `transactions`, `subscriptions`, `support_threads`, `support_ticket_messages`, `review_submissions`, `bot_settings`, `referrals`, `user_bot_statuses`, `scheduled_job_runs`, `chassis_events`.
Схема: `src/bot_chassis/storage/schema.sql`. Колонки `provider` / `payment_id` готовы к другим шлюзам; **в v1 пишется только** `telegram_stars`.

`consent_at` шасси хранит, сбор согласия — кузов.

### 5.3 Middleware (на `dp.update.outer_middleware`)

Порядок: ErrorAlert → Throttling → UserActivity.

- Ошибки хэндлера → `audit_chat_id or support_chat_id`, если тумблер включён. Пользователю уходят две строки без эмодзи: «Произошла непредвиденная ошибка.» и «Мы уже занимаемся этим вопросом.» Traceback остаётся в служебном чате.
- Троттлинг 5/с; `pre_checkout_query` и `successful_payment` не режутся.  
- UserActivity: upsert, локаль, тень (админов не глушит, платежи не дропает), first-touch `traffic_source`, при `enable_referrals` — `/start ref_<id>`.

### 5.4 Админка

Фильтры `admin` / `superadmin`. Команды: `/admin`, `/user`, `/ban`, `/unban`, `/shadowban`, `/grant`, `/revoke`, `/gift`, `/gift_revoke`, `/export`, `/backup`, `/refund`, `/maintenance`. Цель `/user`, `/ban`, `/unban`, `/shadowban`, `/grant`, `/revoke`, `/gift` и `/gift_revoke` — числовой ID или `@username` без учёта регистра. Несколько старых совпадений показывают список ID и ничего не меняют. Кнопка «Найти пользователя» ждёт ввод отдельно от поддержки, рассылки и кузова. `/cancel` отменяет поиск.
Главный экран зависит от роли. Staff: сводка, статистика, поиск, рубильник. Root дополнительно: рассылка, Excel, ручной `.db`, экран рестарта только если передан `process_control`. Сводка: всего пользователей, active текущего бота, новые сегодня (UTC+5), открытые обращения, Stars сегодня, последний успешный бэкап, состояние планировщика и шпаргалка команд. Переходы внутри раздела правят панель; `/admin` снимает кнопки со старой панели и шлёт новую вниз. Значимое действие оставляет постоянный текст без кнопок и поднимает свежую панель. `AdminScreenTracker` не удаляет отчёты (не `UserScreenTracker` + DELETE).
Досье `adm_usr:*`: у staff только санкции; роли и подарки рисуются лишь root, проверка callback остаётся вторым слоем. `extra_user_dossier_lines` / `extra_user_dossier_rows` дополняют `/user`; клики новых кнопок идут в `extra_admin_actions.handle_callback`.
Рассылка 25 msg/s, только root; свой RAM-store, общий `asyncio.Lock`. Предпросмотр после подтверждения или отмены без кнопок; итог — отдельное чистое сообщение.
Рестарт через `ProcessControlPort`: список целей, одноразовое подтверждение, без параллели на одну цель. Для «всех» рама сама вызывает `restart()` по очереди (управляющий последним) и пишет промежуточный итог после каждой цели. Метод порта `restart_all` остаётся адаптеру и тестам, рама его не зовёт. Аудит обязан успешно уйти до первого вызова порта; без настроенного направления или при ошибке доставки рестарт отменяется. Сбой чтения статуса одной цели превращается в `error`, не обрывая общий итог. Финал — в ops и постоянный отчёт. Рама не выполняет системных команд и не хранит имена unit.
Кнопка Excel отдаёт `.xlsx` только суперадмину в ЛС: лист на каждую пользовательскую таблицу, `_manifest`, tenant-фильтр, представление статуса и ссылки на листе users. Книга строится из короткого SQLite snapshot, поэтому долгая упаковка Excel не держит write-lock живой базы. Команда `/export [users|payments|gifts|all]` остаётся legacy CSV/ZIP. Ручной `/backup` и кнопка бэкапа — проверенный `.db` суперадмину; успешно отправленная временная копия удаляется, а при превышении лимита или ошибке отправки остаётся в каталоге. Ночной снимок — ZIP в каталог с конечным timeout внутри SQLite backup; ops-тема получает только итог. Незавершённый claim можно атомарно перехватить после `claim_stale_after_seconds` (по умолчанию 15 минут); уникальный владелец запуска не даёт старому процессу финализировать уже перехваченный слот. Готовые и failed-слоты не перехватываются. Вечерний отчёт рамы при `reporting_policy` уходит в events-тему; первый запуск до 23:30 ждёт сегодняшний слот, неудачный отчёт не обрывает следующий период. Ошибки рамы и платежей считаются по неизменяемым `chassis_events`, без метрик кузова.
Команды админки работают только в private. `/refund charge_id` или `/refund user_id payment_id`: запись сначала ограничивается фактическим Telegram bot ID, затем вызывается Bot API и `mark_refunded` по каноническому `payment_id`.

### 5.5 Платежи v1 (Stars)

Инвойс: `currency=XTR`, `provider_token=""`, цена в целых Stars, payload `sku:{code}:{user_id}:{nonce}` ≤ 128 байт.  
`admin_grant` и SKU вне каталога не продаются.  
`pre_checkout`: рубильник, тень, сверка payload и каталога. Обычный бан → `ok=True`. Сбой решения всегда отвечает `ok=False`.
`successful_payment` всегда пишет чек (деньги уже сняты), в том числе при рубильнике и бане. Битый payload без пользователя чек не пишет, алерт в поддержку уходит.
SKU с `issues_voucher=False` (например, донат) сохраняется сразу погашенным и не попадает в активные талоны.

### 5.6 Сеть: tenant, origin и фактический бот

> Подробное руководство по стыковке с сетью PsyBot: [docs/PSYBOT_INTEGRATION.md](PSYBOT_INTEGRATION.md).

- `bot_id` — общий tenant данных. Семь процессов одной сети используют одно значение и один SQLite-файл.
- `origin_bot_id` — логическое имя конкретного бота; если не задано, равно `bot_id`.
- Фактический Telegram bot ID берётся из токена во время выполнения. Платёж уникален по `(bot_id, provider, merchant_telegram_bot_id, payment_id)`.
- В общей support-группе Reply доставляет только процесс origin-бота и продолжает выбранный `ticket_id`; чужой бот, чат или тема молчат. Закрытие явно снимает слот.
- `audit_chat_id` используется для аудита, а служебные алерты выбирают audit-or-support. Все семь ботов могут быть администраторами служебной группы.
- При постоянном `db_path` фабрика сама создаёт SQLite-store поддержки. `:memory:` и явно переданный JSON остаются одноразовым legacy.

---

## 6. Инварианты

1. `bot_gateway.py` не трогать. В `tests/test_chassis.py` по-прежнему 19 тестов; для контракта меню `0.3` изменены только `test_main_menu_keyboard_toggles_and_domain_rows`, `test_register_button_chassis_startup_hook` и `test_setup_bot_commands_merges_custom_commands`.
2. Кузов зовёт порты сам.  
3. v1 — только официальные Stars.  
4. `bot_id` обязателен во всех SQL.  
5. Деньги — INTEGER, без `REAL`.  
6. Тень на admin/superadmin запрещена. Последнего активного (не забаненного) суперадмина нельзя забанить и снять роль.
7. Платёжный гейт ≠ `WorkGatePort`.

---

## 7. Карта пакета

```
src/bot_chassis/
  factory.py          # create_complete_chassis, CompleteChassis
  config.py           # BotChassisConfig, SkuItem
  router.py           # кнопки
  storage/            # engine, schema.sql, repositories/
  ports/              # протоколы + дефолтные адаптеры
  middleware/         # ErrorAlert, Throttling, UserActivity
  admin/              # фильтры, аудит, экран, экспорт, рассылка
  payments/           # Stars invoice + router
  localization.py
  lifecycle.py followup.py dispatcher.py
  support_bridge.py commands.py keyboards.py contracts.py
```

Тесты: `tests/test_chassis.py`, `test_storage.py`, `test_ports_and_middleware.py`, `test_admin.py`, `test_payments.py`, `test_factory.py`, `test_integration.py`, `test_gate*.py`.

---

## 8. Документы

| Файл | Назначение |
|---|---|
| **Этот файл** | Канон v1, подключение и состав |
| [archive/](archive/README.md) | Спеки и планы, по которым раму собрали |

Дальше по продукту: монтировать кузов. Раму v1 не расширять сторонними шлюзами и доменной логикой.
