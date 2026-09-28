# Agent Control Plane — Bot Chassis

Этот каталог — единственный versioned источник рабочих правил, текущего
состояния, планов, backlog и журнала рамы.

Рабочий корень: `C:\Python\bot_chassis`.
Пакет: `src/bot_chassis`.
Канон: `docs/CHASSIS.md`.

## Разделение ролей

- Архитектурный чат фиксирует решения, границы и очередь. Код рамы он не
  пишет, пока владелец явно не смешает роли в этом чате.
- Coding-чат реализует ровно один подтверждённый Gate из
  `.agents/TASK_TODO.md`; технические критерии Gate берёт только из
  `.agents/UPGRADE_0_3_PLAN.md`.
- Не прыгать через Gate. Соседние «улучшения» и скрытые фиксы запрещены.
- Аудит соседнего кузова (Profiling, PsyBot, Chat Listener) этот репозиторий
  не заменяет и из этого корня не запускает.

## Bootstrap order

1. `.agents/NEW_CHAT.md`
2. `.agents/AGENTS.md`
3. `.agents/SESSION_STATE.md`
4. `.agents/PROJECT_CONTEXT.md`
5. `.agents/ACTIVE_PLANS.md`
6. `.agents/TASK_TODO.md`
7. `.agents/UPGRADE_0_3_PLAN.md` — если работа относится к `0.3`
8. Канон рамы — `docs/CHASSIS.md`
9. `.agents/PROJECT_LOG.md` — только последние релевантные записи
10. Если сдвинулась версия или тег — `VERSION_LOG.md` и `CHANGELOG.md`

## Обязательные правила

- Не создавать альтернативные session state, TODO или project log вне
  `.agents`. Корневой `project_log.md` в этой раме не заводить.
- Перед правкой кода сверять `SESSION_STATE.md` и живую очередь
  `TASK_TODO.md`. Не начинать Gate без подтверждения владельца.
- Одна доработка = одна проверка = один коммит. Новые параметры фабрики
  только keyword-only, в конец списка, по умолчанию `None`. Старый вызов
  без новых параметров обязан вести себя как сейчас.
- `tests/test_chassis.py` заморожен: не менять ни число тестов, ни содержимое.
  Шлюз `src/bot_chassis/bot_gateway.py` и сигнатуры Button Chassis не ломать.
- В раму не класть домен кузова: опросники, LLM, скоры, витрины,
  ЮKassa/CryptoBot, кризисные протоколы, тарифы Listener, клинические шкалы.
- Не делать без явного ТЗ: второй Info-хук, своё хранилище тикетов, выбор
  SQLite по имени бота, перенос бизнес-доступа в раму, новую админку,
  новые сервисы, push.
- Соседние репозитории из этого корня не открывать и не менять:
  `C:\Python\tg_psy_tests` (PsyBot / `psybot_test`),
  `C:\Python\tg_chat_listener` (Chat Listener).
  Profiling Framework — отдельный потребитель; его checkout не переключать.
- Тег `profiling` = hold-точка `6823f30`. Не ретегать и не force-push, пока
  владелец не прикажет отдельно.
- `.agents/SESSION_STATE.md` обновлять перед handoff/коммитом и при смене
  следующего шага. Это не журнал микродействий.
- Значимая итерация сначала есть в очереди; после принятия — запись в
  `.agents/PROJECT_LOG.md`. Если сдвинулись tag или принятый `main` —
  ещё `VERSION_LOG.md` и `CHANGELOG.md`.
- Секреты не читать и не коммитить: `.env`, токены, DSN, ключи.
  В Git только `.env.example`.
- Деструктивные git-операции, push и live Telegram smoke — только по
  отдельной явной команде.
- Для изменённого контура — узкие тесты этого контура. Полный
  `pytest tests -q` перед сдачей среза, если владелец не сузил набор.

## Git и документация

- Канонический Git-root — директория с `.agents/`, `src/bot_chassis/`,
  `docs/` и `tests/`.
- Репозиторий остаётся приватным, пока владелец явно не решит иначе.
- Документы рамы: `docs/CHASSIS.md` (канон), `docs/PSYBOT_INTEGRATION.md`
  (стык с PsyBot, не очередь), `docs/archive/` (история проектирования,
  не backlog).
