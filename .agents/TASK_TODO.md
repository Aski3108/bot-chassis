# TASK_TODO — Bot Chassis

**Назначение:** живая очередь задач рамы Bot Chassis (`C:\Python\bot_chassis`).
Все изменения рамы делаются отдельными хирургическими шагами с сохранением обратной совместимости.

---

## Отложено / Backlog

- [ ] **Поддержка топиков супергрупп (`message_thread_id`) в раме (форум/темы).**
  **Контекст:** Проекты (Profiling Framework, Chat Listener, Psybot и др.) переходят на единую супергруппу с темами, чтобы не плодить отдельные чаты.
  **Что требуется сделать в раме (отдельный изолированный этап):**
  1. `BotChassisConfig` (`bot_chassis/config.py`):
     - Добавить опциональные поля: `support_thread_id: int | None = None` и `audit_thread_id: int | None = None`.
  2. `SupportBridge` (`bot_chassis/support_bridge.py`):
     - Передавать `message_thread_id=config.support_thread_id` в `send_user_report_to_support` (`bot.send_message`, `bot.copy_message`).
     - `SupportThreadStore`: учесть топики при регистрации и поиске тикетов, чтобы не ломался Reply админа из топика.
  3. Алерты ошибок и платежей:
     - `bot_chassis.middleware.error_monitor` (`ErrorAlertMiddleware`): передавать `message_thread_id` в `_alert_support`.
     - `bot_chassis.payments.router` (`_notify_support`): передавать `message_thread_id` при уведомлении об оплате Stars.
  4. Обратная совместимость:
     - При отсутствии `*_thread_id` (`None`) поведение остаётся строго прежним (сообщения идут в общий чат или в ветку General).
