# SESSION_STATE — передача сессии Bot Chassis

**Дата:** 2026-10-02
**Корень:** `C:\Python\bot_chassis`
**Ветка:** `main`
**Версия:** `0.3.1`
**Profiling hold:** tag `profiling` = `6823f30` (не двигался)

## Фактическое состояние

Пакет `0.3.1` завершён. Сквозной B7 прошёл повторный независимый аудит. Два
блокера последующего release-аудита закрыты: рабочее дерево публичных
документов зафиксировано коммитом `134334d`, release/control-plane документы
синхронизированы. Низкоприоритетные F401 закрыты отдельным коммитом
`ede4ef5`; старые callback-константы сохранены в публичном API через
`__all__`.

Локальный аннотированный тег `v0.3.1` указывает на финальный release-handoff
коммит, содержащий эту запись. Прежний тег на `24df03f` был преждевременным и
локально заменён. Push и force-push не выполнялись.

Кодовый HEAD пакета до release-cleanup: `4955784`. Публичные release-гайды:
`134334d`. Ops Sidecar записан как будущая инициатива в
`.agents/OPS_SIDECAR_CONCEPT.md`; в `0.3.1` он не входит.

## Проверка

- `python -m pytest tests -q` → **244 passed**;
- `python -m pytest tests/test_chassis.py -q` → **19 passed**;
- `python -m compileall -q src tests` → чисто;
- `python -m ruff check src --select F401` → чисто;
- `git diff --check` → чисто перед release-handoff.

## Следующее действие

1. Не push и не запускать live Telegram smoke без отдельной команды.
2. Для потребителя сначала закрепить новый immutable SHA рамы и прогнать его
   mount/contract тесты.
3. Затем открыть отдельный live/crash runbook: старт, меню, поддержка,
   платежный sandbox, рестарт процесса и восстановление после аварии.
4. Gate 13 и Ops Sidecar не открывать вместе с live smoke `0.3.1`.

## Жёсткие границы

- Не менять PsyBot, Chat Listener и Profiling из этого репозитория.
- Не двигать tag `profiling`.
- Не читать и не коммитить секреты.
- Push, force-push, live smoke и системные рестарты требуют отдельной команды.
