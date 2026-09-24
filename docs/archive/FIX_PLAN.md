> **Архив.** Полировка F.1–F.5 выполнена. Канон v1: [../CHASSIS.md](../CHASSIS.md).

# Хирургический план устранения неточностей и полировки (v1.1)

**Рабочий корень:** `C:\Python\bot_chassis`  
**Канонический базис:** [docs/IMPLEMENTATION_PLAN.md](file:///c:/Python/bot_chassis/docs/IMPLEMENTATION_PLAN.md) (v2.10) и [docs/MODULAR_CHASSIS_SPEC.md](file:///c:/Python/bot_chassis/docs/MODULAR_CHASSIS_SPEC.md) (v2.10)  
**Источник замечаний:** [docs/AUDIT_REPORT.md](file:///c:/Python/bot_chassis/docs/AUDIT_REPORT.md) (раздел 2, реестр NB-12..NB-31)  
**Ревизия v1.1:** Исправлены архитектурные и платформенные риски v1.0 (Windows I/O бэкапа, целостность `payment_id`/`charge_id` при возврате Stars, TOCTOU рассылки, стыковка колбэка досье с кодом и тестами, keyword-only сигнатура фабрики). Сниппеты F.2/F.4 выровнены с живым кодом: рубильник и тень pre_checkout не переписываются, многословная причина `/ban` сохраняется, обвязка возврата NB-21 не снимается.

> [!IMPORTANT]
> **Принцип нулевого риска:**
> 1. Все 19 тестов базового кнопочного шасси `tests/test_chassis.py` и шлюз `src/bot_chassis/bot_gateway.py` остаются **100% неприкосновенными**.
> 2. Любые расширения публичных конструкторов (`BotChassisConfig`, `create_complete_chassis`) выполняются строго с безопасными дефолтами и keyword-only аргументами.
> 3. Порядок внедрения строго атомарен: **F.1 $\to$ F.2 $\to$ F.3 $\to$ F.4 $\to$ F.5**. Переход к следующей задаче только при 100% зелёных тестах текущего шага.

---

## 1. Матрица соответствия замечаний из AUDIT_REPORT.md

| ID | Область | Описание замечания | Задача плана v1.1 |
|---|---|---|---|
| **NB-12** | `admin/filters.py` | Защитный фоллбэк `_user_id(event)` для сырых объектов `Update` (`event.event.from_user`) | **Задача F.1** |
| **NB-19** | `admin/audit.py` | Поддержка форматированного HTML с сохранением обязательного swallow всех исключений | **Задача F.1** |
| **NB-29** | `payments/router.py`| Defense-in-depth: передача `config` в `_pre_checkout_decision`, валидация `sku_code in config.skus` и запрет `admin_grant` | **Задача F.2** |
| **NB-30** | `factory.py` | Расширяемость DI: keyword-only параметры `vouchers_provider` и `referrals_provider` | **Задача F.3** |
| **NB-31** | `config.py` & `factory.py` | Кастомизация приветственного сообщения `/start` через `config.welcome_text` (HTML) | **Задача F.3** |
| **NB-20** | `admin/router.py` | Защита от переполнения лимита сообщения Telegram (4096 симв.) при `reason and len(reason) > 500` | **Задача F.4** |
| **NB-25** | `admin/router.py` | Быстрый toast `await call.answer("Формирую выгрузку...")` и удаление хвостового `call.answer()` | **Задача F.4** |
| **NB-26** | `admin/router.py` | Кнопка возврата «« Главное меню админки» (`CB_HOME = "adm_home"`) и синхронизация ассерта теста досье | **Задача F.4** |
| **NB-27** | `admin/router.py` | Поиск платежа по `payment_id = ? OR telegram_payment_charge_id = ?` с детерминированным `ORDER BY` | **Задача F.4** |
| **NB-24** | `admin/router.py` | Одно- и двухаргументный `/refund`: в Bot API передаётся канонический `charge_id` ряда, в `mark_refunded` — канонический `payment_id` ряда | **Задача F.4** |
| **NB-28** | `admin/broadcast.py`| Сериализация рассылок: `async with _BROADCAST_LOCK` в `_run_broadcast`, сброс в `reset_broadcast_sessions()` | **Задача F.4** |
| **NB-22** | `admin/export.py` | Защита памяти: выборка чанками `fetchmany(1000)` без аллокации списка всех кортежей; сохранение `None -> ""` | **Задача F.5** |
| **NB-23** | `admin/router.py` | Потоковая отправка `FSInputFile`, гарантированный `unlink` в `finally` и фиксация байт в моке сессии | **Задача F.5** |

---

## 2. Пошаговые хирургические задачи

### Задача F.1: Безопасность фильтров и аудит-сообщений (NB-12, NB-19)

1. **Файл:** [src/bot_chassis/admin/filters.py](file:///c:/Python/bot_chassis/src/bot_chassis/admin/filters.py)
   - Обновить `_user_id(event)` с безопасным извлечением пользователя из обёрнутого `event.event`:
     ```python
     def _user_id(event: TelegramObject) -> int | None:
         user = getattr(event, "from_user", None)
         if user is None:
             inner = getattr(event, "event", None)
             if inner is not None:
                 user = getattr(inner, "from_user", None)
         if user is not None and getattr(user, "id", None) is not None:
             return int(user.id)
         return None
     ```

2. **Файл:** [src/bot_chassis/admin/audit.py](file:///c:/Python/bot_chassis/src/bot_chassis/admin/audit.py)
   - Сигнатура: `async def send_admin_audit(bot: Bot | None, config: BotChassisConfig, text: str, is_html: bool = False) -> None:`.
   - Если `is_html is False`: экранировать текст `payload = html.escape(text)`.
   - Если `is_html is True`: вызывающий обязан экранировать подставляемые переменные пользователя (`user_id`, `reason`). Отправлять `payload = text`. При возникновении `TelegramBadRequest` (ошибка тегов парсера Telegram) отправлять защитный фоллбэк: `html.escape(text)` для гарантии доставки.
   - **Инвариант NB-13:** Внешний блок `try ... except Exception: logger.exception("Не удалось отправить аудит-лог")` сохраняется безусловно — сетевые ошибки аудита никогда не прерывают основной поток.

3. **Верификация:**
   - В [tests/test_admin.py](file:///c:/Python/bot_chassis/tests/test_admin.py) добавить тесты:
     - `_user_id(Update(update_id=1, message=Message(...)))` корректно возвращает id пользователя.
     - `send_admin_audit` с `is_html=False` экранирует символы `<` и `>`.
     - `send_admin_audit` с `is_html=True` отправляет HTML, а при `TelegramBadRequest` повторяет отправку с экранированием.
   - Запуск: `python -m pytest tests/test_admin.py -v`.

---

### Задача F.2: Защита платёжного гейта pre_checkout (NB-29)

1. **Файл:** [src/bot_chassis/payments/router.py](file:///c:/Python/bot_chassis/src/bot_chassis/payments/router.py)
   - В функции `handle_pre_checkout` передавать `config`:
     `ok, error = await _pre_checkout_decision(storage, bot_id, query, config)`
   - Расширить сигнатуру `_pre_checkout_decision(..., config: BotChassisConfig)`. Ветки рубильника и теневого бана **не менять**. После существующей проверки payload **вставить** валидацию SKU:
     ```python
     async def _pre_checkout_decision(
         storage: Storage,
         bot_id: str,
         query: PreCheckoutQuery,
         config: BotChassisConfig,
     ) -> tuple[bool, str | None]:
         maintenance, reason = await storage.bot_settings.get_maintenance_status(bot_id)
         if maintenance:
             return False, reason or MAINTENANCE_PAYMENT_ERROR
         user = query.from_user
         record = await storage.users.get_user(bot_id, user.id) if user is not None else None
         if record is not None and record.is_shadow_banned:
             return False, SHADOW_PAYMENT_ERROR
         parsed = _parse_payload(query.invoice_payload)
         if parsed is None or user is None or parsed[1] != user.id:
             return False, PAYLOAD_MISMATCH_ERROR
         sku_code, _ = parsed
         valid_sku_codes = {sku.sku_code for sku in config.skus}
         if sku_code not in valid_sku_codes or sku_code == "admin_grant":
             return False, PAYLOAD_MISMATCH_ERROR
         return True, None
     ```
   - Защита исключает оплату товаров не из каталога, а также служебного `admin_grant`, даже если он случайно оказался в `config.skus`. Рубильник, тень и обычный бан (ok=True) остаются как в принятом гейте B2.

2. **Верификация:**
   - В [tests/test_payments.py](file:///c:/Python/bot_chassis/tests/test_payments.py) добавить проверки:
     - Попытка оплаты неизвестного SKU `sku:unknown_item:7:abcd` $\to$ `ok=False`, `error_message == PAYLOAD_MISMATCH_ERROR`.
     - Попытка оплаты служебного SKU `sku:admin_grant:7:abcd` $\to$ `ok=False`, `error_message == PAYLOAD_MISMATCH_ERROR`.
   - Запуск: `python -m pytest tests/test_payments.py -v`.

---

### Задача F.3: Расширяемость фабрики и кастомизация приветствия (NB-30, NB-31)

1. **Файл:** [src/bot_chassis/config.py](file:///c:/Python/bot_chassis/src/bot_chassis/config.py)
   - Добавить поле в `BotChassisConfig`:
     ```python
     welcome_text: str | None = None
     ```
     Зафиксировать в документации: `welcome_text` ожидает HTML-разметку (как дефолтный `_MENU_TEXT`), так как сообщение меню отправляется с `parse_mode="HTML"`. Дефолт `None` обеспечивает 100% обратную совместимость.

2. **Файл:** [src/bot_chassis/factory.py](file:///c:/Python/bot_chassis/src/bot_chassis/factory.py)
   - Сигнатуру `create_complete_chassis` расширить **строго keyword-only** аргументами в конце:
     ```python
     async def create_complete_chassis(
         bot: Bot,
         config: BotChassisConfig,
         dp: Dispatcher | None = None,
         storage: Storage | None = None,
         voucher_consumer: SkuVoucherConsumerPort | None = None,
         cabinet_provider: CabinetSlotsProviderPort | None = None,
         domain_router: Router | None = None,
         domain_rows: Sequence[Sequence[str]] | None = None,
         *,
         vouchers_provider: VoucherManagerPort | None = None,
         referrals_provider: ReferralPort | None = None,
     ) -> CompleteChassis:
     ```
   - Использовать переданные провайдеры при наличии:
     ```python
     vouchers = vouchers_provider or DefaultVoucherManagerAdapter(storage.transactions)
     referrals = referrals_provider or DefaultReferralAdapter(storage.referrals)
     ```
   - В `_create_start_router`:
     ```python
     welcome = config.welcome_text if config.welcome_text is not None else _MENU_TEXT
     await message.answer(
         welcome,
         reply_markup=build_main_menu_keyboard(domain_rows=domain_rows, locale=locale),
         parse_mode="HTML",
     )
     ```

3. **Верификация:**
   - В [tests/test_factory.py](file:///c:/Python/bot_chassis/tests/test_factory.py) добавить тесты:
     - Внедрение кастомного `vouchers_provider` сохраняется в объекте `CompleteChassis.vouchers`.
     - Задание `welcome_text="<b>Привет!</b>"` отправляет заданный текст при `/start`.
   - Запуск: `python -m pytest tests/test_factory.py -v`.

---

### Задача F.4: UX админки, безопасность рассылки и целостность возвратов (NB-20, NB-24, NB-25, NB-26, NB-27, NB-28)

1. **Файл:** [src/bot_chassis/admin/router.py](file:///c:/Python/bot_chassis/src/bot_chassis/admin/router.py)
   - **Константы:** Добавить `CB_HOME = "adm_home"`.
   - **Ограничение длины причины бана (NB-20):**
     - В `handle_ban` оставить разбор через `_command_args` / `args`. Многословную причину не резать до первого токена. Сразу после текущей строки `reason = " ".join(args[1:]).strip() or None` добавить обрезку:
       ```python
       reason = " ".join(args[1:]).strip() or None
       if reason and len(reason) > 500:
           reason = reason[:497] + "..."
       ```
   - **Отзывчивость экспорта (NB-25):**
     - В начале `handle_export`: сразу после проверки роли вызывать `await call.answer("Формирую выгрузку...")`.
     - **Удалить хвостовой вызов `await call.answer()`** в конце `handle_export` (исключение двойного ответа на один колбэк).
   - **Кнопка возврата в досье (NB-26):**
     - В `_dossier_keyboard`: добавить 6-ю кнопку:
       `[InlineKeyboardButton(text="« Главное меню админки", callback_data=CB_HOME)]`.
     - Зарегистрировать колбэк:
       ```python
       @router.callback_query(F.data == CB_HOME, staff)
       async def handle_home_callback(call: CallbackQuery) -> None:
           user = call.from_user
           if user is None or await _is_banned(storage, bot_id, user.id):
               await call.answer()
               return
           await _edit_home(call, storage, bot_id)
           await call.answer()
       ```
   - **Поиск платежа и целостность `/refund` (NB-24, NB-27):**
     - Обновить `_find_payment(storage, bot_id, target_id: int | None, query: str)`:
       ```python
       def _op(conn):
           sql = """
           SELECT user_id, payment_id, telegram_payment_charge_id, provider, status, voucher_status
           FROM transactions
           WHERE bot_id = ?
             AND (? IS NULL OR user_id = ?)
             AND (payment_id = ? OR telegram_payment_charge_id = ?)
           ORDER BY CASE provider WHEN 'telegram_stars' THEN 0 ELSE 1 END, id DESC
           LIMIT 1
           """
           row = conn.execute(sql, (bot_id, target_id, target_id, query, query)).fetchone()
           if row is None:
               return None
           return (
               row["user_id"],
               row["payment_id"],
               row["telegram_payment_charge_id"],
               row["provider"],
               row["status"],
               row["voucher_status"],
           )
       ```
     - В `handle_refund`:
       - Поддержать вызов с 1 или 2 аргументами:
         ```python
         args = _command_args(message)
         if len(args) == 1:
             target_id = None
             query = args[0]
         elif len(args) == 2:
             target_id = _parse_user_id(args[0])
             query = args[1]
             if target_id is None:
                 await _reply(message, REFUND_USAGE)
                 return
         else:
             await _reply(message, REFUND_USAGE)
             return
         ```
       - Найти ряд: `row = await _find_payment(storage, bot_id, target_id, query)`.
         Если `row is None`: `await _reply(message, REFUND_NOT_FOUND); return`.
         Распаковать: `canon_user_id, canon_payment_id, canon_charge_id, provider, status, voucher_status = row`.
       - Валидация — без изменений смысла:
         - `provider != "telegram_stars"` $\to$ `REFUND_NOT_STARS`
         - `status == "refunded"` или `voucher_status == "cancelled"` $\to$ `REFUND_ALREADY`
         - `not canon_charge_id` $\to$ `REFUND_NO_CHARGE`
       - Исполнение возврата: меняются **только идентификаторы**. Обвязку NB-21 (`try/except TelegramAPIError`, `REFUND_REJECTED`, `_refund_mark_error`) не снимать:
         ```python
         try:
             confirmed = await message.bot.refund_star_payment(
                 user_id=canon_user_id,
                 telegram_payment_charge_id=canon_charge_id,
             )
         except TelegramAPIError as exc:
             await _reply(message, str(exc))
             return
         if not confirmed:
             await _reply(message, REFUND_REJECTED)
             return
         ok, err = await storage.transactions.mark_refunded(
             bot_id, canon_payment_id, provider="telegram_stars"
         )
         if not ok:
             await _reply(message, _refund_mark_error(err))
             return
         await _reply(message, f"Платёж возвращён: {canon_payment_id}")
         ```
         В Bot API идут **`canon_user_id`** и **`canon_charge_id`**, в `mark_refunded` — **`canon_payment_id`**. Если Telegram отказал, ряд в БД остаётся `paid`. Если админ указал `charge_id`, отличный от внутреннего `payment_id`, статусы не разъедутся.

2. **Файл:** [src/bot_chassis/admin/broadcast.py](file:///c:/Python/bot_chassis/src/bot_chassis/admin/broadcast.py)
   - **Сериализация рассылок (NB-28):**
     - Добавить на уровне модуля: `_BROADCAST_LOCK = asyncio.Lock()`.
     - В `_run_broadcast(...)` обернуть цикл доставки в `async with _BROADCAST_LOCK:`.
       Это гарантирует, что даже при одновременном запуске рассылок двумя администраторами их выполнение будет строго последовательным, а суммарный поток никогда не превысит лимит токена (25 msg/s < 30 msg/s).
     - В `reset_broadcast_sessions()` добавить сброс лока:
       ```python
       global _BROADCAST_LOCK
       _BROADCAST_LOCK = asyncio.Lock()
       ```
       для изоляции тестов от предыдущих запусков.

3. **Синхронизация существующих тестов [tests/test_admin.py](file:///c:/Python/bot_chassis/tests/test_admin.py):**
   - В тесте `test_user_dossier_card_and_actions`:
     Обновить проверку списка кнопок, добавив 6-ю кнопку: `("« Главное меню админки", "adm_home")`.
   - Добавить новые проверки:
     - Обрезка длинной причины бана до 500 символов.
     - Одноаргументный `/refund <charge_id>`.
     - Двухаргументный `/refund <user_id> <charge_id>`, когда `charge_id != payment_id`.
     - Запрос рефанда по чужому `bot_id` возвращает `REFUND_NOT_FOUND`.
     - Колбэк `"adm_home"` возвращает на домашний экран админки.
   - Запуск: `python -m pytest tests/test_admin.py -v`.

---

### Задача F.5: Оптимизация памяти при экспорте и безопасный бэкап (NB-22, NB-23)

1. **Файл:** [src/bot_chassis/admin/export.py](file:///c:/Python/bot_chassis/src/bot_chassis/admin/export.py)
   - В `_table_csv`:
     Заменить `rows = cursor.fetchall()` на чанки `fetchmany(1000)`:
     ```python
     text = io.StringIO()
     writer = csv.writer(text, lineterminator="\n")
     writer.writerow(headers)
     while True:
         batch = cursor.fetchmany(1000)
         if not batch:
             break
         for row in batch:
             writer.writerow("" if value is None else value for value in row)
     return text.getvalue().encode("utf-8-sig")
     ```
     Сохраняется строгое форматирование `None -> ""` и кодировка `utf-8-sig`. Устраняется единовременное хранение гигантского списка кортежей строк SQLite в куче Python.

2. **Файл:** [src/bot_chassis/admin/router.py](file:///c:/Python/bot_chassis/src/bot_chassis/admin/router.py)
   - В `_send_backup(bot: Bot, storage: Storage, actor_id: int)`:
     Использовать потоковую передачу через `FSInputFile` с гарантированным освобождением дескрипторов:
     ```python
     fd, path = tempfile.mkstemp(suffix=".db")
     os.close(fd)
     try:
         await storage.engine.backup(path)
         if os.path.getsize(path) >= BACKUP_LIMIT_BYTES:
             await _notify(bot, actor_id, BACKUP_TOO_LARGE)
             return
         document = FSInputFile(path, filename="backup.db")
         await bot.send_document(chat_id=actor_id, document=document)
     except Exception:
         logger.exception("Не удалось отправить снапшот")
         await _notify(bot, actor_id, "Не удалось отправить снапшот")
     finally:
         try:
             os.unlink(path)
         except OSError:
             pass
     ```
     Удалить устаревший хелпер `_snapshot_bytes`.

3. **Синхронизация тестового мока в [tests/test_admin.py](file:///c:/Python/bot_chassis/tests/test_admin.py):**
   - В сессии `_Session.make_request(bot, method, timeout)`:
     При перехвате метода `SendDocument` перехватывать и сохранять байты до завершения вызова:
     ```python
     if method.__class__.__name__ == "SendDocument":
         doc = getattr(method, "document", None)
         if isinstance(doc, FSInputFile):
             method._test_payload = Path(doc.path).read_bytes()
     ```
   - В тесте `test_backup_goes_only_to_the_caller`:
     Проверять `documents[0].document.filename == "backup.db"` и валидировать схему SQLite по байтам из `documents[0]._test_payload`.
   - Запуск: `python -m pytest tests/test_admin.py tests/test_integration.py -v`.

---

## 3. Финальный верификационный протокол

После завершения всех 5 задач F.1–F.5 запускается полный контрольный прогон:
```powershell
python -m pytest tests/ -v
```

**Критерии 100% приёмки полировки:**
1. Все 7 сьютов зелёные, суммарно не менее **80 тестов** (74 базовых + не менее 6 новых проверок).
2. Все 19 базовых тестов [tests/test_chassis.py](file:///c:/Python/bot_chassis/tests/test_chassis.py) не модифицировались и зелёные.
3. Шлюз [src/bot_chassis/bot_gateway.py](file:///c:/Python/bot_chassis/src/bot_chassis/bot_gateway.py) не модифицировался.
4. Обновление статусов замечаний в [docs/AUDIT_REPORT.md](file:///c:/Python/bot_chassis/docs/AUDIT_REPORT.md) (перевод NB-12..NB-31 в статус `Устранено`).
