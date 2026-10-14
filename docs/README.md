# Документация Bot Chassis

- **[CHASSIS.md](CHASSIS.md)** — канон v1: состав рамы, подключение, порты, тумблеры.
- Эталон окружения: [`examples/.env.example`](../examples/.env.example). Кузов копирует набор рамы и добавляет свои ключи.
- Живой control plane (очередь, состояние, журнал, правила): [`AGENTS.md`](../AGENTS.md) и [`.agents/`](../.agents/). Не дублировать его в `docs/`.
