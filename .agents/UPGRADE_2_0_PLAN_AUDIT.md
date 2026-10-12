# Release 2.0 — хирургический план реализации (Bot Chassis)

**Дата составления:** 2026-10-12
**Статус:** Исправлено после независимого аудита; готово к последовательной реализации по одному Gate
**Проект:** Bot Chassis (`C:\Python\bot_chassis`)
**Связанные документы:**
- Архитектурная спецификация админки: `.agents/ADMIN_REDESIGN_SPEC.md`;
- канон рамы: `docs/CHASSIS.md`;
- реестр планов: `.agents/ACTIVE_PLANS.md`;
- текущее состояние: `.agents/SESSION_STATE.md`;
- независимая приёмка реализации: `.agents/AUDIT_2_0_IMPLEMENTATION_PROMPT.md`.

**Идентификатор пакета:** рабочее имя — Release 2.0; целевая версия пакета после зелёной реализации и документационного Gate R2 — `2.0.0`. До R2 значение `version = "0.3.1"` в `pyproject.toml` не менять.

---

# ЧАСТЬ I. ЗАКРЫТИЕ НЕЗАВИСИМОГО АУДИТА

## 1. Executive Verdict

> **Вердикт плана после коррекции:** **READY FOR GATED IMPLEMENTATION**.
> Этот документ является единственным исполняемым планом Release 2.0. Coding-модель не принимает архитектурных решений сама: она выполняет только текущий подтверждённый Gate, использует указанные callback-строки и сигнатуры, запускает перечисленные тесты и останавливается до команды владельца на следующий Gate.

Независимый аудит обнаружил блокеры в S4-A, S4-B, S4-C, P1, P3, A0, A1, A3, A4, A5, A6 и A7. Ниже они закрыты на уровне плана точными контрактами. Код проекта этим документом ещё не изменён.

---

## 2. Закрытые архитектурные решения

1. **Telegram-клавиатуры:** максимум пять цифровых кнопок A5 в одном ряду; у Stars-инвойса `pay=True` строго в `[0][0]`; callback отмены постоянный и короче 64 байт.
2. **Стартовое уведомление:** только `audit_chat_id/audit_thread_id`; если `audit_chat_id` отсутствует — только `superadmin_ids[0]`; `support_chat_id` для startup не используется. Это точечное решение Release 2.0 и оно должно синхронно исправить противоречащую строку в `ADMIN_REDESIGN_SPEC.md`.
3. **Экран рамы для кузова:** единая публичная сигнатура `await chassis.screens.retire_active_screen(bot, user_id)`. `chat_id` берётся из записи трекера и извне не передаётся.
4. **Single-message `/start`:** `single_message_start=False` сохраняет старый двухсообщенческий контракт. Один носитель возможен только когда итоговый экран не требует Inline-разметки; язык/toggle и уже отправленный callback-`Message` безопасно деградируют до двух сообщений.
5. **Причина санкции:** pending-запись хранит и `target_user_id`, и вид санкции (`ban` либо `shadow_ban`), и координаты исходной панели. Для причины теневого бана вводится отдельное поле БД `shadow_ban_reason` с миграцией.
6. **Автобэкап:** внешний аргумент остаётся `BackupPolicy | Literal[False] | None`, default остаётся `None`. Внутри фабрики он один раз нормализуется в `resolved_backup_policy: BackupPolicy | None`; значение `False` никогда не попадает в scheduler, admin-router или форматтеры.
7. **Существующие тесты:** `tests/test_chassis.py` не меняется. Старые тесты админки, бэкапа и отчётов разрешено менять только там, где ожидание намеренно заменено этим Release 2.0; точный список приведён в Части III.

---

## 3. Архитектурные запреты для coding-модели

1. Не добавлять `FSMContext`, `StatesGroup`, Redis или новое постоянное хранилище ожиданий.
2. Не менять `bot_gateway.py`, порядок роутеров и публичные Button Chassis-сигнатуры.
3. Не менять `tests/test_chassis.py`: файл содержит ровно 19 тестов.
4. Не оставлять кнопку без зарегистрированного обработчика даже на один промежуточный Gate. Поэтому A1–A4 имеют явно описанные переходные состояния.
5. Не использовать сырой `edit_message_text` в Stay-in-Dossier. Только `AdminScreenTracker.edit_or_send` либо новый метод того же класса с тем же перехватом `message is not modified`.
6. Не удалять `freeze_as_report` и `_raise_home` глобально: они нужны другим контурам. Удаляются только их вызовы из dossier-flow.
7. Не использовать `support_chat_id` как fallback стартового уведомления и не рассылать startup по всему `superadmin_ids`.
8. Не кодировать в callback_data username, причину, SKU или другой произвольный текст. Только фиксированный префикс, короткое действие, номер страницы и целочисленный `user_id`.
9. Любая пользовательская строка в HTML (`username`, имя, причина, источник, имя архива/бота) проходит через `html.escape` ровно один раз.

---

# ЧАСТЬ II. ТЕХНИЧЕСКИЙ ПЛАН RELEASE 2.0 (14 КОДОВЫХ ГЕЙТОВ + RELEASE GATE R2)

## Железные инварианты разработки
1. **Один Gate = один изолированный diff = один коммит** после прогона тестов.
2. **Файл `tests/test_chassis.py` строго заморожен:** ровно 19 тестов, структура неизменна. Новые проверки пишутся только в `tests/test_gate_s4.py`, `tests/test_gate_p.py`, `tests/test_admin_v2.py`; существующие профильные тесты меняются только по матрице Части III. Для S4-B разрешена только точечная замена старого ожидания отсутствующей клавиатуры истории в `tests/test_gate5b_tickets.py` на проверку единственной кнопки `Закрыть`.
3. **Обратная совместимость сигнатур:** новые параметры в `factory.py` добавляются строго в конец keyword-only части. Единственное новое поле этого релиза — `single_message_start: bool = False`; это явно утверждённое исключение из общего правила default `None`.
4. **Экранирование HTML:** все пользовательские данные (`username`, `first_name`, `traffic_source`) оборачиваются в `html.escape`.
5. **CallbackQuery:** каждый обработанный callback получает ровно один `call.answer(...)`, включая ошибки, повторные клики и отказ доступа.
6. **Приватность:** новые admin/message handlers обязательно содержат `F.chat.type == ChatType.PRIVATE` и существующий staff/root ACL.
7. **Тест после Gate:** сначала узкий файл Gate, затем `py -m pytest tests -q`, затем `py -m pytest tests/test_chassis.py -q`.

## Протокол «модель ничего не додумывает»

Правило путей: короткое имя production-файла вроде `factory.py` означает ровно `src/bot_chassis/factory.py`; `admin/router.py` означает `src/bot_chassis/admin/router.py`; тест всегда указан от корня `tests/`. Если найдено два одноимённых файла, использовать только путь из этого правила, не выбирать на глаз.

Для каждого Gate coding-модель обязана выполнить один и тот же буквальный цикл:

1. Выписать в ответе разрешённые файлы Gate. Файл, которого нет в списке, не открывать для редактирования.
2. Найти указанные ниже функции/классы через `rg -n`. Номер строки из этого документа не считать постоянным: якорь — имя символа.
3. До первой правки сохранить вывод `git diff -- <разрешённые файлы>` и `git status --short`.
4. Сделать один микро-шаг; сразу запустить названный тест этого микро-шага. Не накапливать пять непроверенных изменений.
5. После каждого изменения `admin/router.py` выполнить `git diff -- src/bot_chassis/admin/router.py` и подтвердить, что diff находится только внутри перечисленных для Gate символов и импортов этих символов.
6. Если нужного символа нет, сигнатура отличается или для реализации требуется ещё один production-файл — **остановиться** и сообщить расхождение. Не создавать параллельную функцию с похожим именем.
7. Не «чинить заодно» соседний Gate, lint всего проекта, формулировки чужих документов или старый код вне разрешённого диапазона.
8. Gate считается законченным только после зелёного узкого набора, полного suite, frozen-suite `19 passed`, `compileall`, `git diff --check` и проверки списка изменённых файлов.
9. После отчёта остановиться. Коммит и следующий Gate требуют отдельной команды владельца.

### Хирургические границы большого `admin/router.py`

| Gate | Разрешённые якоря в `admin/router.py` | Запрещённые соседние контуры |
|---|---|---|
| A0 | imports из `admin.screens`; `create_admin_router`; `_home`; callbacks home/DB/export/backup; передача guard в broadcast/process | `_dossier*`, поиск, sanctions/subscription, `_dashboard` SQL |
| A6 | `_dashboard` и handler, который только показывает её результат | `_home`, dossier, export/backup, process, broadcast |
| A1 | вызовы `_dossier`; `_dossier`; `_dossier_text`; `_dossier_keyboard`; `handle_user_action`; новый `_show_dossier_call` | home/DB, dashboard, broadcast/process, export/backup |
| A2 | `_dossier_keyboard`; exact handlers/parsers `menu:sanctions` и `sanction:*` | pending-ввод A3, subscription A4, список A5 |
| A3 | imports pending; lookup registration; sanctions `ban/shadow_on/no_reason/cancel`; навигационные очистки ADMIN-scope; `AdminScreenTracker.edit_tracked_or_send` в `admin/screens.py` | A0/A6, остальные методы tracker, subscription A4, pagination A5, payment router |
| A4 | `_dossier_keyboard`; subscription parser/handlers | sanctions pending A3, dashboard, список A5 |
| A5 | lookup screen; DB menu row; users page/open parsers и handlers; вызов `_dossier` | текст/операции dossier, sanctions/subscription, dashboard |
| A7 | тип/нормализация `backup_policy`, `_send_backup`, wiring `project_label` в оба scheduler-а, human-readable вызовы форматтеров | меню, ACL, dossier, lookup и pagination |

Если diff одного Gate пересёк запрещённый контур, Gate не сдавать: откатить только собственный незакоммиченный фрагмент либо остановиться и показать владельцу конфликт. Чужие изменения рабочей папки не откатывать.

---

## Канонический граф очередности внедрения

### Реестр callback_data Release 2.0

Coding-модель использует только эти значения; альтернативные префиксы не придумывать:

| Назначение | Значение |
|---|---|
| Закрыть историю поддержки | существующий `CB_NAV_CLOSE = "chassis:nav:close"` |
| Отмена Stars-инвойса | `CB_PAY_CANCEL = "chassis:pay:cancel"` |
| Меню БД | `CB_GO_DB = "adm_go:db_menu"` |
| Excel из меню БД | существующий `CB_EXPORT = "adm_export"` |
| Ручной `.db` из меню БД | существующий `CB_DO_BACKUP = "adm_do:backup"` |
| Список из поиска | `adm_users:p:s:<page>` |
| Список из меню БД | `adm_users:p:d:<page>` |
| Открыть досье из списка | `adm_users:o:<user_id>` |
| Открыть санкции | `adm_usr:menu:sanctions:<user_id>` |
| Назад в базовое досье | `adm_usr:menu:dossier:<user_id>` |
| Полный бан / разбан | `adm_usr:sanction:ban:<user_id>` / `adm_usr:sanction:unban:<user_id>` |
| Тень вкл. / выкл. | `adm_usr:sanction:shadow_on:<user_id>` / `adm_usr:sanction:shadow_off:<user_id>` |
| Бан без причины | `adm_usr:sanction:no_reason:<user_id>` |
| Отмена ввода причины | `adm_usr:sanction:cancel:<user_id>` |
| Открыть подписку | `adm_usr:menu:subscription:<user_id>` |
| Gift 30 / lifetime | `adm_usr:sub:gift30:<user_id>` / `adm_usr:sub:giftlife:<user_id>` |
| +1 токен / отзыв Gift | `adm_usr:sub:token:<user_id>` / `adm_usr:sub:revoke:<user_id>` |

Для максимального 20-значного Telegram ID каждое значение остаётся короче 64 байт. Парсеры принимают только точное число сегментов, allowlist действий и `str.isdigit()` для ID/page. Битый callback только подтверждается через `call.answer()` и ничего не изменяет.

```text
[ Фаза 1: UI & Client Core ]
  Gate S4-A (Startup Alert)
    → Gate S4-B (Ticket History Close)
    → Gate S4-C (Retire Active Screen)
    → Gate P1 (Invoice Stars Cancel)
    → Gate P2 (Cabinet 1-Line Slots)
    → Gate P3 (Single Message Start)

[ Фаза 2: Корневая админка и статистика ]
    → Gate A0 (Admin Menu & DB Menu & Security Alert Throttling)
    → Gate A6 (Stats Screen Redesign)

[ Фаза 3: Ядро досье и подменю ]
    → Gate A1 (Dossier Redesign & Stay-in-Dossier Engine)
    → Gate A2 (Sanctions Submenu & 1-Click Unban)
    → Gate A3 (Ban Reason Input via PendingInputStore)
    → Gate A4 (Subscription Submenu)

[ Фаза 4: Поиск, список пользователей и отчётность ]
    → Gate A5 (Search Cleanup & Paginated User List with 5/row buttons)
    → Gate A7 (Human-Readable Reports & Safe Default Backup)
```

---

## Детальные спецификации гейтов

### Фаза 1. UI & Client Core (S4 & Live Profiling)

#### Gate S4-A: Маршрут уведомления о старте бота

**Цель:** один startup-процесса создаёт не более одного Telegram-сообщения и никогда не рассылается всему `SUPERADMIN_IDS`.

**Файлы:**
- `src/bot_chassis/service_notify.py`;
- `src/bot_chassis/factory.py`;
- `.agents/ADMIN_REDESIGN_SPEC.md` и `docs/CHASSIS.md` — только синхронизация принятого маршрута;
- `tests/test_gate_s4.py`.

**Сделать буквально:**
1. В `service_notify.py` добавить:
   ```python
   async def deliver_startup_notification(bot: Bot | None, config: BotChassisConfig) -> bool:
   ```
2. Текст уведомления: `🟢 <b>Bot Chassis запущен</b>\nПроект: <b>{escaped bot_id}</b>`. `bot_id` экранировать.
3. Если `bot is None` — вернуть `False`, сеть не вызывать.
4. Если `resolve_service_destination(config, "audit")` вернул адрес — отправить ровно туда с `parse_mode="HTML"` и вернуть `True` при успехе.
5. Если audit-адреса нет и `config.superadmin_ids` непуст — отправить ровно один раз в `config.superadmin_ids[0]`, без `message_thread_id`.
6. Если нет ни audit, ни суперадмина — `logger.warning(...)`, вернуть `False`.
7. Любая ошибка Telegram логируется и превращается в `False`; не делать повторную рассылку по остальным ID.
8. В `create_complete_chassis` зарегистрировать отдельный `dp.startup` hook, который вызывает `deliver_startup_notification(bot, config)`. Простого добавления функции без регистрации недостаточно.
9. Исправить §9.1 `ADMIN_REDESIGN_SPEC.md`: startup-fallback — первый суперадмин, не `SUPPORT_CHAT_ID`. Остальные service channels сохраняют прежний audit-or-support контракт.

**Тесты Gate:** audit с thread; fallback только в первый ID из `(11, 22)`; пустые настройки — ноль запросов; ошибка отправки — `False` и без второй попытки; `dp.emit_startup()` реально вызывает функцию один раз.

**Definition of Done:** в проекте нет цикла `for ... in superadmin_ids` для startup-уведомления.

#### Gate S4-B: Закрытие экрана истории тикета поддержки

**Цель:** оператор закрывает историю; истёкшее или недоступное для удаления сообщение не роняет handler.

**Файлы:** `support_bridge.py`, `router.py`, `tests/test_gate_s4.py`, точечное обновление существующего ожидания истории в `tests/test_gate5b_tickets.py`.

**Сделать буквально:**
1. `send_support_history` передаёт `InlineKeyboardMarkup` с единственной кнопкой `Закрыть`, callback — существующий `CB_NAV_CLOSE`.
2. Не создавать второй close-callback и не менять текст кнопки на эмодзи-вариант.
3. В общем обработчике `CB_NAV_CLOSE/CB_NAV_CANCEL/CB_SUPPORT_BACK` заменить сырой `message.delete()` на существующий:
   ```python
   await close_card_screen(
       query.bot,
       query.message.chat.id,
       query.message.message_id,
       policy=CardClosePolicy.DELETE,
   )
   ```
   Этот helper уже обрабатывает `TelegramBadRequest`, `TelegramForbiddenError`, timeout и fallback на снятие markup.
4. Существующий `screens.forget_card(user_id)` сохранить **перед** вызовом `close_card_screen`. Не переносить его после `await` и не удалять: tracker не должен помнить уже закрываемую карточку даже при сетевой ошибке.
5. Для `InaccessibleMessage` сетевой вызов не делать. `query.answer()` вызвать ровно один раз.
6. Поведение `CB_NAV_CANCEL` и `CB_SUPPORT_BACK` после закрытия оставить прежним; `CB_NAV_CLOSE` завершает handler сразу после закрытия.

**Тесты Gate:** успешное delete; `TelegramBadRequest` → `EditMessageReplyMarkup(None)`; `TelegramForbiddenError` → тот же fallback; ошибка fallback не выходит наружу; текст истории и reply-to не меняются.

#### Gate S4-C: Идемпотентное снятие карточек рамы (`retire_active_screen`)

**Цель:** кузов явно и безопасно снимает кнопки последней карточки рамы перед открытием доменного экрана.

**Файлы:** `lifecycle.py`, `factory.py`, `docs/CHASSIS.md`, `docs/LISTENER_INTEGRATION.md`, `docs/PSYBOT_INTEGRATION.md`, `tests/test_gate_s4.py`.

**Единственная допустимая сигнатура:**
```python
async def retire_active_screen(self, bot: Bot, user_id: int) -> None:
```

**Алгоритм:**
```python
entry = self.get_card(user_id)
if entry is None:
    return
chat_id, message_id, _old_policy = entry
self.forget_card(user_id)  # до await: повторный/параллельный вызов уже пустой
await close_card_screen(
    bot,
    chat_id,
    message_id,
    policy=CardClosePolicy.DROP_MARKUP,
)
```

**Монтаж:**
1. Создать `screens = UserScreenTracker()` до `if config.enable_buttons`, а не внутри него.
2. В `CompleteChassis` вставить обязательное поле `screens: UserScreenTracker` **сразу после** `locale_cache` и **до** `thread_store`/`pending_store`, у которых уже есть defaults. В конец dataclass поле без default не добавлять — это вызовет `TypeError: non-default argument follows default argument`. `default_factory` не использовать: фабрика обязана вернуть именно тот tracker, который передан в routers.
3. В `return CompleteChassis(...)` передать `screens=screens`; это тот же объект по identity, не новый `UserScreenTracker()`.
4. Старые вызовы фабрики не меняются. Кузов вызывает только `await chassis.screens.retire_active_screen(bot, user_id)`.
5. `before_chassis_menu_action` не переименовывать и не разворачивать: он по-прежнему вызывается рамой при входе в её меню.

**Тесты Gate:** нет записи → ноль API; первая отставка снимает markup, но не удаляет текст; повторная → ноль API; используется сохранённый `chat_id`; при `enable_buttons=False` поле `chassis.screens` всё равно существует.

#### Gate P1: Кнопка «Отмена» на инвойсе Stars

**Цель:** корректный Stars-инвойс с безопасной отменой и без длинного callback_data.

**Файлы:** `payments/service.py`, `payments/router.py`, `tests/test_gate_p.py`; при публичном экспорте константы — также `payments/__init__.py`.

**Сделать буквально:**
1. В `payments/service.py` объявить `CB_PAY_CANCEL = "chassis:pay:cancel"`. Не включать `sku_code`: отмена не меняет заказ и не нуждается в SKU.
2. В `send_sku_invoice` передать в `bot.send_invoice`:
   ```python
   InlineKeyboardMarkup(inline_keyboard=[
       [InlineKeyboardButton(
           text=f"Оплатить {invoice.prices[0].amount} ⭐",
           pay=True,
       )],
       [InlineKeyboardButton(text="Отмена", callback_data=CB_PAY_CANCEL)],
   ])
   ```
3. В payments-router зарегистрировать точный фильтр `F.data == CB_PAY_CANCEL`, не `startswith`.
4. Handler: проверить доступное сообщение, вызвать `call.answer("Оплата отменена")` ровно один раз, затем закрыть через `close_card_screen(..., policy=DELETE)`. При невозможности удаления останется текст инвойса без активной клавиатуры.
5. Не добавлять FSM, `state.clear()`, запись транзакции или отмену `pre_checkout`: до оплаты состояние отсутствует.

**Тесты Gate:** `[0][0].pay is True`; cancel находится отдельным вторым рядом; callback короче 64 байт даже при SKU длиной 120; cancel не вызывает payment/storage; delete и fallback; существующие `tests/test_payments.py` остаются зелёными.

#### Gate P2: Однострочный компактный рендеринг слотов кабинета

**Цель:** каждый слот занимает одну строку, между слотами нет пустых строк.

**Файлы:** `ports/cabinet.py`, `tests/test_gate_p.py`.

**Точная сборка текста:**
```python
lines = ["👤 <b>Аккаунт</b>"]
if slots:
    lines.append("")
for slot in slots:
    lines.append(
        f"• <b>{html.escape(slot.title)}:</b> {html.escape(slot.content)}"
    )
return ChassisScreen(text="\n".join(lines))
```

Не менять получение слотов, порядок, кнопки слотов и `CabinetSlot`. Не оставлять старый `"\n\n".join(lines)`, иначе компактность будет фиктивной. При пустом `slots` результат обязан быть ровно `👤 <b>Аккаунт</b>` без завершающего `\n`.

**Тесты Gate:** два слота идут соседними строками; `<`, `>`, `&` в title/content экранированы; пустой список даёт только заголовок без лишнего хвоста.

#### Gate P3: Single-Message режим на `/start`

**Цель:** опционально объединить стартовый текст и Reply-клавиатуру, не теряя Inline-кнопки, language toggle и совместимость callback, который сам отправляет `Message`.

**Файлы:** `factory.py`, `docs/CHASSIS.md`, `docs/PSYBOT_INTEGRATION.md`, `docs/LISTENER_INTEGRATION.md`, `tests/test_gate_p.py`, узкое дополнение контрактного теста в `tests/test_gate12_release.py`.

**Сигнатура:** добавить последним keyword-only аргументом:
```python
single_message_start: bool = False,
```
Default `False` проверяется отдельным assert и не добавляется в `NEW_NONE_KWONLY`.

**Не менять старый режим:** при `False` `/start` сначала отправляет carrier с Reply-клавиатурой, затем вызывает существующий `_deliver_start_card`; поведение байт-в-байт прежнее.

Чтобы не вызвать callback дважды, разделить текущую вложенную функцию на два шага:
```python
async def _render_start_result(message: Message, user_id: int) -> object:
async def _deliver_start_result(message: Message, user_id: int, rendered: object) -> None:
```
Первая функция только вызывает `render_start_callback` либо возвращает `None`; вторая только отправляет/декорирует уже полученный результат и не вызывает callback. Старый `_deliver_start_card` может остаться тонкой обёрткой над этими двумя функциями для режима `False` и `on_support_back`.

**Алгоритм при `True`:**
1. Закрыть прошлую карточку и очистить USER-scope как сейчас.
2. Построить Reply-клавиатуру.
3. Если `render_start_callback is None` и `enable_language_switch is False` — отправить ровно один carrier (`welcome_text` либо `_START_CARRIER_TEXT`) с Reply-клавиатурой. В tracker его не записывать.
4. Если callback есть — вызвать его один раз до отправки carrier и разобрать результат:
   - `ChassisScreen` без Inline markup и `enable_language_switch=False`: отправить **его `text`** и `parse_mode` одним сообщением с Reply-клавиатурой; в tracker не записывать;
   - `ChassisScreen` с markup либо любой `ChassisScreen` при `enable_language_switch=True`: `logger.warning`, затем отправить carrier с Reply-клавиатурой; после этого передать уже полученный объект в `_deliver_start_result`, которая добавит toggle при необходимости, отправит отдельную Inline-карточку и запомнит её;
   - уже отправленный `Message`: не пытаться редактировать его в Reply-markup; `logger.warning`, затем отправить carrier отдельным сообщением. Получается два сообщения, содержимое кузова не теряется; returned `Message` запомнить как карточку;
   - `None` или неподдерживаемый объект при `enable_language_switch=False`: один carrier;
   - `None`/неподдерживаемый объект при `enable_language_switch=True`: старый безопасный carrier + штатная языковая карточка.
5. Не прикреплять InlineKeyboardMarkup и ReplyKeyboardMarkup к одному сообщению.

**Тестовая матрица:** False + callback; True без callback; True + plain `ChassisScreen`; True + Inline `ChassisScreen`; True + language toggle; True + returned `Message`; повторный `/start` закрывает прежнюю карточку; callback вызывается ровно один раз.

---

### Фаза 2. Корневая админка и статистика

#### Gate A0: Очистка `/admin`, меню БД и защита от DoS алертов

**Цель:** единое видимое меню для staff/root, root-проверка на серверной стороне, отдельный рабочий экран БД и отсутствие legacy-экранов export/backup.

**Файлы:** `admin/screens.py`, `admin/router.py`, `admin/broadcast.py`, `admin/process.py`, `admin/__init__.py`, `tests/test_admin_v2.py`; обновить намеренно устаревшие ожидания в `tests/test_admin.py` и `tests/test_gate9_admin.py`.

**Константы:**
```python
CB_GO_DB = "adm_go:db_menu"
SECURITY_ALERT_TTL_SECONDS = 60.0
_SECURITY_ALERT_THROTTLE: dict[tuple[str, int, str], float] = {}
```

**Главное меню:**
1. Удалить вызов `command_cheatsheet()` из `_home`, затем удалить саму неиспользуемую функцию и импорт.
2. `home_keyboard` показывает staff и root одинаковые базовые кнопки в порядке: Stats, Find, Broadcast, DB, Maintenance; Restart — только если `process_control is not None`.
3. Прямые Excel/backup-кнопки с главного экрана удалить.
4. `extra_actions.home_rows()` по-прежнему рисовать только root: внешний контракт не расширять.
5. Удалить неиспользуемый `ROOT_ONLY_CALLBACKS`: реальная защита выполняется handler-level guard, а мёртвый список создаёт ложное ощущение ACL.
6. Удалить неиспользуемую обёртку `_home_keyboard` из `admin/router.py`; все вызовы должны идти прямо в `home_keyboard`.

Базовые кнопки и их порядок фиксированы буквально:
```text
[ 📊 Статистика ]
[ 🔍 Найти пользователя ]
[ 📢 Рассылка ]
[ 💾 База данных ]
[ ⚙️ Рубильник ]
[ 🔄 Рестарт бота ]  # только при process_control is not None
```
Не сокращать `🔄 Рестарт бота` до `🔄 Рестарт`, не убирать эмодзи у поиска/рубильника и не возвращать Excel/backup на home.

**Root guard:**
1. Заменить простой `_require_root_call` на helper, принимающий `action_label`.
2. Root получает actor и продолжает.
3. Staff всегда мгновенно получает `call.answer("Access Denied", show_alert=True)`.
4. Security alert отправляется максимум раз в 60 секунд для ключа `(bot_id, actor_id, call.data or action_label)`; время — `time.monotonic()`.
5. При каждой проверке удалить из словаря протухшие ключи, чтобы кэш не рос бесконечно.
6. После определения, что actor не root, вычислить `now`, очистить протухшие ключи и при разрешённом audit **записать `_SECURITY_ALERT_THROTTLE[key] = now` до первого последующего `await`**. Только затем делать `await call.answer(...)` и, если ключ был зарезервирован, `await send_admin_audit(...)`. Так параллельные клики не создают пачку audit-сообщений.
7. Alert отправить через `send_admin_audit(..., is_html=True)` и строить буквально:
   ```html
   🚨 <b>Попытка несанкционированного доступа</b>: админ {actor_identity} (ID: <code>{actor_id}</code>) нажал <b>[{action_label}]</b>
   ```
   `actor_identity` равен `@{escaped_username}` либо `без username`; `action_label` экранировать до помещения внутрь буквальных квадратных скобок. Для рассылки результат — `<b>[Рассылка]</b>`. Ошибка audit не разрешает действие, но handler не падает.
8. Этим guard защитить Broadcast, DB, Excel, backup и все callbacks ProcessControl. Forged callback staff не выполняет операцию.
9. Передать helper в `register_broadcast(..., require_root_call=...)` и заменить им root-проверки четырёх callback handlers `adm_bcast*`; message-handler ввода текста сохраняет обычный `root(message)` filter.
10. В `admin/process.py` все пять вызовов `require_root_call(call)` заменить на `require_root_call(call, "Рестарт бота")`. В router/DB/broadcast передавать стабильные подписи `Рассылка`, `База данных`, `Выгрузка пользователей`, `Бэкап базы данных` — они входят в throttle key через callback data, а в audit-текст через label.

**Меню БД:**
1. Root callback `CB_GO_DB` открывает текст и кнопки Excel, `.db`, `« Назад`.
2. На этом Gate **не рисовать** `👥 Список пользователей`: обработчик появляется только в A5. Это осознанное промежуточное состояние без мёртвой кнопки.
3. Excel-кнопка использует существующий `CB_EXPORT`; handler сразу отвечает `Формирую файл...`, вызывает `_send_xlsx_export` и оставляет DB-панель на месте.
4. Backup использует существующий `CB_DO_BACKUP`; handler сразу отвечает `Готовлю снимок...`, вызывает `_send_backup` и оставляет DB-панель на месте.
5. Полностью удалить `CB_GO_EXPORT`, `CB_GO_BACKUP`, `handle_export_screen`, `handle_backup_screen` и их импорты/экспорты. Slash-команды `/export` и `/backup` не удалять.

Текст DB-экрана копировать буквально, не пересказывать:
```html
💾 <b>Управление базой данных</b>

Выберите действие:
• Выгрузка пользователей — файл Excel (.xlsx) с гиперссылками на профили.
• Бэкап базы данных (.db) — бинарный файл SQLite базы данных проекта.
• Список пользователей — просмотр всей базы прямо в Telegram.
```
В A0 третью строку текста оставить, но кнопку списка ещё не рисовать; она появляется вместе с handler в A5. Кнопки A0 строго: `📥 Выгрузка пользователей (.xlsx)`, `💾 Бэкап базы данных (.db)`, `« Назад`.

**Навигация первого уровня:** добавить `back_only_keyboard(callback_data=CB_HOME)`. Stats, Find и DB используют клавиатуру ровно из одного ряда `[ « Назад ]`. Maintenance сохраняет действие отдельным первым рядом `[ Снять рубильник ]` либо `[ Опустить рубильник ]`, а `back_only_keyboard` даёт только последний ряд `[ « Назад ]`; переключатель `CB_DO_MAINT` не удалять. Общий `nav_keyboard()` оставить для вложенных dossier-экранов.

**Тесты Gate:** одинаковое базовое меню staff/root; root-only операция действительно не запускается у staff; 10 кликов одного действия → 10 alert popup, но один audit; другое действие не подавляется; после 60 секунд alert повторяется; DB actions без промежуточных экранов; удалённые callback-константы больше не встречаются через `rg`.

#### Gate A6: Редизайн экрана «📊 Статистика»

**Цель:** точный макет SPEC на данных текущего tenant и фактического Telegram-бота.

**Файлы:** `admin/router.py`, `tests/test_admin_v2.py`; обновить соответствующие ожидания `tests/test_admin.py` и `tests/test_gate9_admin.py`.

**Расчёты `_dashboard`:**
1. `total`, `sanctioned_total`, `shadow_banned` — из `users` по `bot_id`. `sanctioned_total` считать SQL-условием `is_banned = 1 OR is_shadow_banned = 1`; это число уникальных пользователей хотя бы с одной санкцией. `shadow_banned` считать отдельно. Не использовать `banned + shadow_banned`: пользователь с двумя флагами должен попасть в общий итог один раз.
2. `new_today` — `users.created_at >= midnight UTC+5`, как сейчас.
3. `active_7_days` — `COUNT(DISTINCT user_id)` из `user_bot_statuses` по `(bot_id, telegram_bot_id)` и `last_seen_at >= now_utc - 7 days`. Не использовать `users.updated_at`: санкция администратора не является активностью пользователя.
4. `stars_today` и `stars_total` — только `provider='telegram_stars'`, `currency='XTR'`, `status='paid'`; суммы INTEGER.
5. `gifts` — только реально активные подписки.
6. `open_tickets`, `last_backup`, maintenance — сохранить существующие источники.
7. Поле `scheduler` и вызов `_scheduler_label` удалить из dashboard, если они больше нигде не используются.
8. `last_backup_label`: если записи нет — `нет`; иначе разобрать UTC timestamp существующим `parse_utc`, перевести в `UTC_PLUS_5`, вывести строго `%Y-%m-%d %H:%M (UTC+5)` и не добавлять имя ZIP.
9. `maintenance_label`: `🟢 снят` при `maintenance_on=False`, `🔴 включён` при `True`. Слова `опущен` в статистике не использовать.

**Точный текст:** строить только по следующему шаблону; ссылка на внешний SPEC для реализации не нужна:
```html
📊 <b>Статистика</b>

Пользователи: <b>{total}</b>
Новые сегодня: <b>{new_today}</b>
Активные за 7 дней: <b>{active_7_days}</b>
Баны: <b>{sanctioned_total}</b> (из них Shadow: <b>{shadow_banned}</b>)

Платежи Stars: сегодня <b>{stars_today} ⭐</b> · всего <b>{stars_total} ⭐</b>
Gift-подписки: <b>{gifts}</b>
Открытые обращения: <b>{open_tickets}</b>

Последний бэкап: {last_backup_label}
Рубильник: {maintenance_label}
```
Не добавлять `XTR`, «Планировщик», scheduler-state, роли или пояснения. Строку открытых обращений выводить и при нуле. Между тремя блоками ровно одна пустая строка; после последней строки лишнего `\n` нет.

**Клавиатура:** только `back_only_keyboard()`. Никакой кнопки `В главное меню`.

**Тесты Gate:** фиксированное время; границы ровно 7 дней; чужой `telegram_bot_id` не считается; RUB/USDT и refunded не входят в Stars; Shadow выводится отдельно внутри строки банов; клавиатура содержит одну кнопку.

---

### Фаза 3. Ядро досье и интерактивные подменю

#### Gate A1: Редизайн досье и архитектура Stay-in-Dossier

**Цель:** новая карточка данных и общий безопасный механизм её обновления. На этом Gate сохраняются старые action-кнопки; финальная иерархия кнопок достраивается A2–A4, чтобы ни один промежуточный коммит не имел кнопок без handler.

**Файлы:** `admin/router.py`, `storage/repositories/user_bot_statuses.py`, `tests/test_admin_v2.py`; обновить dossier-ожидания в `tests/test_admin.py`.

**Данные lifecycle:**
1. Расширить `UserBotStatus` полем `last_seen_at: str` и выбирать его в `list_for_user`.
2. Добавить метод:
   ```python
   async def get_for_user(
       self, bot_id: str, user_id: int, telegram_bot_id: int
   ) -> UserBotStatus | None:
   ```
3. `_dossier` получает обязательный keyword-only `telegram_bot_id: int`; все места вызова передают `int(message.bot.id)` либо `int(call.bot.id)`.
4. Не выводить список всех origin-ботов. Базовый статус берётся только для текущего `telegram_bot_id`.

**Единый формат времени досье:** в `admin/router.py` добавить чистый helper `def _format_utc_minute(value: str | None) -> str | None`. Если `value` пуст — вернуть `None`; иначе вызвать существующий `storage.engine.parse_utc(value)`, привести к `timezone.utc` и вернуть `strftime("%Y-%m-%d %H:%M UTC")`. При неразбираемом legacy-значении залогировать warning и вернуть исходную строку без добавления второго `UTC`; renderer экранирует такой fallback один раз. Не использовать `utc_now()` — он создаёт timestamp с секундами, а не форматирует. Не использовать reports `format_local()` — он переводит в UTC+5. Этим helper форматировать и `users.created_at`, и `UserBotStatus.last_seen_at`.

**Приоритет строки `Статус`:**
1. Если есть full ban и shadow — `🔴 Заблокирован · 👤🕶 Теневой бан`.
2. Только full ban — `🔴 Заблокирован`.
3. Только shadow — `👤🕶 Теневой бан`.
4. Иначе lifecycle `deleted` → `⚠️ Аккаунт удалён в Telegram`.
5. Иначе lifecycle `stopped` → `🛑 Бот остановлен пользователем`.
6. Иначе → `🟢 Активен`.

**Точный состав текста:**
- заголовок строго `<b>Досье пользователя</b>`;
- identity-строка строится без догадки: если есть имя — `Имя: <b>{escaped_name}</b>{optional_username} (ID: <code>{user_id}</code>)`; если имени нет, но есть username — `Username: @{escaped_username} (ID: <code>{user_id}</code>)`; если нет обоих — `ID: <code>{user_id}</code>`; `optional_username` равен ` @{escaped_username}` либо пустой строке;
- роль выводить только при наличии: `Суперадминистратор` имеет приоритет над `Администратор`;
- `Первый визит` — `users.created_at`;
- `Последняя активность` — `UserBotStatus.last_seen_at`; если ряда нет, строку не выводить;
- подписка — только активная; lifetime либо дата окончания;
- токены — только если активных vouchers > 0;
- рефералы — только если > 0;
- язык, traffic source, число оплат, нулевые роли/подарки/токены/рефералы не выводить;
- удалить `_lifecycle_lines` и литерал `Санкции сети`; динамические строки вида `profiling: активен` исчезают вместе с циклом всех ботов.

**Порядок и пустые строки досье:**
```text
<заголовок>
<пустая строка>
<identity>
<пустая строка>
Статус: ...
[Роль: ...]
<пустая строка>
Первый визит: ... UTC
[Последняя активность: ... UTC]
[пустая строка + Подписка/Токены/Рефералы без пустот между ними]
[пустая строка + extra_lines]
```
Квадратные скобки здесь означают «весь блок пропускается, если данных нет»; сами скобки в Telegram не выводятся. Даты форматировать единым уже существующим UTC-форматтером проекта; новый второй форматтер не создавать.

Эталон минимальной карточки:
```html
<b>Досье пользователя</b>

Имя: <b>Александр</b> @alexander (ID: <code>123456789</code>)

Статус: 🟢 Активен

Первый визит: 2026-10-05 14:20 UTC
Последняя активность: 2026-10-10 12:45 UTC
```
Эталон полной карточки:
```html
<b>Досье пользователя</b>

Имя: <b>Planferno</b> @Planferno (ID: <code>554750808</code>)

Статус: 🔴 Заблокирован · 👤🕶 Теневой бан
Роль: Суперадминистратор

Первый визит: 2026-10-08 02:59 UTC
Последняя активность: 2026-10-10 15:10 UTC

Подписка: Gift (до 2026-11-08)
Токены: 5 шт.
Рефералы: пригласил 3 чел.
```

**Порты кузова:**
```python
if extra_lines:
    text += "\n\n" + "\n".join(extra_lines)
```
Строки порта не экранировать повторно: контракт кузова уже требует безопасный HTML. Ряды `extra_user_dossier_rows` оставить непосредственно перед навигационным рядом и сохранить формат пар `(text, callback_data)`.

**Stay-in-Dossier engine:**
1. Добавить локальный helper `_show_dossier_call(call, actor_id, target_id, *, keyboard_mode="legacy")`, который заново вызывает `_dossier` и затем `panels.edit_or_send`.
2. В существующем `handle_user_action` после успешного действия вызывать этот helper.
3. Удалить из dossier-flow `panels.freeze_as_report(...)` и последующий `_raise_home(...)`.
4. Сами методы `freeze_as_report` и `_raise_home` не удалять: их используют рубильник, процесс-контроль и другие контуры.
5. На этом Gate оставить старые рабочие ban/shadow/gift/token кнопки, но уже с обновлением на месте. Кнопку и dossier-action `role_adm` удалить сразу: SPEC исключил управление ролями из досье, а slash `/grant` и `/revoke` остаются. Новые menu-callbacks ещё не рисовать.

**Тесты Gate:** три эталонных варианта досье; status precedence; текущий bot vs соседний bot; пропуск пустых строк; HTML-экранирование; sync/async extra ports; повторный callback не падает; после action нет нового home-сообщения.

#### Gate A2: Подменю «🔴 Санкции» и мгновенный разбан

**Цель:** заменить две прямые toggle-кнопки явным подменю и исключить случайную инверсию состояния.

**Файлы:** `admin/router.py`, `tests/test_admin_v2.py`; обновить связанные ожидания `tests/test_admin.py`.

**Сделать буквально:**
1. Базовое досье заменяет прямые ban/shadow-кнопки одной кнопкой `adm_usr:menu:sanctions:<id>`.
   Root-only legacy-кнопки `gift30`/`addvouch` временно остаются до A4; staff их по-прежнему не видит. Это не второй путь одной функции, а контролируемый переход между соседними Gate.
2. Добавить `def _parse_sanction_callback(data: str) -> tuple[str, int] | None`; allowlist строго `{"ban", "unban", "shadow_on", "shadow_off"}`, формат строго четыре сегмента после нормального `split(":")` согласно реестру.
3. Sanctions keyboard строится из свежего `UserRecord`, а не из состояния кнопки:
   - если full ban выключен: `[ 🔴 Выдать бан ]` → `ban`; если включён: `[ 🟢 Снять бан ]` → `unban`;
   - если shadow выключен: `[ 👤🕶 Включить теневой бан ]` → `shadow_on`; если включён: `[ 👤🕶 Снять теневой бан ]` → `shadow_off`;
   - `[ « Назад в досье ] [ В главное меню ]`.
   Тексты и эмодзи копировать буквально; альтернативы `Забанить`, `Разбанить`, `Shadow ON/OFF` запрещены.
4. `unban` вызывает `set_ban(..., False)`; `shadow_off` вызывает `set_shadow_ban(..., False)`. Это явные set-операции, не `not profile.flag`.
5. `adm_usr:menu:dossier:<id>` имеет отдельный exact handler и возвращает базовую клавиатуру досье.
6. После успеха отправить audit и перерисовать **sanctions submenu** через `panels.edit_or_send`. Никаких `freeze_as_report` и `_raise_home`.
7. После ошибки БД показать `call.answer(error, show_alert=True)` и не менять экран.
8. На переходном Gate A2 действия `ban` и `shadow_on` сохраняют прежнее мгновенное включение с причиной `None`. Gate A3 заменит только эти две ветки на Human-in-the-Loop; все остальные ветки уже финальные.
9. Запрет тени для staff-target и запрет бана последнего активного superadmin сохраняются в repository и покрываются тестами.

**Тесты Gate:** exact callback parser; submenu labels; один клик unban/shadow_off; повторное явное снятие безопасно; отказ repository не рисует ложный успех; Stay-in-Dossier.

#### Gate A3: Интерактивный ввод причины бана (PendingInputStore)

**Цель:** причина и вид санкции не теряются между callback и следующим сообщением; команды не поглощаются pending-handler.

**Файлы:** `src/bot_chassis/followup.py`, `src/bot_chassis/__init__.py`, `src/bot_chassis/storage/schema.sql`, `src/bot_chassis/storage/engine.py`, `src/bot_chassis/storage/repositories/users.py`, `src/bot_chassis/admin/lookup.py`, `src/bot_chassis/admin/broadcast.py`, `src/bot_chassis/admin/screens.py`, `src/bot_chassis/admin/router.py`, `tests/test_admin_v2.py`, `tests/test_admin.py`, `tests/test_gate4_lookup.py`, `tests/test_gate5a_support.py`, `tests/test_gate9_admin.py`, `tests/test_gate10_process.py`, узкие migration-тесты в `tests/test_storage.py`. Голого `__init__.py` в этом Gate нет: разрешён только корневой пакетный `src/bot_chassis/__init__.py`.

**Модель pending:**
```python
class AdminSanctionKind(str, Enum):
    BAN = "ban"
    SHADOW_BAN = "shadow_ban"

# добавить внутрь существующего PendingInputKind:
ADMIN_BAN_REASON = "admin_ban_reason"

# добавить последним полем существующего PendingInput:
sanction_kind: AdminSanctionKind | None = None
```
Использовать уже существующие `target_user_id`, `origin_chat_id`, `origin_message_id`; не создавать второй RAM-store.

**Один store без legacy-fallback:**
1. В начале `create_admin_router` создать `resolved_pending_store = pending_store or PendingInputStore()` и ниже использовать только его — в lookup, sanction и при регистрации broadcast.
2. Передать `resolved_pending_store` в `register_broadcast`; начало рассылки очищает lookup через этот же экземпляр, а не через скрытое глобальное состояние.
3. В `admin/lookup.py` сделать аргумент `pending_store: PendingInputStore` обязательным у `begin_admin_lookup`, `cancel_admin_lookup`, `admin_lookup_is_waiting` и `AwaitingAdminLookup`. Параметр `bot_id` можно сохранить для совместимости сигнатур, но он не является ключом второго хранилища.
4. Удалить `_WAITING`, `_TTL_SECONDS`, импорт `time` и `reset_admin_lookups`. TTL берётся только из `PendingInputStore`; две конкурирующие реализации ожидания запрещены.
5. Тесты больше не очищают модульный global через `reset_admin_lookups`: каждый тест создаёт собственный `PendingInputStore` и передаёт его router/helper-ам. Проверки изоляции выполняются отдельными экземплярами store.

**Хранение причины тени:**
1. Добавить `shadow_ban_reason TEXT` в `users` schema.
2. В `StorageEngine._apply_schema` добавить idempotent `_add_column_if_missing` для старых БД.
3. Добавить поле в `UserRecord` и `_row_to_user` с совместимой обработкой старой строки.
4. Изменить `set_shadow_ban(..., reason: Optional[str] = None)`: при включении сохранить reason, при выключении очистить.

**Старт ожидания:**
1. Обработать только `sanction:ban` и `sanction:shadow_on`.
   В `_parse_sanction_callback` расширить allowlist значениями `no_reason` и `cancel`; других действий не принимать.
2. Если `call.message` недоступно — alert и pending не создавать.
3. Записать target, sanction kind, chat/message ID в `PendingScope.ADMIN`.
4. Отрисовать один из двух точных prompt ниже и две кнопки. Никаких `/cancel`, дополнительных подсказок или третьей кнопки:

Для полного бана:
```html
⚠️ <b>Блокировка пользователя {identity}</b> (ID: <code>{user_id}</code>)

Отправьте в чат причину блокировки:
(или выберите блокировку без указания причины)
```

Для теневого бана:
```html
⚠️ <b>Теневой бан пользователя {identity}</b> (ID: <code>{user_id}</code>)

Отправьте в чат причину теневого бана:
(или выберите блокировку без указания причины)
```

`identity` равен `@{escaped_username}`, если username есть, иначе `без username`; не выводить `@None`. Клавиатура строго:
```text
[ ⚡️ Заблокировать без причины ]
[ ❌ Отмена ]
```
Первая кнопка использует `adm_usr:sanction:no_reason:<user_id>`, вторая — `adm_usr:sanction:cancel:<user_id>`.

**Приём текста:**
1. Добавить `AwaitingAdminBanReason` с обязательными PRIVATE/staff filters.
2. Filter возвращает `False` для любого текста, начинающегося с `/`; тогда `/admin` доходит до своего command-handler и очищает pending.
3. Пустой текст не завершает состояние; ответить подсказкой.
4. Причину обрезать до 500 символов тем же правилом, что `/ban`.
5. Перед мутацией атомарно `clear(actor_id, ADMIN)` и работать с возвращённой записью: повторное сообщение уже ничего не применит.
6. По `sanction_kind` вызвать `set_ban(..., True, reason)` либо `set_shadow_ban(..., True, reason)`.
7. Обновить исходную панель новым методом:
   ```python
   async def edit_tracked_or_send(
       self,
       bot,
       bot_id: str,
       actor_id: int,
       text: str,
       markup: InlineKeyboardMarkup,
   ) -> None:
   ```
   Метод получает `(chat_id, message_id)` через `self.get(bot_id, actor_id)`. При отсутствии записи вызывает `send_panel`. Иначе вызывает `bot.edit_message_text(chat_id=..., message_id=..., text=..., reply_markup=markup, parse_mode="HTML")`; `message is not modified` считается успехом; `TelegramBadRequest`, `TelegramForbiddenError` и прочая ошибка логируются и деградируют в `send_panel`. Не пытаться передавать обычный `Message` в `edit_or_send(CallbackQuery, ...)`.
8. После успешного текста причины заново получить базовое досье через `_dossier(..., telegram_bot_id=int(message.bot.id))` с его штатной базовой клавиатурой и передать `text/markup` в `edit_tracked_or_send`. Не добавлять `_dossier` новый параметр ради этого шага. Рисовать sanctions submenu после ввода причины запрещено: финальный экран сценария — обновлённое базовое досье.

**Без причины / отмена / навигация:**
- `no_reason` использует сохранённый `sanction_kind`, reason=`"Не указана"`, затем очищает pending и возвращает базовое досье;
- `cancel` очищает ADMIN-scope и возвращает базовое досье без мутации;
- target ID в `no_reason`/`cancel` обязан совпасть с `pending.target_user_id`; несовпадение даёт alert и не очищает чужое ожидание;
- если pending уже отсутствует/протух, callback отвечает `Действие устарело` и ничего не меняет;
- `/admin`, `adm_home`, `adm_back`, `menu:dossier` перед навигацией очищают только ADMIN-scope;
- SUPPORT, USER, BROADCAST и DOMAIN scopes не трогать.

**Тесты Gate:** full vs shadow причина; миграция существующей БД; команда `/admin` не поглощается; отмена; no_reason; двойная доставка текста применяет санкцию один раз; другой пользователь/scope не затрагивается; исходная панель редактируется либо безопасно пересоздаётся.

#### Gate A4: Подменю «🎁 Управление подпиской»

**Цель:** завершить финальную иерархию досье, сохранив существующий root-only контракт подарков и токенов.

**Файлы:** `admin/router.py`, `tests/test_admin_v2.py`; обновить связанные ожидания `tests/test_admin.py`.

**ACL и базовое досье:**
1. Staff видит только `[ 🔴 Санкции (Бан) ]`.
2. Root видит санкции и `[ 🎁 Управление подпиской ]`.
3. Forged subscription-callback от staff проходит root guard A0: `Access Denied`, security alert, ноль мутаций.
4. После A4 удалить legacy callbacks/actions `gift30` и `addvouch` из старого `_parse_user_callback` и удалить старые прямые кнопки. `role_adm` уже удалён в A1; slash `/grant` и `/revoke` остаются.

**Subscription submenu:** использовать callback-значения из реестра. `revoke` рисовать только при `get_active_subscription(...) is not None`. Навигация — назад в базовое досье и home.

Точные подписи и ряды:
```text
[ 🎁 Подарить 30 дней ] [ ♾ Подарить бессрочно ]
[ 🎟 Начислить +1 токен ]
[ 🚫 Отозвать подписку/Gift ]  # ряд отсутствует без активной подписки
[ « Назад в досье ] [ В главное меню ]
```
Не заменять `♾` текстом `Навсегда`, `токен` словом `талон` и не сокращать подпись revoke.

Добавить `def _parse_subscription_callback(data: str) -> tuple[str, int] | None`; allowlist строго `{"gift30", "giftlife", "token", "revoke"}`. Entry callback `adm_usr:menu:subscription:<id>` обрабатывается отдельно и тоже проходит root guard.

**Операции:**
- `gift30` → `grant_gift_access(..., days=30)`;
- `giftlife` → `grant_gift_access(..., days=None)`;
- `token` → сохранить существующую запись zero-amount `admin_grant` с новым UUID; не менять денежный баланс и не вызывать Stars API;
- `revoke` → `revoke_gift_access(...)`.

После успеха отправить audit и перерисовать **subscription submenu** из свежих данных. Ошибка repository показывается alert и не рисует успех. Все mutations используют явное действие, не toggle.

**Тесты Gate:** staff visibility и forged callback; 30/lifetime; token +1; revoke появляется/исчезает; double edit `message is not modified`; extra rows всё ещё стоят перед навигацией базового досье.

---

### Фаза 4. Поиск, список пользователей и отчётность

#### Gate A5: Поиск и постраничный список пользователей

**Цель:** stateless-список всей tenant-базы с детерминированной пагинацией и безопасными callback_data.

**Файлы:** `storage/repositories/users.py`, `admin/router.py`, `admin/screens.py`, `tests/test_admin_v2.py`; обновить поиск в `tests/test_admin.py`/`tests/test_gate9_admin.py` только по изменённому UI.

**Repository API:**
```python
async def count_users(self, bot_id: str) -> int:
async def list_users_page(
    self, bot_id: str, *, limit: int, offset: int
) -> list[UserRecord]:
```
SQL order строго `ORDER BY created_at DESC, user_id DESC`; `limit=15` — единственный page size Release 2.0. SQL всегда содержит `bot_id`.

**Экран поиска:** скрытую поддержку команды `/cancel` оставить для обратной совместимости, но в сообщении её не показывать. Текст копировать буквально:
```html
🔍 <b>Поиск пользователя</b>

Отправьте в чат @username или числовой ID пользователя.
Либо откройте полный список пользователей базы данных.
```
Клавиатура строго двумя рядами: `[ 👥 Все пользователи базы ]` с `adm_users:p:s:0`, затем `[ « Назад ]` через `back_only_keyboard`. Не использовать общий `nav_keyboard`, иначе появится лишняя кнопка.

**DB menu:** на этом Gate добавить третью кнопку `👥 Список пользователей в Telegram` с `adm_users:p:d:0`. Теперь финальный DB-макет полностью совпадает со SPEC.

**Парсинг страницы:** callback `adm_users:p:<origin>:<page>`, где origin только `s` или `d`, page — неотрицательное целое. Некорректные данные → один `call.answer()` и никакого SQL.

Добавить две чистые функции: `def _parse_users_page_callback(data: str) -> tuple[str, int] | None` и `def _parse_users_open_callback(data: str) -> int | None`. Они не обращаются к БД и тестируются отдельно.

**Рендер списка:**
1. `total_pages = max(1, ceil(total / 15))`; page clamp в диапазон после получения total.
2. Номер строки — `page * 15 + local_index + 1`.
3. Username экранировать; при отсутствии username показать только `<code>user_id</code>`.
4. Статусы: `Суперадмин` имеет приоритет над `Админ`; затем `Заблокирован`, `Shadow`, `Gift`. Пустой набор не рисует тире и скобки.
5. Для каждого пользователя быстрый callback содержит настоящий `user_id`: `adm_users:o:<user_id>`. Не хранить соответствие номеров в RAM.
6. Цифровые кнопки разбить helper-ом на чанки **ровно по пять максимум**.
7. Pagination row рисовать только при `total_pages > 1`; отсутствующее направление не рисовать пустой кнопкой.
   Подписи фиксированы: назад — `⬅️ Назад`, вперёд — `Вперёд ➡️`. Callback сохраняет тот же origin и меняет только page.
8. Нижний ряд: origin `s` → `« Назад в поиск`, origin `d` → `« Назад в БД`; рядом `В главное меню`.
9. Открытие `adm_users:o:<id>` вызывает существующий `_dossier` и сохраняет Stay-in-Dossier; если пользователь исчез — alert `Пользователь не найден`.

Заголовок списка строить буквально:
```html
👥 <b>Пользователи базы</b> (всего: <b>{total}</b>) · Стр. {page + 1}/{total_pages}
```
Строка с username: `{ordinal}. @{escaped_username} (<code>{user_id}</code>){badges_suffix}`. Строка без username: `{ordinal}. <code>{user_id}</code>{badges_suffix}`. `badges_suffix` равен пустой строке, если плашек нет, иначе ` — ` + плашки в порядке `[Суперадмин|Админ] [Заблокирован] [Shadow] [Gift]`. Тире без плашек запрещено. Между заголовком и первой записью одна пустая строка. При `total == 0` после пустой строки вывести `Пользователи не найдены.` и не рисовать цифровые кнопки.

**Производительность:** для максимум 15 строк разрешены repository-вызовы ролей/subscription; не выполнять запрос на всех пользователей заранее и не загружать всю БД в память.

**Тесты Gate:** 0/1/15/16/31 пользователей; стабильный order при одинаковой дате; tenant isolation; 15 цифровых кнопок дают 3 ряда по 5; forged page/origin/id; HTML username; callback длина <64; back destination зависит от origin.

#### Gate A7: Человекочитаемые отчёты и безопасный автобэкап по умолчанию

**Цель:** безопасно изменить значение `None` с «выключено» на «штатная политика для файловой БД», сохранив явный opt-out и тестовую изоляцию.

**Файлы:** `factory.py`, `admin/router.py`, `admin/audit.py`, `scheduler.py`, `reports.py`, `docs/CHASSIS.md`, `docs/LISTENER_INTEGRATION.md`, `docs/PSYBOT_INTEGRATION.md`, `tests/test_admin_v2.py`; разрешённые коррекции `tests/test_gate7_backup.py`, `tests/test_gate8_reports.py`, `tests/test_gate12_release.py`.

**Тип и нормализация:**
```python
backup_policy: BackupPolicy | Literal[False] | None = None

if backup_policy is False:
    resolved_backup_policy: BackupPolicy | None = None
elif backup_policy is None:
    resolved_backup_policy = (
        BackupPolicy() if _is_persistent_sqlite(config.db_path) else None
    )
else:
    resolved_backup_policy = backup_policy
```

`_is_persistent_sqlite(path)` возвращает `False` для `None`, пустой строки, `":memory:"` и URI с `mode=memory`; иначе `True`. Default публичной сигнатуры остаётся строго `None`.

**Критически важно:** после нормализации только `resolved_backup_policy` передаётся в `create_admin_router`, `_dashboard`, `_send_backup` и `BackupScheduler`. Регистрация scheduler — только `if resolved_backup_policy is not None`. Сырой `False` ниже блока нормализации не используется вообще.

**Тестовая изоляция:**
1. Переписать `test_factory_none_skips_scheduler_owner_registers_lifecycle`: для файловой БД `None` теперь ожидает task; отдельный chassis с `backup_policy=False` ожидает `None`; обе ветки завершают `emit_shutdown`.
2. Добавить `:memory:` + `None` → task отсутствует.
3. `TestGate12FactoryContract` продолжает ожидать default `None`; отдельно проверить, что `False` принимается.
4. Тест report-loop из Gate 8 по-прежнему проверяет только report task, но обязан корректно shutdown-ить автоматически поднятый backup task.

**Форматтеры, не строки внутри handlers:**
1. В `admin/audit.py` добавить `format_sanction_audit(...)` для ban/unban/shadow on/off. Все поля target/actor/reason экранируются; `send_admin_audit(..., is_html=True)` получает готовую карточку.
2. В `scheduler.py` добавить `format_backup_notification(result, project_label)`. В конец keyword-only конструкторов `BackupScheduler` и `ReportScheduler` добавить совместимый параметр `project_label: str | None = None`; хранить `self._project_label = project_label or origin_bot_id`. Фабрика обязана передать в оба scheduler-а свой аргумент `project_label`. Форматтер backup вызывается с `self._project_label`, **не** с `self._origin`. `_origin` остаётся техническим ключом claim/ownership и наружу как имя проекта не выводится.
3. Имя архива брать через `Path(...).stem`, экранировать и помещать в `<b>` — расширение `.zip` в Telegram-текст не попадает.
4. В `reports.py` расширить `format_aggregates` keyword-only аргументами `project_label`, `current_origin_bot_id`, `current_telegram_bot_id`; `format_chassis_report` принимает и передаёт их во все daily/weekly/monthly секции. `ReportScheduler` передаёт `self._project_label`, `self._origin`, `self._telegram_bot_id`.
5. В `format_aggregates` сохранить **каждое** поле текущего `ChassisAggregates` ровно один раз: `new_users`, оба вида санкций, paid/refunded count+stars, payment errors, donation count+stars, tickets created/open/in_progress/closed, backup done/failed/details, job failures, restarts, chassis errors и у каждого `per_bot` — active/stopped/deleted/unknown/first_launches. Ничего не суммировать между ботами и ничего не выбрасывать.
6. Размер backup форматировать детерминированно: `<1024` — `N Б`, `1024 <= N < 1024**2` — `N/1024` с одной цифрой и `КБ`, иначе `N/1024**2` с одной цифрой и `МБ`.
7. Failure-уведомление использует точный шаблон ниже, не включает exception, traceback, путь, claim owner или секреты; полная подробность остаётся только в logger и `scheduled_job_runs.details`.

**Точные шаблоны A7:**

Заголовки: daily — `📋 <b>Суточный отчёт рамы</b>`, weekly — `📋 <b>Недельный отчёт рамы</b>`, monthly — `📋 <b>Месячный отчёт рамы</b>`. Все используют одинаковый порядок блоков:
```html
{exact_title}
Период: {period_start} — {period_end} ({policy.tz_label})

👥 <b>Аудитория</b>
• Новые пользователи: <b>{new_users}</b>
{one_audience_line_for_each_per_bot}
• Санкции: баны <b>{banned}</b> · теневые <b>{shadow_banned}</b>

⭐️ <b>Финансы и поддержка</b>
• Оплаты Stars: <b>{paid_stars} ⭐</b> ({paid_count} шт.) · возвраты: <b>{refunded_stars} ⭐</b>
• Ошибки оплат: <b>{payment_errors}</b>
• Донаты Stars: <b>{donation_stars} ⭐</b> ({donation_count} шт.)
• Обращения: создано <b>{tickets_created}</b> · открыто <b>{tickets_open}</b> · в работе <b>{tickets_in_progress}</b> · закрыто <b>{tickets_closed}</b>

💾 <b>Системные задания</b>
• Ночной бэкап: {exact_backup_status}
• Ошибки планировщика: <b>{job_failures}</b> · Ошибки рамы: <b>{chassis_errors}</b>
• Рестарты процессов: <b>{restarts}</b>
```

Для каждого элемента `block.per_bot` вывести отдельную строку, сохраняя сортировку tuple:
```html
• Живая база ({bot_label}): активных <b>{active}</b> · остановлено <b>{stopped}</b> · удалено <b>{deleted}</b> · неизвестно <b>{unknown}</b> · первые запуски <b>{first_launches}</b>
```
`bot_label = project_label`, если одновременно совпали `origin_bot_id == current_origin_bot_id` и `telegram_bot_id == current_telegram_bot_id`; для остальных `bot_label = f"{origin_bot_id} / bot {telegram_bot_id}"`. Label экранировать. Не складывать одинакового пользователя между ботами: это per-bot lifecycle, строки намеренно отдельные.

`exact_backup_status` строить чистым helper-ом строго так:

- `backup_done > 0`, `backup_failed == 0`: `🟢 успешно — запусков <b>{backup_done}</b>{archive_suffix}`;
- оба > 0: `🟡 частично — успешно <b>{backup_done}</b> · ошибок <b>{backup_failed}</b>{archive_suffix}`;
- `backup_done == 0`, `backup_failed > 0`: `🔴 ошибка — неуспешных запусков <b>{backup_failed}</b>`;
- оба равны 0: `⚪ не запускался`.

`archive_suffix` пуст, если `last_backup_details` отсутствует; иначе ` (последний архив: <b>{escaped Path(last_backup_details).stem}</b>)`. Здесь `.zip` убирается только из отображения.

Успешный автобэкап:
```html
💾 <b>Автоматический бэкап базы данных</b>

Статус: 🟢 Успешно ({kind})
Архив: <b>{archive_stem}</b>
Размер: <b>{human_size}</b>
Проект: <b>{project_label}</b>
```

Неуспешный автобэкап:
```html
💾 <b>Автоматический бэкап базы данных</b>

Статус: 🔴 Ошибка
Проект: <b>{project_label}</b>
```

Полный бан:
```html
🚫 <b>Блокировка пользователя</b>

Пользователь: {target_identity} (ID: <code>{target_id}</code>)
Администратор: {actor_identity} (ID: <code>{actor_id}</code>)
Тип санкции: <b>Полный бан</b>
Причина: <b>{reason}</b>
```
Для теневого бана заменить заголовок на `👤🕶 <b>Теневой бан пользователя</b>` и тип на `<b>Теневой бан</b>`. Для снятия санкции использовать заголовки `✅ <b>Пользователь разблокирован</b>` / `✅ <b>Теневой бан снят</b>`; строку причины не выводить. `target_identity`/`actor_identity`: `@username`, если есть, иначе `без username`; все подстановки экранируются внутри форматтера ровно один раз.

**Документация:** заменить старые утверждения `backup_policy=None → без планировщика` на новый контракт; явно документировать `False` и in-memory исключение.

**Тесты Gate:** default file/False/in-memory; ни одной фоновой задачи после shutdown; точные HTML-карточки; `.zip` отсутствует в отправленном тексте, но реальный файл/`scheduled_job_runs.details` не переименовывается; HTML в reason/project/archive экранирован; существующие weekly/monthly отчёты не потеряны.

---

### Фаза 5. Release handoff после зелёного кода

#### Gate R2: Канон рамы, версия 2.0.0 и control plane

**Когда разрешён:** только после PASS контрольных аудитов B1–B5 из `.agents/AUDIT_2_0_IMPLEMENTATION_PROMPT.md` и полного зелёного suite. R2 не исправляет production-код. Если B1–B5 нашли дефект, сначала отдельный correction Gate и повтор соответствующего аудита.

**Разрешённые файлы:** `docs/CHASSIS.md`, `docs/LISTENER_INTEGRATION.md`, `docs/PSYBOT_INTEGRATION.md`, `.agents/ADMIN_REDESIGN_SPEC.md`, `.agents/ACTIVE_PLANS.md`, `.agents/TASK_TODO.md`, `.agents/SESSION_STATE.md`, `.agents/PROJECT_LOG.md`, `CHANGELOG.md`, `VERSION_LOG.md`, `pyproject.toml`, узкие version/docs assertions в `tests/test_gate12_release.py`.

**Делать в таком порядке:**
1. `docs/CHASSIS.md`: заменить статус `0.3.1` на актуальный `2.0.0`; добавить раздел `Миграция 0.3.1 → 2.0.0` со всеми публичными изменениями:
   - `single_message_start=False` и пять его веток;
   - `chassis.screens.retire_active_screen(bot, user_id)`;
   - `backup_policy=None` теперь включает backup только для файловой SQLite, `False` отключает, in-memory не включает;
   - startup destination audit → первый superadmin, без support fallback;
   - новые admin callback-экраны, root-only границы и единый `PendingInputStore`;
   - неизменность `bot_gateway.py` и frozen-suite.
2. `docs/LISTENER_INTEGRATION.md` и `docs/PSYBOT_INTEGRATION.md`: обновить только монтаж публичных контрактов из пункта 1. Не менять код/репозитории кузовов и не заявлять, что потребители уже мигрировали.
3. `.agents/ADMIN_REDESIGN_SPEC.md`: привести §2–§9 к фактически принятой реализации. Обязательно исправить §9.1: startup идёт в audit destination, а при его отсутствии — только первому superadmin; `SUPPORT_CHAT_ID` не является fallback startup. В каждом реализованном пункте поставить статус `реализовано в 2.0.0`; отложенные payment-delivery queue и Ops Sidecar оставить отложенными.
4. `pyproject.toml`: изменить только `[project].version` с `0.3.1` на `2.0.0`.
5. `CHANGELOG.md`: сверху добавить `[2.0.0]` с блоками «Добавлено», «Изменено», «Безопасность», «Совместимость», «Миграция». Не писать SHA, которых ещё нет.
6. `tests/test_gate12_release.py`: изменить/добавить только проверки версии `2.0.0` и новых публичных keyword-only контрактов. Не ослаблять старые проверки.
7. Запустить финальные команды §6. До их успеха не менять статусы control plane на «завершено».
8. После PASS финального аудита B6 обновить `.agents/TASK_TODO.md`, `.agents/ACTIVE_PLANS.md`, `.agents/SESSION_STATE.md`, `.agents/PROJECT_LOG.md`: записать фактические результаты, число тестов, `BASE_REF`, проверенный `HEAD_REF` и отсутствие/наличие tag/push. Не придумывать SHA заранее.
9. `VERSION_LOG.md` обновлять только когда действительно принят новый HEAD `main` или сдвинут tag. Если коммита/tag ещё нет, записать handoff в `PROJECT_LOG.md`, но не создавать фиктивную версию в `VERSION_LOG.md`.
10. Коммит, merge, tag `v2.0.0`, push, live Telegram smoke и переключение потребителей не выполнять без отдельных команд владельца.

**DoD R2:** `rg -n "0\.3\.1" docs/CHASSIS.md docs/LISTENER_INTEGRATION.md docs/PSYBOT_INTEGRATION.md` не находит ложных утверждений о текущей версии; исторические строки миграции допустимы. `pyproject.toml` содержит ровно одну версию `2.0.0`. Канон, SPEC и changelog описывают одинаковые публичные контракты.

---

## Карты микроисполнения и обязательные имена новых тестов

Эта таблица не заменяет описание Gate выше. Она задаёт порядок внутри Gate и не даёт модели «расползтись» по соседнему коду. Если тест с указанным именем уже существует, расширить его; второй тест с суффиксом `_new` не создавать.

### S4-A
1. Сначала написать `test_startup_notification_uses_audit_thread`, `test_startup_notification_falls_back_to_first_superadmin_only`, `test_startup_notification_does_not_use_support_chat`, `test_factory_registers_startup_notification_hook`.
2. Реализовать helper только в `service_notify.py`.
3. Подключить helper только в startup-секции `create_complete_chassis`.
4. Стоп: в diff нет изменений shutdown/report/backup startup hooks.

### S4-B
1. Написать `test_support_history_has_plain_close_button`, `test_history_close_forgets_tracker_before_api`, `test_history_close_bad_request_drops_markup`, `test_history_close_forbidden_drops_markup`, `test_history_close_inaccessible_answers_once`.
2. Изменить markup только в `send_support_history`; изменить только общий navigation handler в `router.py`.
3. Стоп: текст ленты, SQL истории и reply-to не изменились.

### S4-C
1. Написать `test_retire_active_screen_forgets_before_await`, `test_retire_active_screen_is_idempotent`, `test_screens_exists_when_buttons_disabled`, `test_complete_chassis_dataclass_has_required_screens_before_default_fields`.
2. Добавить метод в существующий tracker; затем переместить создание ровно одного tracker выше `if config.enable_buttons`; затем вставить обязательное поле до default-полей и передать тот же объект в результат фабрики.
3. Стоп: публичные методы gateway и `before_chassis_menu_action` не изменены.

### P1
1. Написать `test_invoice_pay_button_is_first_and_cancel_is_second_row`, `test_invoice_cancel_callback_is_constant_under_64_bytes`, `test_invoice_cancel_does_not_touch_storage`, `test_invoice_cancel_answers_once_and_closes`.
2. Сначала изменить invoice markup, затем отдельным микро-шагом зарегистрировать exact handler.
3. Стоп: pre-checkout и successful-payment handlers имеют нулевой diff.

### P2
1. Написать `test_cabinet_slots_are_one_line_without_blank_gap`, `test_cabinet_slot_html_is_escaped_once`, `test_empty_cabinet_has_no_trailing_blank_line`.
2. Изменить только финальную сборку `lines` в renderer кабинета.
3. Стоп: `CabinetSlot`, provider и slot keyboard не изменены.

### P3
1. Написать отдельный parametrized test `test_single_message_start_branch_matrix` со строковыми case-id: `legacy_false`, `plain_screen`, `inline_screen`, `language_toggle`, `returned_message`, `none_without_language`, `none_with_language`.
2. Сначала выделить render/deliver helpers без изменения поведения `False`; прогнать старые factory/integration tests.
3. Затем добавить аргумент фабрики и только ветку `True`.
4. В каждом case посчитать вызовы callback, send/edit и tracker; проверка только текста недостаточна.
5. Стоп: `render_start_callback` нигде не вызывается дважды; одновременно Inline и Reply markup не передаются.

### A0
1. Написать `test_admin_home_has_exact_labels_and_same_base_rows`, `test_root_guard_denies_forged_callback_without_side_effect`, `test_security_alert_exact_html`, `test_security_alert_parallel_clicks_emit_one_audit`, `test_security_alert_is_throttled_per_bot_actor_action`, `test_maintenance_keeps_toggle_and_only_one_back_button`, `test_db_actions_have_no_intermediate_screen`.
2. Сначала изменить чистые keyboard helpers в `admin/screens.py`; затем root guard; затем подключить guard в router/broadcast/process; последним удалить legacy callbacks/imports.
3. После каждого микро-шага прогнать `rg -n "CB_GO_EXPORT|CB_GO_BACKUP|ROOT_ONLY_CALLBACKS|command_cheatsheet|def _home_keyboard" src tests` и сравнить остатки с текущим шагом.
4. Стоп: slash-команды `/export`, `/backup`, `/grant`, `/revoke` и их tests не удалены.

### A6
1. Написать `test_dashboard_uses_current_bot_last_seen_for_active_7_days`, `test_dashboard_counts_user_with_full_and_shadow_once_in_total`, `test_dashboard_stars_exclude_non_xtr_and_refunded`, `test_dashboard_formats_backup_and_maintenance_exactly`, `test_dashboard_exact_html_and_one_back_button`.
2. Сначала получить все числа, затем заменить только renderer текста, затем удалить scheduler-label только после `rg`-доказательства отсутствия других вызовов.
3. Стоп: ни одна admin action/keyboard кроме stats не изменилась.

### A1
1. Написать `test_dossier_exact_minimal_html`, `test_dossier_exact_full_html`, `test_dossier_formats_utc_without_seconds_or_local_shift`, `test_dossier_status_precedence`, `test_dossier_uses_current_telegram_bot_lifecycle`, `test_dossier_action_stays_in_place`.
2. Сначала repository `last_seen_at/get_for_user`; затем `_dossier` data assembly; затем `_dossier_text`; затем keyboard; последним Stay-in-Dossier helper.
3. На каждом вызове `_dossier` явно добавить `telegram_bot_id=`; positional передачу запретить.
4. Стоп: `freeze_as_report`/`_raise_home` удалены только из dossier flow, но их определения и недосьешные вызовы остаются.

### A2
1. Написать `test_sanction_parser_rejects_wrong_shape_and_action`, `test_sanction_menu_has_exact_labels_for_each_flag_combination`, `test_sanction_menu_uses_fresh_flags`, `test_unban_and_shadow_off_are_explicit_idempotent_sets`, `test_sanction_error_does_not_render_success`.
2. Сначала parser, затем keyboard, затем entry/back handlers, затем set-actions.
3. Стоп: `ban`/`shadow_on` пока ещё мгновенные; pending A3 не реализован раньше времени.

### A3
1. Написать `test_admin_sanction_pending_keeps_target_kind_and_origin`, `test_admin_reason_command_is_not_consumed`, `test_admin_reason_double_delivery_mutates_once`, `test_admin_reason_returns_exact_base_dossier_keyboard`, `test_admin_no_reason_and_cancel_validate_target`, `test_lookup_and_sanction_share_one_pending_store`, `test_shadow_reason_migrates_old_database`.
2. Порядок: модель/enum → schema migration → repository → единый store/lookup cleanup → start pending → text filter/handler → no_reason/cancel → tracked edit fallback.
3. После удаления global fallback выполнить `rg -n "_WAITING|_TTL_SECONDS|reset_admin_lookups" src tests`; результат должен быть пустым.
4. Стоп: SUPPORT/USER/BROADCAST/DOMAIN pending tests проходят без изменения их смысла.

### A4
1. Написать `test_subscription_entry_is_root_only_even_when_forged`, `test_subscription_menu_has_exact_labels_and_rows`, `test_subscription_giftlife_token_and_revoke`, `test_subscription_success_rerenders_fresh_state`.
2. Сначала root-only видимость, затем parser, затем menu, затем операции, последним удалить legacy direct actions.
3. Стоп: slash `/gift` и `/gift_revoke` сохранены; Stars balance/payment flow не изменён.

### A5
1. Написать `test_users_page_repository_is_tenant_scoped_and_stable`, `test_users_list_boundaries_0_1_15_16_31`, `test_users_list_badges_use_dash_only_when_present`, `test_users_pagination_has_exact_direction_labels`, `test_users_list_has_at_most_five_number_buttons_per_row`, `test_users_callbacks_are_stateless_and_strict`, `test_users_back_destination_follows_origin`.
2. Сначала repository API; затем чистые parsers; затем pure renderer/helper; затем page handler; затем open handler; последним добавить кнопку в DB menu.
3. Стоп: ни один callback не содержит username/ordinal mapping; не появляется RAM-словарь страниц.

### A7
1. Написать `test_backup_policy_normalization_file_none_false_and_memory`, `test_only_resolved_backup_policy_flows_down`, `test_sanction_audit_exact_html_and_escaping`, `test_backup_notification_uses_factory_project_label_stem_and_human_size`, `test_backup_failure_notification_hides_exception`, `test_report_renders_each_per_bot_row_without_folding`, `test_report_backup_status_all_four_branches`, `test_report_exact_human_labels_keep_every_aggregate`.
2. Сначала чистая нормализация policy; затем factory wiring; затем каждый форматтер отдельно; документы не менять до зелёного кода.
3. Стоп: `False` отсутствует во внутренних типах router/scheduler; реальное имя ZIP и persisted details не переименованы.

### R2
1. Сначала `docs/CHASSIS.md` и интеграционные паспорта; затем SPEC; затем `pyproject.toml`/CHANGELOG/tests; control plane — только после B6 PASS.
2. Обязательные тесты: `test_project_version_is_2_0_0`, `test_release_2_0_public_factory_defaults`, `test_release_2_0_docs_name_new_contracts`.
3. Стоп: никакого tag/push/merge/live smoke; `VERSION_LOG.md` не содержит выдуманный SHA.

---

# ЧАСТЬ III. ИНСТРУКЦИЯ ИСПОЛНЕНИЯ И ПРИЁМКИ

## 1. Что coding-модель делает на каждом Gate

1. Прочитать только описание текущего Gate, перечисленные файлы и связанные существующие тесты.
2. До правок выполнить `git diff -- <файлы Gate>` и не затирать пользовательские изменения.
3. Реализовать только текущий Gate. Не подтягивать код следующего Gate «заодно».
4. Удалить заменённые импорты, функции, константы и callback handlers в пределах Gate; не оставлять второй путь.
5. Запустить узкий тест Gate.
6. Запустить полный `py -m pytest tests -q`.
7. Запустить `py -m pytest tests/test_chassis.py -q` и подтвердить `19 passed`.
8. Выполнить `py -m compileall -q src tests` и `git diff --check`.
9. Показать владельцу diff/stat и результаты. Коммит — только после отдельного разрешения. Следующий Gate автоматически не начинать.

## 2. Разрешённая матрица изменения тестов

| Файл | Можно менять | Нельзя менять |
|---|---|---|
| `tests/test_chassis.py` | Ничего | Любую строку, импорт, имя и число тестов |
| `tests/test_gate_s4.py` | Создать новые тесты S4-A/B/C | Смешивать admin/payments |
| `tests/test_gate5b_tickets.py` | S4-B: заменить только ожидание отсутствующей клавиатуры истории на одну кнопку `Закрыть` с `CB_NAV_CLOSE` | Менять SQL, порядок истории, reply-to и остальные тесты тикетов |
| `tests/test_gate_p.py` | Создать новые тесты P1/P2/P3 | Дублировать весь старый payments-suite |
| `tests/test_admin_v2.py` | Создать новые тесты A0–A7 | Проверять внутренности кузовов |
| `tests/test_payments.py` | Только намеренно изменившийся invoice markup/cancel | Переписывать pre-checkout/successful-payment контракт |
| `tests/test_admin.py` | Старые ожидания текста, кнопок и Stay-in-Dossier; A3 — собственный PendingInputStore вместо global reset | Ослаблять ACL, tenant isolation, команды и ошибки |
| `tests/test_gate4_lookup.py` | A3 — обязательный PendingInputStore, удаление проверок legacy-global с сохранением поведения lookup | Ослаблять TTL, команды, cancel и изоляцию состояний |
| `tests/test_gate5a_support.py` | A3 — общий переданный store для lookup/support и отказ от global reset | Ослаблять разделение scopes и приоритет support |
| `tests/test_gate9_admin.py` | Старые ожидания home/nav/export/backup; A3 — собственный store вместо global reset | Удалять проверки безопасности и screen lifecycle |
| `tests/test_gate10_process.py` | A3 — собственный store вместо global reset | Ослаблять ACL и process-control сценарии |
| `tests/test_gate7_backup.py` | A7: новый default, explicit False, новый текст notification | Ослаблять integrity, rotation, fencing, timeout |
| `tests/test_gate8_reports.py` | A7: новый human-readable текст | Удалять weekly/monthly, periods, claims и delivery tests |
| `tests/test_gate12_release.py` | P3 default False и A7 explicit False; default backup остаётся None | Ослаблять keyword-only и остальные None-default контракты |
| `tests/test_storage.py` | A3: миграция `shadow_ban_reason` | Переписывать старые fixture-схемы без необходимости |

Запрещено «чинить» падение удалением assert или заменой точной проверки на `assertTrue(result)`. Новое ожидание должно прямо соответствовать этому плану.

## 3. По-гейтовые команды проверки

- S4-A/B/C: `py -m pytest tests/test_gate_s4.py tests/test_factory.py tests/test_integration.py -q`
- P1/P2/P3: `py -m pytest tests/test_gate_p.py tests/test_payments.py tests/test_factory.py tests/test_gate12_release.py -q`
- A0/A6: `py -m pytest tests/test_admin_v2.py tests/test_admin.py tests/test_gate9_admin.py -q`
- A1/A2/A4/A5: `py -m pytest tests/test_admin_v2.py tests/test_admin.py tests/test_gate4_lookup.py -q`
- A3: `py -m pytest tests/test_admin_v2.py tests/test_admin.py tests/test_gate4_lookup.py tests/test_gate5a_support.py tests/test_gate9_admin.py tests/test_gate10_process.py tests/test_storage.py -q`
- A7: `py -m pytest tests/test_admin_v2.py tests/test_gate7_backup.py tests/test_gate8_reports.py tests/test_gate12_release.py -q`
- R2: `py -m pytest tests/test_gate12_release.py -q`

После любой узкой команды обязателен полный suite.

## 3.1. Независимые контрольные аудиты — не после каждого Gate

Использовать только `.agents/AUDIT_2_0_IMPLEMENTATION_PROMPT.md` и отдельный чат-аудитор:

1. `B1` после S4-A + S4-B + S4-C. До PASS не начинать P1.
2. `B2` после P1 + P2 + P3. До PASS не начинать A0.
3. `B3` после A0 + A6. До PASS не начинать A1.
4. `B4` после A1 + A2 + A3 + A4. До PASS не начинать A5.
5. `B5` после A5 + A7. Только после PASS разрешён R2.
6. `B6` после R2 — полный сквозной аудит всего Release 2.0.
7. После PASS B6 исполнитель фиксирует фактический handoff в control plane; `B6-CLOSEOUT` проверяет только эти записи.

`BLOCKED` закрывается отдельным correction Gate с собственным diff и повтором того же boundary. `PASS WITH NOTES` не разрешает игнорировать СРЕДНИЕ находки: владелец явно принимает их либо назначает correction Gate.

## 4. Финальный dead-code аудит Release 2.0

Перед релизным handoff выполнить `rg` и подтвердить:

- [ ] В dossier handlers нет `freeze_as_report` и `_raise_home`; глобальные helper-ы сохранены там, где ещё нужны.
- [ ] Нет `command_cheatsheet` и её импорта.
- [ ] Нет неиспользуемых `_home_keyboard` и `ROOT_ONLY_CALLBACKS`.
- [ ] Нет `CB_GO_EXPORT`, `CB_GO_BACKUP`, `handle_export_screen`, `handle_backup_screen`.
- [ ] Нет `_WAITING`, `_TTL_SECONDS`, `reset_admin_lookups` и вызовов lookup-helper без явного `PendingInputStore`.
- [ ] Нет старых dossier-actions `adm_usr:gift30`, `adm_usr:addvouch`, `adm_usr:role_adm`.
- [ ] Нет строки `/cancel — отмена` в UI поиска; скрытая команда `/cancel` может остаться.
- [ ] Нет строк `Санкции сети`, `profiling: активен`, `Планировщик:` и пользовательского `XTR` в новых UI-карточках.
- [ ] Все callback_data из реестра имеют ровно один handler; неизвестные/битые callbacks ничего не меняют и отвечают на query.
- [ ] На первом уровне Stats, Find и DB состоят только из ряда `« Назад`; у Maintenance action-row сохранён, а навигационный ряд содержит только `« Назад`.
- [ ] Home содержит буквальные подписи `📊 Статистика`, `🔍 Найти пользователя`, `📢 Рассылка`, `💾 База данных`, `⚙️ Рубильник`, опционально `🔄 Рестарт бота`.
- [ ] Maintenance сохраняет toggle отдельным рядом и имеет только одну навигационную кнопку `« Назад`.
- [ ] Sanctions/subscription/pagination labels byte-for-byte совпадают с литералами Gate A2/A4/A5.
- [ ] Security alert содержит точный заголовок, escaped identity/label и квадратные скобки вокруг action label.
- [ ] В A5 не более пяти цифровых кнопок в ряду; во всём проекте нет ряда более восьми.

## 5. Финальные runtime-инварианты

- [ ] Startup создаёт максимум одно служебное сообщение и не использует массовую рассылку.
- [ ] Close/delete деградирует на снятие markup при BadRequest и Forbidden.
- [ ] `retire_active_screen` повторно безопасен и экспортирован даже при `enable_buttons=False`; `CompleteChassis` содержит тот же tracker и корректно импортируется как dataclass.
- [ ] Пустой кабинет равен ровно `👤 <b>Аккаунт</b>` без хвостового переноса.
- [ ] Stars pay button находится в `[0][0]`; cancel callback постоянный и короче 64 байт.
- [ ] Single-message режим никогда не теряет Inline markup или language toggle.
- [ ] Staff не может выполнить root-only callback даже подделкой callback_data.
- [ ] Security alert throttle изолирован по `bot_id + actor + action`, очищает старые ключи и резервирует новый ключ до await отправки.
- [ ] Ban pending различает full/shadow, не ловит команды и чистит только ADMIN-scope.
- [ ] Lookup и ban-reason используют один `PendingInputStore`; скрытого второго RAM-state нет.
- [ ] Dossier/list/search экранируют пользовательские поля и сохраняют оба L2-порта кузова.
- [ ] Досье использует UTC без секунд; dashboard считает пересечение full+shadow один раз и показывает точные backup/maintenance labels.
- [ ] `backup_policy=False` нигде не воспринимается как объект политики.
- [ ] `None` запускает backup только для постоянной файловой SQLite; in-memory не запускает.
- [ ] Отчёт сохраняет все поля `ChassisAggregates`, не сворачивает `per_bot`; оба scheduler-а получают фабричный `project_label`, технический `_origin` остаётся только внутренним ключом.
- [ ] После shutdown нет живых `chassis_backup_task`/`chassis_report_task`.

## 6. Финальный выпускной прогон

```powershell
py -m pytest tests -q
py -m pytest tests/test_chassis.py -q
py -m compileall -q src tests
py -m ruff check src --select F401
git diff --check
```

Ожидается: все тесты зелёные; frozen-suite — ровно `19 passed`; предупреждений о незакрытых async tasks нет. Старое число `244 passed` не использовать как ожидаемое: после новых файлов suite обязан вырасти, записывается фактическое число.

После PASS B6 и B6-CLOSEOUT результат фиксируется в `TASK_TODO`, `ACTIVE_PLANS`, `SESSION_STATE`, `PROJECT_LOG`; `VERSION_LOG` — только при реально принятом HEAD/tag. Live Telegram smoke, commit, merge, push, tag и рестарты этим планом автоматически не разрешаются.
