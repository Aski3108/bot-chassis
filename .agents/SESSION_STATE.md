# SESSION_STATE — передача сессии Bot Chassis

**Дата:** 2026-10-19
**Корень:** `C:\Python\bot_chassis`
**Ветка:** `main`
**Версия:** `2.0.0`
**Implementation / B6 HEAD:** `3db41c9`
**Release tag:** аннотированный `v2.0.0` на текущем metadata-коммите
**Profiling hold:** tag `profiling` = `6823f30` (не двигался)

## Фактическое состояние

Release 2.0 выполнен по `.agents/UPGRADE_2_0_PLAN_AUDIT.md`: S4-A–C,
P1–P3, A0–A7 и R2 реализованы. Первый B6 был заблокирован документационными
и UI-хвостами. Correction Gate закрыл все подтверждённые находки без новых
слоёв и обходов; повторный B6 2026-10-19 — **PASS**.

Версия пакета — `2.0.0`. `tests/test_chassis.py` и
`src/bot_chassis/bot_gateway.py` не изменены относительно базы Release 2.0.
Владелец отдельной командой разрешил release tag и push. `main` и
аннотированный `v2.0.0` опубликованы; tag `profiling` не двигался.

## Проверка

- correction-набор → **44 passed**;
- B1/B2/admin/A7-R2 → **26/38/78/34 passed**;
- `py -m pytest tests -q` → **320 passed**;
- `py -m pytest tests/test_chassis.py -q` → **19 passed**;
- `py -m compileall -q src tests`, `py -m ruff check src --select F401` и
  `git diff --check` → чисто.

## Следующее действие

1. Выбрать первый кузов и мигрировать его отдельно по паспорту на `v2.0.0`.
2. Не запускать live Telegram smoke или рестарт без отдельной команды.
3. Gate 13, payment-delivery queue, Ops Sidecar и миграции других кузовов не
   смешивать с Release 2.0.

## Жёсткие границы

- Не менять PsyBot, Chat Listener и Profiling из этого репозитория.
- Не двигать tag `profiling`.
- Не читать и не коммитить секреты.
- Push, force-push, live smoke и системные рестарты требуют отдельной команды.
