# PROJECT_LOG — Bot Chassis

Журнал работ в стабильной раме `C:\Python\bot_chassis`. Писать сюда при каждом изменении рамы.
Это единственный project log. Корневой `project_log.md` не заводить.

---

## 2026-09-28 — Gate 0: control plane перед кодом 0.3

**Почему.** Перед продуктовыми гейтами Operational Upgrade нужно зафиксировать control plane отдельным документационным коммитом, не смешивая его с кодом рамы.

**Что сделано.** В Git вошли правила и состояние `.agents` (`AGENTS`, `NEW_CHAT`, `SESSION_STATE`, `PROJECT_CONTEXT`, `ACTIVE_PLANS`, `TASK_TODO`, план `UPGRADE_0_3_PLAN`, промпты реализации и аудита), правило `.cursor/rules/session-bootstrap.mdc`, ссылка на control plane из `docs/README.md` и игнор `.agents/local/`. После коммита создана ветка `feat/chassis-0.3` от того же снимка. Код рамы не менялся.

**Проверка.** `pytest tests -q`: **110 passed**. `main` на момент старта содержал 9 локальных коммитов поверх `origin/main` (вершина `42c3cce`). Tag `profiling` = `6823f30`. Worktree `C:\tmp\bot_chassis_psybot_upgrade` чистый; `feat/psybot-network` (`faf10b7`) уже предок `main`.

**Не тронуто.** `src/`, тесты, PsyBot, Chat Listener, Profiling, tag `profiling`, push, удаление worktree. Gate 1 не начат: сначала аудит B0.

---

## 2026-09-27 — фиксация очереди задач рамы

**Почему.** Перед живым прогоном Listener закрывается оговорка аудита о грязном дереве рамы. Существующая очередь по поддержке топиков была полезным локальным документом, а не мусором.

**Что сделано.** `.agents/TASK_TODO.md` добавлен в Git отдельным документационным шагом. Код, зависимости и поведение рамы не менялись.

**Проверка.** Документационный diff и `git diff --check`; продуктовые тесты повторяются из Listener-аудита отдельным шагом.

## 2026-09-27 — вливание `feat/psybot-network` в `main`

**Почему.** Монтаж psybot (P0–P4, PC PASS) и хвосты тикетов закрыты в worktree. Владелец разрешил перенос черновика в стабильную раму. Live smoke не входил.

**Что сделано.**

- Тег `profiling` на `6823f30` — снимок, на котором сидел Profiling Framework до вливания.
- Merge `feat/psybot-network` (`faf10b7`) в `main` с сохранением портов Profiling (`pending_store`, `before_chassis_menu_action`, extra dossier).
- Конфликты: `CHANGELOG.md` (0.2.1 разошлись → сеть стала 0.2.2), `tests/test_factory.py` (оставлены оба набора тестов).
- Заведены `.agents/PROJECT_LOG.md`, `VERSION_LOG.md`, правило `.cursor/rules/chassis-logs.mdc`.
- `pyproject.toml` version → `0.2.2`.

**Затронуто.** Фабрика и админка Profiling не урезаны. Сетевые файлы: sqlite ticket store, support bridge, error_monitor, MAINTENANCE_USAGE, тесты гонки и семи bot ID.

**Не тронуто.** Репозиторий Profiling Framework. `psybot_test`. Push на origin. Live Telegram smoke.

**Тесты.** Полный `pytest tests/` рамы после merge: **110 passed**. Merge-commit: `d3c5de8`.
