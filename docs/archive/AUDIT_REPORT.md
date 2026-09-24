> **Архив.** Журнал находок. Канон v1: [../CHASSIS.md](../CHASSIS.md).

# Сводный реестр аудита Bot Chassis (v2.0 — ФИНАЛ)

**Дата фиксации:** 2026-09-24  
**Проверенная кодовая база:** `C:\Python\bot_chassis` (Windows, Python 3.14, aiogram 3.13+, SQLite WAL)  
**Канонические документы:** [docs/IMPLEMENTATION_PLAN.md](file:///c:/Python/bot_chassis/docs/IMPLEMENTATION_PLAN.md) (v2.10), [docs/MODULAR_CHASSIS_SPEC.md](file:///c:/Python/bot_chassis/docs/MODULAR_CHASSIS_SPEC.md) (v2.10)  
**Финальный статус сьют-тестов:** **80 passed** после полировки F.1–F.5 (100% зелёные, 0 ошибок). До полировки было 74.  
- 19 базовых тестов кнопок: [tests/test_chassis.py](file:///c:/Python/bot_chassis/tests/test_chassis.py)
- 16 тестов контура хранения: [tests/test_storage.py](file:///c:/Python/bot_chassis/tests/test_storage.py)
- 12 тестов портов и middleware: [tests/test_ports_and_middleware.py](file:///c:/Python/bot_chassis/tests/test_ports_and_middleware.py)
- 22 теста админки: [tests/test_admin.py](file:///c:/Python/bot_chassis/tests/test_admin.py)
- 6 тестов платежей Stars: [tests/test_payments.py](file:///c:/Python/bot_chassis/tests/test_payments.py)
- 4 теста сборки рамы: [tests/test_factory.py](file:///c:/Python/bot_chassis/tests/test_factory.py)
- 1 сквозной интеграционный тест: [tests/test_integration.py](file:///c:/Python/bot_chassis/tests/test_integration.py)

---

## 1. Матрица статуса этапов реализации

| Этап / Задача | Описание | Статус аудита | Результат тестов |
|---|---|---|---|
| **Этап 1** | Базовый Storage Contour (SQLite WAL, пользователи, роли, подарки) | **ПРИНЯТ** | 28 тестов зелёные |
| **Задача 2.0** | Синхронизация Storage (схема v2.10, безопасная пересборка `transactions`, `referrals`, `mark_refunded`, `backup()`) | **PASS** | 35 тестов зелёные |
| **Задача 2.1** | Платформенные тумблеры и аудит-чат в [config.py](file:///c:/Python/bot_chassis/src/bot_chassis/config.py) | **PASS** | 35 тестов зелёные |
| **Задача 2.2** | Чистые порты и адаптеры в [ports/](file:///c:/Python/bot_chassis/src/bot_chassis/ports/) (`WorkGate`, `Access`, `Vouchers`, `Referrals`, `Cabinet`, `build_cabinet_renderer`) | **PASS** | 35 тестов зелёные |
| **Задача 2.3** | Middleware в [middleware/](file:///c:/Python/bot_chassis/src/bot_chassis/middleware/) (`ErrorAlert`, `Throttling`, `UserActivity`, регистрация на `Update`) | **PASS** | 35 тестов зелёные |
| **Задача 2.4** | Локализация в [localization.py](file:///c:/Python/bot_chassis/src/bot_chassis/localization.py) (`ALLOWED_LOCALES`, колбэк `core_lang:*`, Reply через SendMessage) | **PASS** | 35 тестов зелёные |
| **Задача 2.5** | Сьют тестов Этапа 2 в [test_ports_and_middleware.py](file:///c:/Python/bot_chassis/tests/test_ports_and_middleware.py) | **PASS** | 47 тестов зелёные |
| **ИТОГ ЭТАПА 2** | **Port Contour & Middleware полностью реализованы** | **ПРИНЯТ** | **47 тестов зелёные** |
| **Задача 3.1** | Фильтры ролей в [admin/filters.py](file:///c:/Python/bot_chassis/src/bot_chassis/admin/filters.py) (`AdminRoleFilter`, `SuperadminRoleFilter`) | **PASS** | 50 тестов зелёные |
| **Задача 3.2** | Сервис аудит-канала в [admin/audit.py](file:///c:/Python/bot_chassis/src/bot_chassis/admin/audit.py) (`send_admin_audit`) | **PASS** | 53 теста зелёные |
| **Задача 3.3** | Admin Router, команды и досье в [admin/router.py](file:///c:/Python/bot_chassis/src/bot_chassis/admin/router.py) и [admin/export.py](file:///c:/Python/bot_chassis/src/bot_chassis/admin/export.py) | **PASS** | 63 теста зелёные |
| **Задача 3.4** | Рассылка в [admin/broadcast.py](file:///c:/Python/bot_chassis/src/bot_chassis/admin/broadcast.py) (25 msg/s, изолированный RAM-store, RetryAfter, отмена) | **PASS** | 64 теста зелёные |
| **Задача 3.5** | Сьют тестов админки в [tests/test_admin.py](file:///c:/Python/bot_chassis/tests/test_admin.py) (17 тестов) | **PASS** | 64 теста зелёные |
| **ИТОГ ЭТАПА 3** | **Admin Chassis полностью реализован и протестирован** | **ПРИНЯТ** | **64 теста зелёные** |
| **Задача 4.1** | Сервис инвойсов Stars в [payments/service.py](file:///c:/Python/bot_chassis/src/bot_chassis/payments/service.py) (XTR, валидация SKU, payload $\le$ 128) | **PASS** | 70 тестов зелёные |
| **Задача 4.2** | Платёжный роутер в [payments/router.py](file:///c:/Python/bot_chassis/src/bot_chassis/payments/router.py) (pre_checkout гейт, чек, талоны, алерты) | **PASS** | 70 тестов зелёные |
| **Задача 4.3** | Сьют тестов платежей в [tests/test_payments.py](file:///c:/Python/bot_chassis/tests/test_payments.py) (6 тестов) | **PASS** | 70 тестов зелёные |
| **ИТОГ ЭТАПА 4** | **Payment Chassis v1 (Telegram Stars) полностью принят** | **ПРИНЯТ** | **70 тестов зелёные** |
| **Задача 5.1** | Фабрика [factory.py](file:///c:/Python/bot_chassis/src/bot_chassis/factory.py) (`CompleteChassis`, порядок роутеров, алиас `/start`, outer middleware) | **PASS** | 73 теста зелёные |
| **Задача 5.2** | Эталонный раннер [run_complete_chassis.py](file:///c:/Python/bot_chassis/examples/run_complete_chassis.py) и [examples/.env.example](file:///c:/Python/bot_chassis/examples/.env.example) | **PASS** | 73 теста зелёные |
| **Задача 5.3** | Интеграционный тест сквозного цикла в [test_integration.py](file:///c:/Python/bot_chassis/tests/test_integration.py) | **PASS** | **74 теста зелёные** |
| **ИТОГ ЭТАПА 5** | **Сборка рамы, фабрика и интеграционный раннер приняты** | **ПРИНЯТ** | **74 теста зелёные** |

---

## 2. Сводный реестр замечаний аудита по всей истории (Журнал находок и ловушек)

| ID | Тип / Важность | Область | Описание проблемы / Риск | Принятое решение / Статус |
|---|---|---|---|---|
| **B1 / P1** | Блокер (Крит.) | SQLite DDL / миграция | `CREATE INDEX idx_users_bot_shbanned` вызывал `OperationalError` на базе Этапа 1, если создавался до добавления колонки `is_shadow_banned`. | **Устранено.** Докатка колонок перенесена строго **до** исполнения `schema_sql`. Реализована безопасная пересборка `transactions` с сохранением истории и маппингом `payment_id`. |
| **B2** | Блокер (Крит.) | Платежный гейт | `pre_checkout` ошибочно проверялся через `WorkGatePort.can_accept_work()`. При бане покупателю выводился `ban_reason`, что недопустимо, а при теневом бане выдавалось раскрывающее сообщение. | **Устранено.** Платёжный гейт полностью изолирован. Обычный бан отвечает `ok=True`. Теневой бан отвечает нейтрально: *«Оплата временно недоступна»*. Рубильник отдаёт `maintenance_reason`. |
| **B3** | Блокер (Крит.) | Троттлинг | 5-й апдейт в секунду от пользователя мог дропнуть `successful_payment` после реального списания Stars Телеграмом (потеря чека). | **Устранено.** `pre_checkout_query` и `Message.successful_payment` добавлены в безусловный whitelist троттлинга до инкремента счётчиков. |
| **B4** | Блокер (Крит.) | aiogram Update | Мидлвари на `dp.update.outer_middleware` принимали `event` как конкретный тип события (`CallbackQuery`/`Message`), вызывая `AttributeError`. | **Устранено.** Везде `event` типизирован как `aiogram.types.Update`. Диспетчеризация ответа идёт через `event.callback_query` / `event.message` / `event.pre_checkout_query`. |
| **P2** | Архитектура | Теневой бан | В ранней спеке была формулировка «защита последнего суперадмина» для тени. | **Устранено (Инвариант 8).** Теневой бан на **любого** админа или суперадмина запрещён безусловно (`target_is_admin`). Снятие тени разрешено. Защита последнего суперадмина действует только для обычного бана и отзыва роли. |
| **P3** | Архитектура | Кабинет | Отсутствовал мост между `CabinetSlotsProviderPort` и неизменным `render_cabinet_callback` кнопочного шасси. | **Устранено.** Реализован [build_cabinet_renderer](file:///c:/Python/bot_chassis/src/bot_chassis/ports/cabinet.py#L89) с `html.escape` и HTML-разметкой карточки. |
| **P4** | Архитектура | Фабрика рамы | Не были зафиксированы датакласс рамы и строгий порядок роутеров в диспетчере. | **Устранено.** Специфицирован датакласс `CompleteChassis`. Порядок включения: Admin $\to$ Payments $\to$ Localization $\to$ **Domain** $\to$ Buttons. |
| **P5** | Производительность | Троттлинг | Полная чистка словаря троттлинга на каждый апдейт создавала O(N) нагрузку на CPU. | **Устранено.** Ключ пользователя очищается за O(1), глобальный сборщик мусора запускается не чаще 1 раза в 60 секунд. |
| **P6** | Логика | Оплата Stars | У `SuccessfulPayment` нет поля `sku_code`, а `SkuVoucherConsumerPort` мог быть не передан. | **Устранено.** Добавлен безопасный парсинг `sku_code` из `invoice_payload` и проверка `if voucher_consumer is not None:`. |
| **P7** | Целостность данных | First-touch UTM | `cur.rowcount == 0` ломал возврат `set_traffic_source` при повторном визите существующего пользователя. | **Устранено.** Добавлена явная проверка существования пользователя (`SELECT 1 FROM users WHERE bot_id = ? AND user_id = ?`). |
| **P8** | Надёжность | Бэкап БД | `sqlite3.backup` блокировался и зависал внутри транзакции `BEGIN IMMEDIATE`. | **Устранено.** Метод [StorageEngine.backup](file:///c:/Python/bot_chassis/src/bot_chassis/storage/engine.py#L74) вынесен в отдельную блокировку вне транзакционного контекста движка. |
| **NB-12** | Замечание к Т3.1 | Фильтры ролей | Функция `_user_id(event)` в [admin/filters.py](file:///c:/Python/bot_chassis/src/bot_chassis/admin/filters.py#L39) проверяет только `getattr(event, "from_user", None)`. | **Устранено.** Фоллбэк читает `event.event.from_user`, если у внешнего объекта нет `from_user`. |
| **NB-13** | Проверено в Т3.2 | Аудит-канал | Сетевой сбой или неверный `audit_chat_id` не должны ронять основной поток операций админа. | **Устранено.** `send_admin_audit` перехватывает все исключения с `logger.exception`. Экранирует текст через `html.escape`. |
| **NB-14** | Проверено в Т3.3 | 152-ФЗ и экспорт | Выгрузка базы (`/export`, `adm_export`) содержит ПДн. | **Устранено.** Защищено фильтром `root` и проверкой `await root(call)`. Обычному админу отдаётся тост `show_alert=True`. Документ отправляется **строго в ЛС вызывающему суперадмину** (`chat_id=actor_id`). |
| **NB-15** | Проверено в Т3.3 | Лимит бэкапа | Метод `/backup` отправляет файл базы через Telegram Bot API. | **Устранено.** Добавлена проверка `os.path.getsize(path) >= BACKUP_LIMIT_BYTES` (50 МБ). Файл отправляется **только** в приватный чат вызвавшему суперадмину. Временный файл гарантированно удаляется в `finally:`. |
| **NB-16** | Проверено в Т3.3 | Замена подписки | Команда `/gift <user_id> [days]` не должна суммировать дни (§4.2). | **Устранено.** Вызов `grant_gift_access` заменяет активную подписку без накопления срока. Проверено тестом (срок пересчитывается от момента выдачи). |
| **NB-17** | Проверено в Т3.4 | Рассылка и FSM | Рассылка не должна ломать диалоги кнопочного шасси. | **Устранено.** Хранение сессий вынесено в изолированный RAM-словарь `_BROADCAST_SESSIONS` в `admin/broadcast.py`. `PendingInputKind` в кнопочном шасси не затронут (проверено тестом). |
| **NB-18** | Проверено в Т3.3 | InaccessibleMessage | При удалении исходного сообщения в Telegram `call.message` становится `InaccessibleMessage`. | **Устранено.** В [admin/router.py](file:///c:/Python/bot_chassis/src/bot_chassis/admin/router.py) добавлена явная проверка `isinstance(message, InaccessibleMessage)` для всех обновлений сообщений (`_edit_home`, `_edit_dossier`). |
| **NB-19** | Замечание к Т3.2 | Форматирование аудита | `send_admin_audit` экранирует весь переданный текст через `html.escape`, исключая возможность передачи HTML-тегов (`<b>`, `<code>`). | **Устранено.** Флаг `is_html=False` по умолчанию экранирует текст. При `is_html=True` ошибка парсера откатывается на `html.escape`, внешний `except Exception` сохранён. |
| **NB-20** | Замечание к Т3.3 | Длина причины бана | В `/ban` длинная строка причины конкатенируется с сообщением аудита. При экстремальной длине текста (>3500 символов) возможно превышение лимита сообщения Telegram (4096). | **Устранено.** Многословная причина обрезается до 500 символов (`reason[:497] + "..."`), только если она длиннее лимита. |
| **NB-21** | Проверено в Т3.3 | Возврат Stars | Возврат `/refund` не должен менять статус в БД, если Telegram Bot API отклонил запрос. | **Устранено.** Вызов `bot.refund_star_payment` происходит **до** вызова `storage.transactions.mark_refunded`. Ошибки API перехватываются через `TelegramAPIError`, отклонённые платежи не помечаются возвращёнными. |
| **NB-22** | Замечание к Т3.3 | RAM-спайк при экспорте | `_table_csv` делает `cursor.fetchall()`, формируя CSV целиком в памяти в `io.StringIO` и `zipfile.ZipFile`. | **Устранено (частично).** Выборка идёт чанками `fetchmany(1000)`, `None` пишется как пустая строка. CSV по-прежнему собирается в `StringIO`: убран только единовременный список всех кортежей. |
| **NB-23** | Замечание к Т3.3 | Память при бэкапе | `_snapshot_bytes` читает весь файл базы (до 50 МБ) в `bytes` через `read_bytes()` и оборачивает в `BufferedInputFile`. | **Устранено.** Бэкап уходит через `FSInputFile`, временный файл удаляется в `finally` после отправки. |
| **NB-24** | Замечание к Т3.3 | UX сигнатуры `/refund` | В спеке указано `/refund <charge_id>`, а в коде реализовано `/refund <user_id> <payment_id>`. Telegram API требует оба параметра (`user_id` и `charge_id`). | **Устранено.** Принимается `/refund <charge_id>` и прежняя пара аргументов. В Bot API идут канонические `user_id` и `charge_id` ряда, в `mark_refunded` — канонический `payment_id`. |
| **NB-25** | Замечание к Т3.3 | Отзывчивость кнопки экспорта | В `handle_export` вызов `await call.answer()` стоит после `_send_export`. Генерация архива на большой базе может занять 2–4 секунды. | **Устранено.** Тост «Формирую выгрузку...» уходит сразу после проверки роли, хвостовой `call.answer()` снят. |
| **NB-26** | Замечание к Т3.3 | Навигация карточки досье | В карточке `/user` есть кнопки действий над пользователем, но нет кнопки «« Назад в /admin» или «Закрыть». | **Устранено.** Кнопка «« Главное меню админки» с колбэком `adm_home` вызывает `_edit_home`. |
| **NB-27** | Замечание к Т3.3 | Поиск платежа при возврате | В `_find_payment` поиск идёт по `payment_id = ?`. Если администратор скопирует из выписки `telegram_payment_charge_id`, платёж может не найтись, если они различаются. | **Устранено.** Поиск по `payment_id` или `telegram_payment_charge_id` в пределах `bot_id`, с детерминированным `ORDER BY`. |
| **NB-28** | Замечание к Т3.4 | Конкурентные рассылки | Если два администратора одновременно запустят рассылку, суммарный поток (25 + 25 = 50 msg/s) превысит лимит Telegram токена (30 msg/s). | **Устранено.** Весь `_run_broadcast` (включая старт и отчёт) держит модульный `asyncio.Lock`. `reset_broadcast_sessions()` сбрасывает и лок. |
| **NB-29** | Замечание к Т4.2 | Defense-in-depth pre_checkout | `_pre_checkout_decision` проверяет формат payload и `user_id`, но не валидирует наличие `sku_code` в `config.skus`. | **Устранено.** После рубильника и тени SKU сверяется с `config.skus`, `admin_grant` отклоняется. |
| **NB-30** | Замечание к Т5.1 | Расширяемость фабрики | Фабрика `create_complete_chassis` создаёт стандартные адаптеры для ваучеров и рефералов, не принимая кастомных провайдеров. | **Устранено.** `vouchers_provider` и `referrals_provider` — keyword-only аргументы с дефолтом `None`. |
| **NB-31** | Замечание к Т5.1 | Кастомизация приветствия /start | Роутер `_create_start_router` отправляет захардкоженный текст `_MENU_TEXT`. | **Устранено.** `BotChassisConfig.welcome_text` (HTML, дефолт `None`) подставляется в `/start`. |

---

## 3. Детальный чек-лист: статус выполнения

- [x] **Этап 1: Storage Contour (SQLite WAL, пользователи, роли, подарки)** — ПРИНЯТ
- [x] **Этап 2: Port Contour & Middleware** — ПРИНЯТ
  - [x] Задача 2.0: Синхронизация схем v2.10 и миграция `transactions`
  - [x] Задача 2.1: Платформенные тумблеры и аудит-чат в `config.py`
  - [x] Задача 2.2: Чистые порты `WorkGate`, `Access`, `Vouchers`, `Referrals`, `Cabinet`
  - [x] Задача 2.3: Внешние middleware `ErrorAlert`, `Throttling`, `UserActivity`
  - [x] Задача 2.4: Локализация `ALLOWED_LOCALES` и колбэки `core_lang:*`
  - [x] Задача 2.5: Сьют тестов портов и middleware
- [x] **Этап 3: Admin Chassis** — ПРИНЯТ
  - [x] Задача 3.1: Фильтры ролей `AdminRoleFilter`, `SuperadminRoleFilter`
  - [x] Задача 3.2: Сервис аудит-канала `send_admin_audit`
  - [x] Задача 3.3: Экран `/admin`, команды модерации, досье `/user`, выгрузка 152-ФЗ, бэкап $\le$ 50 МБ, возврат Stars
  - [x] Задача 3.4: Рассылка 25 msg/s, RetryAfter, отмена `adm_bcast:stop`
  - [x] Задача 3.5: Полный сьют тестов админки (22 теста после полировки F.1–F.5; на приёмке этапа было 17)
- [x] **Этап 4: Payment Chassis v1 (Telegram Stars)** — ПРИНЯТ
  - [x] Задача 4.1: Сервис инвойсов `XTR`, валидация цен и SKU
  - [x] Задача 4.2: Гейт `pre_checkout`, фиксация чека `successful_payment`, выдача талона
  - [x] Задача 4.3: Сьют тестов платежей (6 тестов)
- [x] **Этап 5: Сборка рамы и интеграция (ФИНАЛ)** — ПРИНЯТ
  - [x] Задача 5.1: Фабрика `create_complete_chassis` и датакласс `CompleteChassis` в [src/bot_chassis/factory.py](file:///c:/Python/bot_chassis/src/bot_chassis/factory.py)
    - Порядок роутеров: Admin $\to$ Payments $\to$ Localization $\to$ **Domain** $\to$ Buttons
    - Подключение внешних middleware на `dp.update.outer_middleware`
    - Алиас `Command("start")` с закрытием предыдущих карточек и дедупликацией
    - Посев суперадминов `seed_superadmins`
  - [x] Задача 5.2: Эталонный запуск [examples/run_complete_chassis.py](file:///c:/Python/bot_chassis/examples/run_complete_chassis.py) и переменные окружения [examples/.env.example](file:///c:/Python/bot_chassis/examples/.env.example)
  - [x] Задача 5.3: Сквозной интеграционный тест [tests/test_integration.py](file:///c:/Python/bot_chassis/tests/test_integration.py) и тесты фабрики [tests/test_factory.py](file:///c:/Python/bot_chassis/tests/test_factory.py)

---

## 4. Жёсткие инварианты кодовой базы (Итог проверки)

1. **Кнопочный каркас:** [tests/test_chassis.py](file:///c:/Python/bot_chassis/tests/test_chassis.py) (19 шт.) и сигнатуры кнопочного интерфейса (`router`, `keyboards`, `lifecycle`, `dispatcher`, `followup`, `commands`, `support_bridge`) **100% неизменны и зелёные**.
2. **Разделение слоёв:** Доменный кузов сам вызывает порты шасси перед выполнением бизнес-логики (`chassis.work_gate.can_accept_work`). Шасси не запускает задачи кузова самовольно.
3. **Платёжный периметр v1:** Исключительно официальные Telegram Stars (XTR). Никаких сторонних серверов и шлюзов (ЮKassa/CryptoBot).
4. **Изоляция арендаторов:** Поле `bot_id` строго обязательно во всех таблицах, связях, индексах и SQL-запросах.
5. **Финансовые единицы:** `amount` строго `INTEGER` minor-units, никаких чисел с плавающей точкой `REAL`.
6. **Шлюз:** Файл [src/bot_chassis/bot_gateway.py](file:///c:/Python/bot_chassis/src/bot_chassis/bot_gateway.py) не модифицирован.
