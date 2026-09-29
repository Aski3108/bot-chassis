# NEW_CHAT — короткий bootstrap

Этот файл читается **в начале любого нового чата** в этом репозитории
(правило `.cursor/rules/session-bootstrap.mdc`, `alwaysApply: true`).

Рабочий проект — **Bot Chassis**. Git-root: `C:\Python\bot_chassis`.
Это рама, не кузов. Кузова живут в своих репозиториях и сами зовут порты.

Прочитать по порядку:

1. `.agents/NEW_CHAT.md` — этот короткий вход;
2. `.agents/AGENTS.md` — правила control plane;
3. `.agents/SESSION_STATE.md` — фактическое состояние;
4. `.agents/PROJECT_CONTEXT.md` — что это за продукт;
5. `.agents/ACTIVE_PLANS.md` — какие треки живы;
6. `.agents/TASK_TODO.md` — единственная живая очередь;
7. `.agents/AUDIT_LOG_0_3.md` — история аудитов, находок и их закрытия;
8. `.agents/UPGRADE_0_3_PLAN.md` — технические критерии Gate `0.3`;
9. `docs/CHASSIS.md` — канон рамы, не backlog;
10. `.agents/PROJECT_LOG.md` — только последние релевантные записи.

## Главные ограничения

- Двигаться строго по указанию владельца. Gate очереди не открывать самому.
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

План `0.3` принят. Gate 0–12 и два Low B4 сделаны на `feat/chassis-0.3`.
B0–B6 закрыты (`PASS` / `PASS WITH NOTES`). Excel строится из SQLite snapshot
вне `BEGIN IMMEDIATE`; протухший nightly claim перехватывается с fencing
владельца. Проверка исполнителя после Low B4: Gate 6–8 **20 passed**, полно
**218 passed**, frozen **19 passed**. Gate 13 (переименование папки/репозитория)
пропущен владельцем 2026-09-29 и в `0.3.0` не входит.
Ветка `feat/chassis-0.3` = `7fe5d93`, запушена в origin.
Git-тег `v0.3.0` не ставился. Tag `profiling` не двигался.

**Где правда:**

- порядок и статусы Gate: `.agents/TASK_TODO.md`;
- единственный технический план: `.agents/UPGRADE_0_3_PLAN.md`;
- состояние: `.agents/SESSION_STATE.md`;
- история аудитов и текущий handoff: `.agents/AUDIT_LOG_0_3.md`;
- канон: `docs/CHASSIS.md`;
- версии: `VERSION_LOG.md`, `CHANGELOG.md`.

**Следующее действие:** короткий независимый повтор двух Low B4 — только в
отдельном чате-аудиторе (этот чат исполнитель, повтор здесь не независим).
Промпт: `.agents/AUDIT_0_3_PROMPT.md`, граница `B4-low-repeat`.
Tag `v0.3.0` — только по отдельной команде. Gate 13 не открывать.
PsyBot, Chat Listener и Profiling из этой рамы не монтировать. L3 нет.
