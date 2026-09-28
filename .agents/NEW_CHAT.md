# NEW_CHAT — короткий bootstrap

Этот файл читается **в начале любого нового чата** в этом репозитории
(правило `.cursor/rules/session-bootstrap.mdc`, `alwaysApply: true`).

Рабочий проект — **Bot Chassis**. Git-root: `C:\Python\bot_chassis`.
Это рама, не кузов. Кузова живут в своих репозиториях и сами зовут порты.

Прочитать по порядку:

1. `.agents/AGENTS.md` — правила control plane;
2. `.agents/SESSION_STATE.md` — фактическое состояние;
3. `.agents/PROJECT_CONTEXT.md` — что это за продукт;
4. `.agents/ACTIVE_PLANS.md` — какие треки живы;
5. `.agents/TASK_TODO.md` — единственная живая очередь;
6. `docs/CHASSIS.md` — канон рамы, не backlog;
7. `.agents/PROJECT_LOG.md` — только последние релевантные записи.

## Главные ограничения

- Двигаться строго по указанию владельца. Пункт очереди не открывать самому.
- Из этого корня не менять PsyBot (`C:\Python\tg_psy_tests`) и Chat Listener
  (`C:\Python\tg_chat_listener`).
- Не переключать checkout Profiling и не ретегать `profiling`.
- `tests/test_chassis.py` не трогать.
- `.env` и секреты не читать.
- Push, force push, live smoke — только после отдельной команды.

---

## СТАРТ СЕЙЧАС

Рама v1 принята. Сеть (R1–R7) влита в `main` как **0.2.2**.
Узкие хуки Listener (L1/L2) уже в фабрике и админке.

План `0.3` принят. Gate 0 (control plane в Git, ветка `feat/chassis-0.3`)
сделан. Код гейтов 1–13 не начат.

**Где правда:**

- очередь: `.agents/TASK_TODO.md`;
- план исполнения: `.agents/UPGRADE_0_3_PLAN.md`;
- состояние: `.agents/SESSION_STATE.md`;
- канон: `docs/CHASSIS.md`;
- версии: `VERSION_LOG.md`, `CHANGELOG.md`.

**Следующее действие:** независимый аудит B0 по `.agents/AUDIT_0_3_PROMPT.md`.
Gate 1 не открывать, пока владелец не примет `PASS` или `PASS WITH NOTES`.
Один запуск — один гейт. Listener не монтировать. L3 нет.
