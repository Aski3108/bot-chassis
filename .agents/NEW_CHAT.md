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
9. `.agents/UPGRADE_0_3_1_PLAN.md` — технические критерии Gate `0.3.1`;
10. `docs/CHASSIS.md` — канон рамы, не backlog;
11. `.agents/PROJECT_LOG.md` — только последние релевантные записи.

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

Рама v1 принята. Сеть (R1–R7) влита в `main` как **0.2.2**.
Узкие хуки Listener (L1/L2) уже в фабрике и админке.

План `0.3` принят. Gate 0–12 и два Low B4 сделаны на `feat/chassis-0.3`.
B0–B6 закрыты (`PASS` / `PASS WITH NOTES`). Excel строится из SQLite snapshot
вне `BEGIN IMMEDIATE`; протухший nightly claim перехватывается с fencing
владельца. Проверка исполнителя после Low B4: Gate 6–8 **20 passed**, полно
**218 passed**, frozen **19 passed**. Gate 13 (переименование папки/репозитория)
пропущен владельцем 2026-09-29 и в `0.3.0` не входит.
Ветка `feat/chassis-0.3`: landing кода `0.3.0` = `7fe5d93`;
`BASE_REF` для пакета `0.3.1` = `d3c79cd` (последний кодовый SHA до C0).
Git-тег `v0.3.0` не ставился. Tag `profiling` не двигался.

**Где правда:**

- порядок и статусы Gate: `.agents/TASK_TODO.md`;
- технический план `0.3`: `.agents/UPGRADE_0_3_PLAN.md`;
- единственный технический план `0.3.1`: `.agents/UPGRADE_0_3_1_PLAN.md`;
- состояние: `.agents/SESSION_STATE.md`;
- история аудитов и текущий handoff: `.agents/AUDIT_LOG_0_3.md`;
- канон: `docs/CHASSIS.md`;
- версии: `VERSION_LOG.md`, `CHANGELOG.md`.

Независимый `B4-low-repeat` завершён: **PASS WITH NOTES**, обе Low закрыты;
20 узких, 218 полных, 19 frozen и две дополнительные stress-проверки.
Gate C0–U3, S1–S3 и R1 выполнены. Пакет `0.3.1` (Implementation HEAD кода
`4955784`; тег не ставился). `FULL-0.3-RELEASE` объединён с B7.

**Следующее действие:** независимый B7 в отдельном чате — промпт
`.agents/AUDIT_0_3_1_PROMPT.md` (+ чек-лист `0.3.0` из
`.agents/AUDIT_0_3_FULL_PROMPT.md`). Диапазон `v0.2.2 → 0.3.1`. Теги и push
— только по отдельной команде. Gate 13 не открывать. PsyBot, Chat Listener и
Profiling из этой рамы не монтировать. L3 нет.
