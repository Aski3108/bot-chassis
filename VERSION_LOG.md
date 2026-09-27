# VERSION_LOG — Bot Chassis

Стабильная рама: `C:\Python\bot_chassis`, ветка `main`.
Новая строка — только когда сдвинулся tag или принятый HEAD `main`.

---

## v0.2.2 — 2026-09-27

| Поле | Значение |
|---|---|
| Tag | `v0.2.2` (ставится на merge-commit) |
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
