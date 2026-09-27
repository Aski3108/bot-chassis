# PROJECT_LOG — Bot Chassis

Журнал работ в стабильной раме `C:\Python\bot_chassis`. Писать сюда при каждом изменении рамы.

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
