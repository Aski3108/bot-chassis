# SESSION_STATE — передача сессии Bot Chassis

**Дата:** 2026-09-28
**Корень:** `C:\Python\bot_chassis`
**Ветка:** `feat/chassis-0.3`
**HEAD:** коммит Gate 5B `feat(support): keep sqlite ticket conversations open`
**Рабочая ветка 0.3:** `feat/chassis-0.3`
**Версия:** `0.2.2` (tag `v0.2.2` = `d3c5de860428f4210d1fe4eb1fc84afe89eee112`)
**Profiling hold:** tag `profiling` = `6823f30`

Живая очередь — `.agents/TASK_TODO.md`. Ниже только то, что нельзя потерять
между чатами.

## Где мы

Полная рама v1 принята (кнопки, storage, порты, админка, Stars, фабрика).
Сетевой пакет R1–R7 влит в стабильный `main` (`d3c5de8`): tenant/origin,
платежи по фактическому Telegram bot ID, SQLite-store поддержки по явной
передаче, `ALREADY_ANSWERED`, команды только в private.

Узкие хуки под Listener закрыты отдельными коммитами:

- L1 `6f2d492` — `pending_store` и `before_chassis_menu_action`;
- L2 `6823f30` — `extra_user_dossier_lines` / `extra_user_dossier_rows`.

После merge: `dfa132d` (hash в VERSION_LOG), `42c3cce` (бэклог в Git).
На диске очередь расширена до девяти пунктов; код по ним не писался.

Control plane `.agents` (этот набор файлов) перенесён 2026-09-28 из той же
схемы, что у `psybot_test` и Chat Listener: `NEW_CHAT`, этот файл,
`PROJECT_CONTEXT`, `ACTIVE_PLANS`, `TASK_TODO`, `PROJECT_LOG`, правило
bootstrap.

## Что уже есть

- Фабрика `create_complete_chassis` и `CompleteChassis`.
- Порты: work_gate, access, vouchers, referrals, cabinet, voucher_consumer.
- Хуки кузова: `render_info_callback`, `extra_admin_actions`, `thread_store`,
  `extra_support_inline`, `pending_store`, `before_chassis_menu_action`,
  extra dossier `/user`.
- Замороженный кнопочный контракт: 19 тестов `tests/test_chassis.py`.
- Канон `docs/CHASSIS.md`, журнал `CHANGELOG.md`, `VERSION_LOG.md`.

## Чего нет и не делать отсюда

- Монтаж Listener или PsyBot в этом репозитории.
- Вторая админка, второе хранилище тикетов, push.
- Переключение Profiling на новый checkout рамы.
- Переименование папки в `telegram_bot_chassis` (пункт 9 очереди, не сейчас).

## Потребители (чужие корни)

| Кузов | Корень | Правило из этой рамы |
|---|---|---|
| PsyBot | `C:\Python\tg_psy_tests` | не открывать, не менять |
| Chat Listener | `C:\Python\tg_chat_listener` | не открывать, не менять |
| Profiling Framework | отдельный репозиторий | hold = tag `profiling`; не переключать |

## Следующий чат

Архитектурно собран подробный план `Bot Chassis 0.3 — Operational Upgrade`:
`.agents/UPGRADE_0_3_PLAN.md`. Он перегруппировывает девять исходных пунктов
по зависимостям и добавляет принятые решения по продолжаемой поддержке,
per-bot lifecycle, вечерним отчётам и process control.

Живой smoke PsyBot добавил в план: мгновенный RU/EN toggle без выбора языка,
на стартовой карточке и внутри Info; во время активного опросника переключение
доступно через Info и не сбрасывает ответы или текущий шаг;
динамические подписи `English / Русский` и `Русский / English`; первичная
локаль по настраиваемой группе Telegram `language_code`
`ru/be/uk/kk/ky/uz/tg/tk/hy/az/ka/pl`, всё прочее и неизвестное → EN, а
ручной выбор сохраняется навсегда. Также зафиксированы единый `/start`, ровно
один Info-ответ, обзорный экран поддержки, отдельные экраны
запроса/отзыва/доната, возврат в кузов и новый нейтральный текст ошибки.

Ошибка live `/start`: `no such table: assessment_answers` в SQLAlchemy PsyBot.
Это доменная схема/миграция кузова, не SQLite Storage рамы; исправлять из этого
корня запрещено. В план рамы также уточнены донаты 50/100/500 Stars и внешний
канал публикации отзывов.

Внешний аудит плана от 2026-09-28 разобран по текущему коду. В план добавлены:
точная миграция единого `/start`; порты стартового/Info/locale/review/process
контуров; `locale_source`; очередь отзывов; уникальный claim планировщика;
разделённые pending scopes; SQLite/JSON-контракты поддержки; матрица трёх
изменяемых frozen-тестов; Gate 1A в коммитной стратегии; Gate 5 разрезан на
5A/5B/5C; уточнены Excel, backup, отчёты, права admin/root и принятые отмены
старого TODO. `TASK_TODO` синхронизирован с принятыми решениями.

Gate 0 зафиксирован 2026-09-28 коммитом
`docs: prepare chassis 0.3 control plane`, ветка `feat/chassis-0.3` создана от
него. Первый B0 обнаружил один корневой дефект: старый подробный `TASK_TODO`
оставался вторым исполняемым техническим планом, а bootstrap-порядок расходился
между инструкциями. По команде владельца выполнена документационная коррекция:
единицей исполнения стал один Gate, единственный технический источник —
`UPGRADE_0_3_PLAN`, старые девять формулировок явно оставлены только как архив,
bootstrap выровнен. Код и тесты не менялись.

Повторная проверка коррекции: `tests/test_chassis.py` — 19 passed,
`pytest tests -q` — 110 passed, `git diff --check` чистый, tag `profiling`
остаётся `6823f30`. Содержательные блокеры B0 сняты и коррекция закоммичена
по команде владельца. Push не делался. Worktree
`C:\tmp\bot_chassis_psybot_upgrade` зарегистрирован на `faf10b7`, который
является предком `main`; удаление не выполнялось.

Gate 1 и Gate 1A выполнены на `feat/chassis-0.3`; повторный B1 — PASS,
ремонт закоммичен как `fef20b7`. Gate 2 выполнен коммитом `3262d77`.
Первый аудит Gate 2 нашёл перенос topic ID в fallback-чат и сверку ответа
поддержки с текущим конфигом. Оба дефекта исправлены: fallback идёт без темы,
а Reply сверяется с темой исходного сообщения. Повторный аудит Gate 2: PASS.
Узкий контур: 58 passed; полный сьют: 137 passed; `git diff --check` чистый.
Gate 3 выполнен. Статус Telegram хранится отдельно по каждому боту.
Первый B2 нашёл потерю `my_chat_member` в throttling, поглощение first-launch
active membership и отсутствие событий смены статуса. Все три дефекта
исправлены: membership не throttled, first-launch имеет отдельный атомарный
claim, реальные переходы lifecycle дают одно events-событие. Повторный B2:
PASS. Узкий контур: 85 passed; полный сьют: 148 passed; `git diff --check`
чистый. Gate 4 выполнен: ID и `@username`, отдельные совпадения не схлопываются.
После внутреннего аудита ожидания поиска и рассылки изолированы парой
`(bot_id, actor_id)`, добавлена двухботовая регрессия. Полный сьют: 152 passed.
Gate 5A выполнен: обзор поддержки, запрос, внешний каталог донатов, раздельные
pending scopes. Полный сьют: 155 passed. Gate 5B выполнен: SQLite-тикет идёт
`open → in_progress → closed`, пользователь отвечает в тот же диалог, JSON
остаётся одноразовым. Полный сьют: 163 passed. Gate 5C не начат. Push не делался.

Промпты: `.agents/IMPLEMENTATION_0_3_PROMPT.md` (ровно один гейт) и
`.agents/AUDIT_0_3_PROMPT.md` (read-only проверка). Независимый аудит обязателен
на границах B0/B1/B2/B3/B4/B5/B6 после Gate 0/1A/3/5C/8/10/12.

Короткий вход нового чата: прочитать `.agents/NEW_CHAT.md`.

## Куда смотреть

- Очередь: `.agents/TASK_TODO.md`
- Канон: `docs/CHASSIS.md`
- Стык PsyBot (справка, не работы): `docs/PSYBOT_INTEGRATION.md`
- Журнал рамы: `.agents/PROJECT_LOG.md`
- Версии: `VERSION_LOG.md`
