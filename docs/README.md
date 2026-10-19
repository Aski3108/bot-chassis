# Документация Bot Chassis

- **[CHASSIS.md](CHASSIS.md)** — канон 1.0: установка по tag, состав рамы, подключение, порты и тумблеры.
- **[LISTENER_INTEGRATION.md](LISTENER_INTEGRATION.md)** — монтаж Chat Listener.
- **[PSYBOT_INTEGRATION.md](PSYBOT_INTEGRATION.md)** — монтаж сети PsyBot.
- **[PROFILING_INTEGRATION.md](PROFILING_INTEGRATION.md)** — безопасная разморозка и монтаж Profiling Framework.
- Эталон окружения: [`examples/.env.example`](../examples/.env.example). Кузов копирует набор рамы и добавляет свои ключи.
- Живой control plane (очередь, состояние, журнал, правила): [`AGENTS.md`](../AGENTS.md) и [`.agents/`](../.agents/). Не дублировать его в `docs/`.
