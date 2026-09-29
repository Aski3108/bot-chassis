# Документация Bot Chassis

- **[CHASSIS.md](CHASSIS.md)** — канон v1: состав рамы, подключение, порты, тумблеры.
- Эталон окружения: [`examples/.env.example`](../examples/.env.example). Кузов копирует набор рамы и добавляет свои ключи.
- **[archive/](archive/README.md)** — спеки и планы, по которым раму собрали. Не очередь работ.
- Живой control plane (очередь, состояние, журнал): [`.agents/`](../.agents/AGENTS.md). Не дублировать его в `docs/`.
