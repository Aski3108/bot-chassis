# Промпт независимого аудита реализации Bot Chassis Release 2.0

Этот файл предназначен для **отдельного чата-аудитора**. Исполнитель не аудирует сам себя. Аудит запускается не после каждого Gate, а после пяти логических пакетов и один раз сквозным финальным прогоном.

## 0. Как запускать

Перед каждым запуском владелец подставляет фактические значения:

```text
AUDIT_BOUNDARY={B1|B2|B3|B4|B5|B6|B6-CLOSEOUT}
BASE_REF={SHA до первого Gate проверяемого пакета}
HEAD_REF={SHA/WORKTREE после последнего Gate проверяемого пакета}
TARGET_VERSION=2.0.0
PLAN=.agents/UPGRADE_2_0_PLAN_AUDIT.md
SPEC=.agents/ADMIN_REDESIGN_SPEC.md
```

Границы:

- `B1`: S4-A + S4-B + S4-C;
- `B2`: P1 + P2 + P3;
- `B3`: A0 + A6;
- `B4`: A1 + A2 + A3 + A4;
- `B5`: A5 + A7;
- `B6`: весь диапазон Release 2.0 + R2 до финального закрытия control plane;
- `B6-CLOSEOUT`: только проверка записей control plane после PASS B6, без повторной оценки production-кода.

Если работа ещё не закоммичена, вместо выдуманного `HEAD_REF` напиши `HEAD_REF=WORKTREE` и проверяй `git diff` плюс untracked-файлы. Не объявляй чистым то, что Git не показывает без `--no-index`.

---

## 1. Роль и запреты аудитора

Ты — независимый аудитор репозитория `C:\Python\bot_chassis`.

Ты **ничего не исправляешь**: не меняешь код, тесты, документы, Git index, ветки и теги. Результат — доказанный вердикт и находки. Даже очевидный однострочный фикс только описывается.

Прочитай полностью и в таком порядке:

1. `.agents/NEW_CHAT.md`;
2. `.agents/AGENTS.md`;
3. `.agents/SESSION_STATE.md`;
4. `.agents/PROJECT_CONTEXT.md`;
5. `.agents/ACTIVE_PLANS.md`;
6. `.agents/TASK_TODO.md`;
7. `.agents/UPGRADE_2_0_PLAN_AUDIT.md`;
8. `.agents/ADMIN_REDESIGN_SPEC.md`;
9. `docs/CHASSIS.md`;
10. diff проверяемого диапазона.

Запрещено:

- открывать/менять соседние репозитории PsyBot, Listener и Profiling;
- читать `.env`, токены, DSN и секреты;
- делать commit, merge, checkout, reset, tag, push, рестарт или live Telegram smoke;
- принимать комментарии и названия тестов за доказательство — проверять реальный код и эффекты;
- считать изменение `tests/test_chassis.py` допустимым: файл полностью заморожен и содержит ровно 19 тестов.

## 2. Формат ответа

Первая строка — ровно один вердикт:

```text
PASS
PASS WITH NOTES
BLOCKED
```

Правила:

- `BLOCKED`: нарушен публичный/данный/security контракт, потеряна совместимость, миграция опасна, тесты падают, scope вышел за план или frozen-файл изменён;
- `PASS WITH NOTES`: обязательные требования выполнены, остались только доказанные некритичные замечания;
- `PASS`: обязательных и рекомендательных находок нет.

Каждая находка:

```text
[БЛОКЕР | СРЕДНЯЯ | НИЗКАЯ] Краткое название
Gate: ...
Где: путь:строка
Требование: точный пункт плана
Факт: что реально делает код
Доказательство: команда, тест, traceback или короткая цитата
Последствие: человеческим языком
Минимальная граница исправления: файлы/символы, без написания патча
```

В конце обязательно вывести:

1. матрицу Gate → `PASS/FAIL/NOT IN BOUNDARY`;
2. список запущенных команд и exit code;
3. число полного suite и frozen-suite;
4. изменён ли `tests/test_chassis.py`;
5. список изменённых production-файлов вне разрешённого scope;
6. можно ли открывать следующий Gate/аудит.

---

## 3. Общая процедура для B1–B6

1. Проверить состояние:
   ```powershell
   git status --short
   git diff --stat BASE_REF..HEAD_REF
   git diff --name-status BASE_REF..HEAD_REF
   git diff BASE_REF..HEAD_REF -- tests/test_chassis.py
   ```
   Для `WORKTREE`: использовать `git diff --stat`, `git diff --name-status`, `git diff`; untracked читать отдельно.
2. Сопоставить каждый изменённый файл с разрешённым списком соответствующего Gate. Любой чужой production-файл — минимум СРЕДНЯЯ, изменение публичного контракта — БЛОКЕР.
3. Проверить, что тесты не «починили» удалением assert, broad `except`, заменой exact-проверки на truthy или mock-ом самой проверяемой функции.
4. Выполнить узкий набор boundary, затем:
   ```powershell
   py -m pytest tests -q
   py -m pytest tests/test_chassis.py -q
   py -m compileall -q src tests
   git diff --check
   ```
5. Отдельно посчитать тесты frozen: ожидается ровно `19 passed`.
6. Проверить warnings об unawaited coroutine, pending task, unclosed session и swallowed exception. Такие предупреждения не считать косметикой.
7. Для callback handlers считать реальные вызовы `call.answer`: на обработанный callback ровно один вызов во всех ветках.
8. Для HTML подставить `<`, `>`, `&`, кавычки в каждое пользовательское поле и доказать ровно одно экранирование.
9. Для multi-tenant SQL создать два `bot_id`, одинаковый `user_id` и разные данные; результат одного tenant не должен включать второй.
10. Не выдавать PASS по одному только pytest: обязательны code review, diff-scope и негативные сценарии.

---

## 4. B1 — S4-A/B/C

Узкий прогон:

```powershell
py -m pytest tests/test_gate_s4.py tests/test_factory.py tests/test_integration.py -q
```

### S4-A — startup notification

Проверить:

- существует `deliver_startup_notification(bot, config) -> bool`;
- `bot is None` не вызывает сеть;
- audit destination использует и chat, и thread;
- при отсутствии audit отправка идёт только `superadmin_ids[0]`;
- `support_chat_id` никогда не является startup fallback;
- ошибка первой/единственной отправки не запускает обход остальных superadmin;
- startup hook реально зарегистрирован в dispatcher и вызывается один раз;
- shutdown/report/backup hooks не продублированы;
- текст и `bot_id` HTML-safe.

Негативные прогоны: audit отсутствует; все destinations отсутствуют; Telegram exception; два superadmin; startup emitted дважды последовательно — по одному сообщению на emit, не накопительная регистрация hooks.

### S4-B — close history

Проверить:

- история имеет один ряд с кнопкой `Закрыть`, callback `chassis:nav:close`;
- новый close callback не создан;
- `CB_NAV_CLOSE` завершает handler после закрытия и не рендерит start/support;
- `TelegramBadRequest` и `TelegramForbiddenError` деградируют в снятие markup;
- недоступное сообщение не вызывает delete/edit;
- ошибка fallback логируется и не выходит наружу;
- текст/SQL/order истории не изменены.

### S4-C — retire screen

Проверить:

- сигнатура ровно `retire_active_screen(self, bot, user_id)`;
- `chat_id` берётся из tracker entry;
- `forget_card` происходит до первого await;
- policy только `DROP_MARKUP`;
- повторный и параллельный вызовы безопасны;
- `CompleteChassis.screens` существует при `enable_buttons=False`;
- обязательное поле `screens` стоит до default-полей `thread_store/pending_store`, dataclass импортируется без TypeError, а результат фабрики содержит тот же tracker по identity;
- `before_chassis_menu_action` и `bot_gateway.py` не изменены.

Вердикт B1 BLOCKED, если startup может разослаться более чем одному адресу, close падает на Telegram error или screens отсутствует без buttons.

---

## 5. B2 — P1/P2/P3

Узкий прогон:

```powershell
py -m pytest tests/test_gate_p.py tests/test_payments.py tests/test_factory.py tests/test_gate12_release.py -q
```

### P1 — Stars cancel

- `[0][0]` — pay button с `pay=True`; cancel — отдельный второй ряд;
- callback ровно `chassis:pay:cancel`, не содержит SKU и <64 bytes;
- router использует exact equality;
- cancel не пишет payment/storage, не вызывает consumer и pre-checkout;
- callback answered один раз при success, inaccessible message и Telegram errors;
- delete fallback снимает markup.

### P2 — cabinet

- каждый слот ровно `• <b>Title:</b> Content`;
- между слотами нет пустой строки;
- title/content escaped once;
- порядок slots и keyboard не изменены;
- пустой набор возвращает byte-for-byte `👤 <b>Аккаунт</b>` без trailing `\n`.

### P3 — single-message start

Проверить каждую ветку отдельно и посчитать вызовы:

| Case | Ожидаемый результат |
|---|---|
| `False` + callback | старый carrier, затем старая карточка |
| `True`, callback отсутствует, language off | одно сообщение с Reply keyboard |
| `True`, plain ChassisScreen, language off | одно сообщение: screen text + Reply keyboard |
| `True`, Inline ChassisScreen | carrier + отдельная Inline card |
| `True`, language on | carrier + отдельная language/Inline card |
| `True`, callback вернул Message | уже отправленный Message сохраняется + отдельный carrier |
| `True`, None/unsupported, language off | один carrier |
| `True`, None/unsupported, language on | carrier + штатная language card |

Для всех веток callback вызывается максимум один раз; Inline и Reply markup не передаются в одном запросе; tracker хранит только реальную Inline/returned карточку; повторный `/start` закрывает старую карточку. Default публичной сигнатуры строго `False`, keyword-only, последний аргумент.

Вердикт B2 BLOCKED при потере pay-кнопки, двойном callback, потере language toggle или изменении default-режима.

---

## 6. B3 — A0/A6

Узкий прогон:

```powershell
py -m pytest tests/test_admin_v2.py tests/test_admin.py tests/test_gate9_admin.py -q
```

### A0 — menu, DB, root guard

- staff/root видят одинаковые базовые ряды; restart зависит только от process port; extra rows только root;
- Broadcast, DB, export, backup и все process callbacks защищены server-side;
- forged callback staff показывает `Access Denied`, не запускает side effect;
- audit throttle key содержит bot + actor + action; 10 кликов дают 10 popup и 1 audit;
- при параллельных кликах throttle key резервируется до первого await после решения об отказе; конкурентный прогон также даёт ровно 1 audit;
- другое действие и другой bot не подавляются; expired keys очищаются;
- audit failure не разрешает действие и не валит handler;
- DB action сразу формирует файл, не открывает промежуточный экран;
- в A0 нет кнопки user-list;
- удалены `CB_GO_EXPORT`, `CB_GO_BACKUP`, intermediate handlers, `ROOT_ONLY_CALLBACKS`, `command_cheatsheet`, `_home_keyboard`;
- slash `/export` и `/backup` живы.

Home labels byte-for-byte: `📊 Статистика`, `🔍 Найти пользователя`, `📢 Рассылка`, `💾 База данных`, `⚙️ Рубильник`, опционально `🔄 Рестарт бота`. Security alert byte-for-byte соответствует шаблону плана и содержит `<b>[Название]</b>`. Maintenance сохраняет toggle первым рядом и имеет только один нижний ряд `« Назад`.

Проверить literal DB text и кнопки по плану. Проверить каждый из четырёх `adm_bcast*` и пяти process callbacks, а не один представитель.

### A6 — dashboard

- active7 берётся из `user_bot_statuses.last_seen_at` и фильтруется по bot_id + telegram_bot_id;
- санкция/изменение `users.updated_at` не делает пользователя активным;
- Stars учитывает только `telegram_stars/XTR/paid`;
- граница ровно 7 суток и midnight UTC+5 покрыты;
- текст совпадает с встроенным шаблоном byte-for-byte на fixture;
- пользователь с `is_banned=1` и `is_shadow_banned=1` учитывается в общем числе санкционированных один раз;
- backup time форматируется `YYYY-MM-DD HH:MM (UTC+5)` либо `нет`; maintenance только `🟢 снят`/`🔴 включён`;
- `Открытые обращения` есть при нуле;
- scheduler/XTR отсутствуют в UI;
- клавиатура — одна кнопка `« Назад`.

Вердикт B3 BLOCKED при обходе root guard, cross-tenant утечке или неверной финансовой статистике.

---

## 7. B4 — A1/A2/A3/A4

Узкий прогон:

```powershell
py -m pytest tests/test_admin_v2.py tests/test_admin.py tests/test_gate4_lookup.py tests/test_gate5a_support.py tests/test_gate9_admin.py tests/test_gate10_process.py tests/test_storage.py -q
```

### A1 — dossier

- `UserBotStatus.last_seen_at` читается и `get_for_user` фильтрует три ключа;
- `_dossier(..., *, telegram_bot_id=...)` вызван везде keyword-only;
- lifecycle соседнего Telegram bot не виден;
- status precedence ровно ban+shadow → ban → shadow → deleted → stopped → active;
- минимальная, полная и stopped-карточки exact;
- отсутствующие поля удаляют всю строку, не оставляют `None`, `0`, пустые скобки;
- имя/username/reason escaped once;
- created/last-seen форматируются `YYYY-MM-DD HH:MM UTC` без секунд и без сдвига в UTC+5;
- extra lines/rows остаются на своих L2-позициях;
- dossier action редактирует текущую панель и не вызывает home;
- role_adm отсутствует, slash role commands сохранены.

### A2 — sanctions menu

- strict parser принимает только четыре сегмента и allowlist текущего Gate;
- четыре action labels byte-for-byte совпадают с Gate A2;
- buttons строятся из свежего UserRecord;
- unban/shadow_off — explicit False, повтор безопасен;
- repository error не рисует success;
- ограничения последнего superadmin/staff target сохранены;
- entry/back callbacks exact и остаются в dossier.

### A3 — reason/pending/migration

- pending хранит target, kind, origin chat/message;
- один общий `PendingInputStore`, отсутствуют `_WAITING`, `_TTL_SECONDS`, `reset_admin_lookups`;
- lookup/support/sanction scopes не чистят друг друга;
- message filter PRIVATE + staff и возвращает False для любой `/command`;
- clear-before-mutation гарантирует exactly-once при двойной доставке;
- no_reason/cancel сверяют target; stale callback ничего не меняет;
- full/shadow причины попадают в разные DB-поля; отключение очищает reason;
- миграция старой SQLite идемпотентна и сохраняет строки;
- tracked edit использует сохранённые координаты; bad request/forbidden/other error деградируют в новую panel;
- prompt/buttons exact.
- после text/no_reason/cancel успешный или отменённый сценарий возвращает точную базовую клавиатуру досье, не sanctions submenu.

### A4 — subscription

- staff видит только sanctions; root также subscription;
- forged subscription callback staff отклонён A0 guard и не мутирует данные;
- strict parser и exact callbacks;
- все четыре subscription labels и раскладка рядов byte-for-byte совпадают с Gate A4;
- gift30/lifetime/token/revoke имеют ровно заявленные эффекты;
- token создаёт zero-amount admin_grant и не трогает Stars balance/API;
- revoke виден только при активной subscription;
- после success submenu строится из свежих данных;
- legacy direct actions удалены, slash gift commands сохранены.

Вердикт B4 BLOCKED при обходе ACL, двойной санкции, неверной миграции, потере L2 ports или смешении pending scopes.

---

## 8. B5 — A5/A7

Узкий прогон:

```powershell
py -m pytest tests/test_admin_v2.py tests/test_admin.py tests/test_gate9_admin.py tests/test_gate7_backup.py tests/test_gate8_reports.py tests/test_gate12_release.py -q
```

### A5 — users list

- repository SQL всегда tenant-scoped, order `created_at DESC, user_id DESC`, limit 15;
- проверить 0/1/15/16/31 records и одинаковый created_at;
- parsers pure/strict; negative, plus-sign, extra segment, unknown origin rejected;
- callbacks содержат настоящий user_id, RAM mapping отсутствует;
- максимум 5 цифровых кнопок в ряду;
- pagination row только когда страниц >1, пустых nav buttons нет;
- origin `s/d` возвращает в search/DB соответственно;
- исчезнувший user даёт alert без exception;
- exact search/list text, HTML escaping и callback length;
- badges получают ` — ` только при наличии; pagination labels ровно `⬅️ Назад` / `Вперёд ➡️`;
- DB user-list button появляется только теперь.

### A7 — backup and human reports

- нормализация проверена для file+None, False, `:memory:`, URI `mode=memory`, пустого/None path;
- ниже блока нормализации сырой `backup_policy` не передаётся;
- scheduler создаётся только для resolved policy и корректно shutdown-ится;
- sanction/backup/report cards совпадают с шаблонами и escaped once;
- factory `project_label` передан в оба scheduler-а; backup notification не использует технический `_origin` как имя проекта;
- каждый `per_bot` имеет отдельную строку и сохраняет active/stopped/deleted/unknown/first_launches без свёртки;
- paid/refunded count+stars, payment errors, donations, все ticket states, backup done/failed/details, job failures, restarts и chassis errors присутствуют ровно по одному разу;
- четыре ветки report backup status и точный безопасный failure-notification совпадают с планом;
- `.zip` отсутствует только в Telegram label; файл и DB details не переименованы;
- size boundaries: 0/1023 bytes, 1024 bytes, MB;
- weekly/monthly sections и все прежние агрегаты сохранены;
- failure message не содержит traceback/path/secret, полная ошибка остаётся в logger;
- документы не утверждают старое `None = disabled`.

Вердикт B5 BLOCKED при случайном запуске backup in-memory, трактовке False как policy, потере агрегатов или tenant leak списка.

---

## 9. B6 — финальный сквозной аудит Release 2.0

B6 запускать только после PASS B1–B5 и подготовки R2. Использовать BASE_REF до S4-A и HEAD_REF release candidate.

### 9.1 Полный diff и архитектурные границы

1. Построить матрицу всех 14 code Gate + R2: требование → файл/символ → тест → факт → verdict.
2. Для каждого изменённого production-файла указать, каким Gate он разрешён.
3. Проверить отсутствие дублирующих routers, callbacks, stores, formatters и навигационных стеков.
4. `bot_gateway.py` и `tests/test_chassis.py` должны иметь пустой diff.
5. Новые factory параметры keyword-only; `single_message_start=False`; backup public default `None`.
6. Нет зависимости от порядка тестов и модульных globals, которые текут между chassis instances.

### 9.2 Security/data

1. Forged callbacks: staff→root action; другой actor→pending target; другой bot→user/status/list.
2. Callback fuzz: пустая строка, лишний сегмент, отрицательный/огромный ID, Unicode digits, unknown action, payload >64 bytes.
3. SQL tenant isolation и deterministic pagination.
4. HTML fuzz для имени, username, reason, project, archive.
5. Migration старой DB → новая schema два раза подряд; данные не потеряны.
6. Exactly-once: reason text twice, cancel twice, no_reason twice, invoice cancel twice.

### 9.3 Async/Telegram failure matrix

Для startup, close, retire, dossier edit, audit send, manual backup и scheduled backup проверить success, `TelegramBadRequest`, `TelegramForbiddenError`, generic exception и inaccessible message, где применимо. Не должно быть unhandled exception, второго side effect или зависшего task.

### 9.4 Dead-code proof

Команды должны дать ожидаемо пустой результат в `src tests` (кроме явно исторических документов):

```powershell
rg -n "CB_GO_EXPORT|CB_GO_BACKUP|handle_export_screen|handle_backup_screen|ROOT_ONLY_CALLBACKS|command_cheatsheet|def _home_keyboard" src tests
rg -n "_WAITING|_TTL_SECONDS|reset_admin_lookups" src tests
rg -n "adm_usr:(gift30|addvouch|role_adm)" src tests
rg -n "Санкции сети|profiling: активен|Планировщик:|/cancel — отмена" src tests
```

Отдельно доказать один handler на каждый callback из реестра плана. Простое число текстовых совпадений недостаточно: различать константу, keyboard и decorator.

### 9.5 Документация и версия

- `docs/CHASSIS.md` содержит миграцию 0.3.1→2.0.0 и все новые public contracts;
- integration docs не заявляют, что соседние consumers уже обновлены;
- ADMIN_REDESIGN_SPEC не противоречит startup fallback и фактическому UI;
- `pyproject.toml` version `2.0.0` ровно в одном месте;
- CHANGELOG описывает breaking/compatibility/migration без выдуманных SHA;
- TASK_TODO содержит R2/обновление спецификации шасси;
- до PASS B6 control plane не заявляет релиз завершённым;
- VERSION_LOG не содержит фиктивного tag или непринятого HEAD.

### 9.6 Финальные команды

```powershell
py -m pytest tests -q
py -m pytest tests/test_chassis.py -q
py -m compileall -q src tests
py -m ruff check src --select F401
git diff --check
```

Зафиксировать фактическое число tests. Не использовать старое число `244 passed` как ожидаемое — suite вырос.

B6 может быть PASS только если нет обязательных находок, все тесты зелёные, frozen ровно 19, docs/version синхронны и scope чист.

---

## 10. B6-CLOSEOUT — проверка фиксации результата

Запускается после PASS B6 и после того, как исполнитель обновил только control-plane журналы.

Проверить:

1. `.agents/TASK_TODO.md`: все реально пройденные Gate/Audit отмечены; непройденные не закрыты; сохранён отдельный пункт обновления `docs/CHASSIS.md`/SPEC.
2. `.agents/ACTIVE_PLANS.md`: Release 2.0 имеет фактический статус, ссылку на план и audit prompt.
3. `.agents/SESSION_STATE.md`: дата, ветка, версия, проверенный HEAD, числа full/frozen, следующий шаг и запреты актуальны.
4. `.agents/PROJECT_LOG.md`: одна содержательная release-handoff запись, без выдуманных действий.
5. `VERSION_LOG.md`: запись есть только если реально принят HEAD main или tag; SHA и состояние push проверены через Git.
6. `CHANGELOG.md` и `pyproject.toml` не изменились после B6 иначе чем для исправления найденного блокера.
7. Ни commit, tag, push, merge, restart или live smoke не были сделаны без отдельной команды владельца.

Выдать отдельный `PASS/PASS WITH NOTES/BLOCKED`. Только PASS B6 + PASS B6-CLOSEOUT означает, что Release 2.0 документально закрыт и готов к отдельному решению владельца о commit/tag/push/consumer migration.
