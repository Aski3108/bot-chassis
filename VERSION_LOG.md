# VERSION_LOG — Bot Chassis

Стабильная рама: `C:\Python\bot_chassis`, ветка `main`.
Новая строка — только когда сдвинулся tag или принятый HEAD `main`.

---

## v2.0.0 — 2026-10-19

| Поле | Значение |
|---|---|
| Tag | аннотированный `v2.0.0`; target = release-metadata коммит с этой записью |
| Branch | `main` |
| Implementation / B6 HEAD | `3db41c9` `release: finalize bot chassis 2.0.0` |
| Previous stable | `v0.3.1` |
| Audit | повторный B6 — PASS; B6-CLOSEOUT — PASS; full 320, frozen 19 |
| Why | Release 2.0: S4-A–C, P1–P3, редизайн админки и досье A0–A7, safe default backup, human reports и release-канон R2 |
| Consumers | закреплять `v2.0.0`; мигрировать каждый кузов отдельно по его паспорту и contract-тестам |
| Profiling hold | старый tag `profiling` = `6823f30` не двигался |
| Push | `main` и `v2.0.0` опубликованы вместе по отдельной команде владельца |

---

## v0.3.1 — 2026-10-02

| Поле | Значение |
|---|---|
| Tag | локальный аннотированный `v0.3.1`; target = release-handoff коммит с этой записью |
| Branch | `main` |
| Implementation HEAD | `4955784` `feat: Gate S3 add operator dialog history from message metadata` |
| Public docs | `134334d` `docs: polish chassis 0.3.1 release guides` |
| Release cleanup | `ede4ef5` `fix(lint): clean chassis public imports` |
| Previous | `0.3.0` landing `7fe5d93`; `BASE_REF` пакета `d3c79cd` |
| Profiling hold | tag `profiling` = `6823f30` (не двигался) |
| Why | UI/навигация/поддержка 0.3.1: RU-лейблы, Отмена/Назад, синее меню start→domain→menu, автор тикета, один ответ оператора, история по метаданным |
| Touched | contracts/keyboards/commands/router/support_bridge/sqlite store/schema; docs CHASSIS + spec; CHANGELOG/pyproject 0.3.1; frozen U1/U3/S2 по разрешению владельца |
| Consumers | переключать только отдельным immutable SHA после contract-тестов потребителя |
| Push | release-cleanup и новый tag локальные; push не выполнялся |

Коммиты пакета после `BASE_REF=d3c79cd` (код до S3; control-plane C0 и легализация frozen — отдельно):

- `181d63b` docs: Gate C0 control plane for chassis 0.3.1
- `0391864` feat: Gate U1 RU main keyboard labels for 0.3.1
- `0991d97` feat: Gate U2 cancel/back navigation canon for 0.3.1
- `4c028f4` fix: preserve frozen cancel tracker contract
- `6383817` feat: Gate U3 blue menu start-domain-menu order for 0.3.1
- `ef623a5` feat: Gate S1 keep ticket author on operator card for 0.3.1
- `b369bd9` feat: Gate S2 deliver support replies as one message for 0.3.1
- `4955784` feat: Gate S3 add operator dialog history from message metadata
- `611682d` docs: authorize exact frozen updates for U3 and S2

---

## v0.3.0 — 2026-09-29 (на `feat/chassis-0.3`, тег не ставился)

| Поле | Значение |
|---|---|
| Tag | не ставился; только по отдельной команде |
| Branch | `feat/chassis-0.3`; landing кода = `7fe5d93`; Base for 0.3.1: `d3c79cd` |
| Previous stable | `v0.2.2` = `d3c5de860428f4210d1fe4eb1fc84afe89eee112` |
| Profiling hold | tag `profiling` = `6823f30` (не двигался) |
| Why | Операционный контур 0.3: меню, темы, lifecycle, админка, Excel snapshot, backup, stale-claim, отчёты, process control, канон env. Gate 13 пропущен. |
| Touched | фабрика keyword-only `None`, schema 0.3, `docs/CHASSIS.md`, `CHANGELOG` 0.3.0, `pyproject` 0.3.0, `tests/test_gate12_release.py` |
| Consumers | Profiling не переключать; монтаж PsyBot / Listener — в их репозиториях, не из этой рамы |
| Push | ветка `feat/chassis-0.3` — по команде владельца 2026-09-29 |

---

## v0.2.2 — 2026-09-27

| Поле | Значение |
|---|---|
| Tag | `v0.2.2` = `d3c5de860428f4210d1fe4eb1fc84afe89eee112` |
| Previous stable | `6823f30` |
| Profiling hold | tag `profiling` = `6823f30` |
| Incoming | `feat/psybot-network` @ `faf10b7` |
| Why | Влить сетевой черновик в стабильный main, не ломая порты Profiling |
| Touched | tickets `ALREADY_ANSWERED` / `resolve_user` closed=None; `audit_chat_id or support_chat_id`; MAINTENANCE_USAGE; factory race + seven-bot tests; CHANGELOG 0.2.2; chassis logs |
| Kept from 0.2.1 | `pending_store`, `before_chassis_menu_action`, extra `/user` dossier ports |
| Profiling Framework | не переключался; pip `-e C:\Python\bot_chassis` теперь видит 0.2.2, откат — checkout tag `profiling` |
| psybot_test | уже на main с P0–P4; этим merge не менялся |
| Push | нет |

Коммиты, вошедшие с `feat/psybot-network` после `170c53f`:

- `defd06a` docs: add PSYBOT_INTEGRATION.md
- `995296e` docs: link PSYBOT_INTEGRATION.md
- `8386422` fix(support): ALREADY_ANSWERED
- `faf10b7` fix(support): resolve_user hides closed tickets

Коммиты `main`, которых не было в черновике (сохранены):

- `8b0a35a` docs: PsyBot integration guide
- `6f2d492` feat(factory): shared pending store and menu hook
- `6823f30` feat(admin): extra dossier lines and rows
