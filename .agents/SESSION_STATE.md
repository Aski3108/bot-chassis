# SESSION_STATE — передача сессии Bot Chassis

**Дата:** 2026-10-13
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

Release 2.0 идёт по `.agents/UPGRADE_2_0_PLAN_AUDIT.md`. S4-A/B/C, P1, P2 и P3
закоммичены. P3: `single_message_start=False` по умолчанию. Полный аудит B2
по P1–P3 — PASS: чужих production-файлов нет, frozen-файл не изменён.
Версия пакета остаётся `0.3.1`. Целевая `2.0.0` выставляется только в Gate R2.

## Проверка

- `python -m pytest tests/test_gate_p.py tests/test_payments.py tests/test_factory.py tests/test_gate12_release.py -q` → **35 passed**;
- `python -m pytest tests -q` → **265 passed** после P3;
- `python -m pytest tests/test_chassis.py -q` → **19 passed**;
- `python -m compileall -q src tests` → чисто.

## Следующее действие

1. B2 закрыт с PASS. Следующий Gate — A0; не начинать без отдельной команды владельца.
2. Не push и не запускать live Telegram smoke без отдельной команды.
3. Gate 13, payment-delivery queue и Ops Sidecar не смешивать с Release 2.0.

## Жёсткие границы

- Не менять PsyBot, Chat Listener и Profiling из этого репозитория.
- Не двигать tag `profiling`.
- Не читать и не коммитить секреты.
- Push, force-push, live smoke и системные рестарты требуют отдельной команды.
