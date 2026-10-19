# NEW_CHAT — короткий bootstrap

Этот файл читается **в начале любого нового чата** в этом репозитории
(правило `.cursor/rules/session-bootstrap.mdc`, `alwaysApply: true`).

Рабочий проект — **Bot Chassis**. Git-root: `C:\Python\bot_chassis`.
Это рама, не кузов. Кузова живут в своих репозиториях и сами зовут порты.

Прочитать по порядку:

1. `.agents/NEW_CHAT.md` — этот короткий вход;
2. `AGENTS.md` (в корне) — канонические правила проекта и control plane;
3. `.agents/SESSION_STATE.md` — фактическое состояние;
4. `.agents/PROJECT_CONTEXT.md` — что это за продукт;
5. `.agents/ACTIVE_PLANS.md` — какие треки живы;
6. `.agents/TASK_TODO.md` — единственная живая очередь;
7. `.agents/AUDIT_LOG_0_3.md` — история аудитов, находок и их закрытия;
8. `.agents/UPGRADE_0_3_PLAN.md` — технические критерии Gate `0.3`;
9. `.agents/UPGRADE_0_3_1_PLAN.md` — технические критерии Gate `0.3.1`;
10. `.agents/ADMIN_REDESIGN_SPEC.md` — утверждённая архитектурная спецификация редизайна админки, досье и отчётов;
11. `.agents/UPGRADE_1_0_PLAN_AUDIT.md` — единственный технический план Release 1.0;
12. `.agents/AUDIT_1_0_IMPLEMENTATION_PROMPT.md` — независимые проверки B1–B6;
13. `docs/CHASSIS.md` — канон рамы, не backlog;
14. `.agents/PROJECT_LOG.md` — только последние релевантные записи.

## Главные ограничения

- Двигаться строго по указанию владельца. Gate очереди не открывать самому.
- Из этого корня не менять PsyBot (`C:\Python\tg_psy_tests`) и Chat Listener
  (`C:\Python\tg_chat_listener`).
- Не переключать checkout Profiling и не ретегать `profiling`.
- `tests/test_chassis.py` заморожен, тестов остаётся 19. Узкие исключения
  `0.3.1`: U1 — строка 104 (`"ℹ️ Info/FAQ"` → `BTN_INFO_RU`); U3 — только
  два существующих тестовых блока команд под `start → domain → menu`; S2 —
  существующий интеграционный тестовый блок под один `SendMessage`. Внутри
  этих блоков разрешены связанные комментарий/докстринг; импорты, структура
  и любые строки вне перечисленных блоков не разрешены.
- Gate U2 `0.3.1` вправе удалить только `cancel_callback` / `cancel_label`
  из `build_support_prompt_keyboard` (breaking — в CHANGELOG и чек-листе
  миграции). Другие сигнатуры Button Chassis не ломать.
- `.env` и секреты не читать.
- Push, force push, live smoke — только после отдельной команды.

---

## СТАРТ СЕЙЧАС

Bot Chassis `1.0.0` завершён на `main`. Implementation/release-коммит —
`3db41c9`; повторный B6 и B6-CLOSEOUT — **PASS**. Проверки: полный suite
**320 passed**, frozen **19 passed**, compile/import/diff чистые.

Аннотированный tag `v1.0.0` является стабильной точкой подключения кузовов и
публикуется вместе с `main`. Старый hold-tag `profiling` остаётся на
`6823f30` и не двигается автоматически. PsyBot, Chat Listener и Profiling
мигрируют только в собственных репозиториях по паспортам из `docs/`.

**Где правда:**

- канонические правила: `AGENTS.md`;
- порядок и статусы Gate: `.agents/TASK_TODO.md`;
- технический план `0.3`: `.agents/UPGRADE_0_3_PLAN.md`;
- единственный технический план `0.3.1`: `.agents/UPGRADE_0_3_1_PLAN.md`;
- архитектурная спецификация редизайна админки: `.agents/ADMIN_REDESIGN_SPEC.md`;
- единственный технический план Release 1.0: `.agents/UPGRADE_1_0_PLAN_AUDIT.md`;
- аудит реализации Release 1.0: `.agents/AUDIT_1_0_IMPLEMENTATION_PROMPT.md`;
- состояние: `.agents/SESSION_STATE.md`;
- история аудитов и текущий handoff: `.agents/AUDIT_LOG_0_3.md`;
- канон: `docs/CHASSIS.md`;
- версии: `VERSION_LOG.md`, `CHANGELOG.md`.

**Следующее действие:** только отдельная миграция выбранного кузова на
`v1.0.0` с его contract-тестами и разрешённым live smoke. Новые функции рамы,
payment-delivery queue, Ops Sidecar и Gate 13 не смешивать с миграцией.
