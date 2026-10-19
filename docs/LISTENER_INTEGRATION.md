# Спецификация стыковки: Bot Chassis ↔ Chat Listener

**Статус:** канонический паспорт интеграции Chat Listener с Bot Chassis `2.0.0` (готовность рамы к миграции кузова; репозиторий кузова этим паспортом не меняется)

**Рама:** `C:\Python\bot_chassis`

**Кузов:** `C:\Python\tg_chat_listener`

**Точка сборки:** `bot_chassis.factory.create_complete_chassis`

**Зависимость:** `bot-chassis @ git+https://github.com/Aski3108/bot-chassis.git@v2.0.0`

**Хуки Listener:** L1 — `6f2d492`, L2 — `6823f30`

Документ фиксирует границу ответственности, порядок маршрутизации и контракты,
по которым сервис мониторинга Chat Listener монтируется на переносимую раму.
Он не переносит доменную логику Listener в `bot_chassis` и не заменяет
документацию репозитория кузова.

---

## 1. Концепция стыковки («Рама и кузов»)

| Сторона | Владеет | Не владеет |
|---|---|---|
| **Chat Listener (кузов)** | Прослушивание супергрупп и каналов, сбор сообщений, статистика активности, репутация, расширенное досье, режимы доменного диалога | Админка рамы, Stars, системная поддержка, постоянное меню рамы |
| **Bot Chassis (рама)** | Фабрика приложения, админка, платежи, локализация, `/start`, личные меню, поддержка, SQLite-контура рамы | Перехваченные сообщения, групповые метрики, репутационные правила и хранилище Listener |

Основные правила:

1. Listener подключается только через `create_complete_chassis`; ручная повторная
   сборка роутеров рамы не допускается.
2. Один процесс Listener обслуживает два разных контура Telegram:
   - **private:** личные сценарии кузова и интерфейсы рамы;
   - **supergroup / channel:** пассивное наблюдение и доменные команды Listener.
3. Админ-команды и личные меню рамы работают только в `ChatType.PRIVATE`.
   Наблюдение за группой не должно порождать в ней сообщения «Кабинет», Info,
   поддержки или системной админки.
4. Рама не читает доменную БД Listener. Кузов отдаёт только подготовленные строки
   и кнопки через L2-порты.
5. Кузов не меняет исходники рамы и не регистрирует второй обработчик `/start`.

### 1.1. Граница данных

| Данные | Владелец | Канал обмена |
|---|---|---|
| Пользователь, роль, бан, платеж, тикет поддержки | Рама | `CompleteChassis.storage` и порты рамы |
| Перехваченные сообщения и групповые события | Listener | Репозитории Listener |
| Репутация, активность, статус слежения | Listener | L2 `extra_user_dossier_lines` |
| Переходы к логам и групповой статистике | Listener | L2 `extra_user_dossier_rows` + `ExtraAdminActions` |
| Временный ввод поддержки/админ-поиска | Рама | Общий `PendingInputStore` с разными scope |
| Доменный режим диалога Listener | Listener | Собственный FSM либо scope `domain` общего store |

---

## 2. Изоляция Private Chat от наблюдения за группами

Listener обязан различать **наблюдение** и **интерфейс** до выполнения бизнес-логики.

| Тип чата | Разрешено | Запрещено |
|---|---|---|
| `PRIVATE` | `/start`, `/menu`, `/help`, `/support`, админка, личные формы Listener | Групповая атрибуция сообщения без явного доменного сценария |
| `SUPERGROUP` | Сбор сообщений, событий участников и разрешённые групповые команды Listener | Ответы на кнопки личного меню и команды админки рамы |
| `CHANNEL` | Сбор доступных боту публикаций и метаданных | Reply-клавиатура, поддержка, кабинет, административные карточки |
| `GROUP` | Только если этот тип явно поддержан политикой Listener | Неявное включение как побочный эффект широкого `F.text` |

Минимальная фильтрация доменных обработчиков:

```python
from aiogram import F, Router
from aiogram.enums import ChatType

listener_domain = Router(name="listener_domain")


@listener_domain.message(F.chat.type == ChatType.SUPERGROUP)
@listener_domain.channel_post(F.chat.type == ChatType.CHANNEL)
async def collect_public_activity(message):
    # Сохранить событие в доменное хранилище Listener.
    # Наблюдающий обработчик не отвечает в чат.
    await listener_service.capture(message)


@listener_domain.message(
    F.chat.type == ChatType.PRIVATE,
    F.text == "📈 Моя активность",
)
async def show_private_activity(message):
    await listener_service.render_private_activity(message)
```

У обработчика наблюдения не должно быть `message.answer(...)` в штатном пути.
Иначе каждый собранный пост превращается в сервисный спам.

Рама уже ограничивает `PRIVATE`-фильтром:

- админ-команды `/admin`, `/user`, `/ban`, `/unban`, `/shadowban`, `/grant`,
  `/revoke`, `/gift`, `/gift_revoke`, `/export`, `/backup`, `/refund`,
  `/maintenance`;
- навигационные команды `/start`, `/menu`, `/help`, `/support`.

Изоляция рамы не освобождает Listener от собственных `ChatType`-фильтров.

---

## 3. Фабрика и канонический порядок роутеров

`create_complete_chassis` включает роутеры в следующем порядке:

1. **Admin Router** — команды и callbacks админки.
2. **Payments Router** — `pre_checkout_query`, `successful_payment`.
3. **Localization Router** — `core_lang:*`.
4. **Listener Domain Router** — сбор групповых/канальных событий и точные
   приватные сценарии кузова.
5. **Start Router** — единственный обработчик `/start`.
6. **Button Chassis Router** — кабинет, Info, поддержка и нижнее меню.

Aiogram отдаёт событие первому подходящему обработчику. Поэтому Listener
получает приоритет над `/start` и Button Chassis, но не имеет права поглощать
их широким обработчиком.

### 3.1. Требования к `domain_router`

- Передавать в фабрику ещё не подключённый `Router`; не включать его в
  `Dispatcher` второй раз.
- Не регистрировать `Command("start")`. Фабрика обнаружит конфликт и завершит
  сборку с `ValueError`.
- Не ставить безусловный private-обработчик `F.text`: он перехватит `/start`,
  подписи нижнего меню и ввод поддержки.
- Узкие private-обработчики фильтровать по команде, callback-префиксу, состоянию
  Listener или точной подписи доменной кнопки.
- Групповые и канальные обработчики всегда ограничивать `ChatType`.
- Listener-callbacks использовать с собственным префиксом, кроме расширений
  админки, для которых зарезервирован `adm_ops:*`.

Опасный вариант:

```python
@listener_domain.message(F.text)
async def catch_everything(message):
    ...  # Перехватит и личные команды рамы.
```

Безопасный вариант:

```python
@listener_domain.message(
    F.chat.type == ChatType.PRIVATE,
    ListenerDialogFilter(),
    F.text,
)
async def handle_listener_dialog(message):
    ...
```

---

## 4. L1: общее хранилище ввода и хук входа в меню

Коммит `6f2d492` добавил два порта фабрики:

| Порт | Контракт | Назначение Listener |
|---|---|---|
| `pending_store` | `PendingInputStore | None` | Передать один экземпляр хранилища ввода в admin/start/button-контуры и получить его как `chassis.pending_store` |
| `before_chassis_menu_action` | `async (user_id: int) -> None` | Сбросить активный режим Listener до открытия Кабинета, Info или Поддержки |

Если `pending_store=None`, фабрика создаёт штатный `PendingInputStore` с TTL
15 минут. Один и тот же экземпляр получают админка, `/start`, Button Chassis
и вызывающий код через `CompleteChassis.pending_store`.

### 4.1. Scope и запрет взаимного затирания

| Scope | Значение | Владелец |
|---|---|---|
| `PendingScope.USER` | `user_navigation` | Поддержка, отзыв и пользовательская навигация рамы; это scope по умолчанию |
| `PendingScope.ADMIN` | `admin_navigation` | Поиск пользователя в админке |
| `PendingScope.BROADCAST` | `broadcast` | Рассылка |
| `PendingScope.DOMAIN` | `domain` | Формы и режимы Listener, если используется общий store |

Ключ store — `(scope, user_id)`. Поэтому очистка `user_navigation` не удаляет
админский поиск, а доменный ввод Listener можно держать отдельно в `domain`.

Если форма Listener должна быть взаимно исключающей с поддержкой рамы, кузов
может осознанно использовать `PendingScope.USER`. Она всё равно не затронет
`PendingScope.ADMIN`. Для независимой длинной формы предпочтителен
`PendingScope.DOMAIN`.

```python
from bot_chassis import PendingInput, PendingInputKind, PendingInputStore, PendingScope

pending = PendingInputStore(ttl_seconds=900.0)


def begin_listener_form(user_id: int) -> None:
    pending.set(
        user_id,
        PendingInput(kind=PendingInputKind.CUSTOM_INPUT),
        scope=PendingScope.DOMAIN,
    )


def cancel_listener_form(user_id: int) -> None:
    pending.clear(user_id, scope=PendingScope.DOMAIN)
```

### 4.2. `before_chassis_menu_action`

Рама вызывает hook строго перед открытием:

- Кабинета;
- Info;
- Поддержки; для поддержки — до установки ожидания пользовательского сообщения.

```python
async def before_chassis_menu_action(user_id: int) -> None:
    await listener_dialogs.cancel(user_id)  # FSM/режим диалога кузова
    pending.clear(user_id, scope=PendingScope.DOMAIN)
```

Требования к hook:

- асинхронный, быстрый и идемпотентный — повторный вызов безопасен;
- очищает только состояние конкретного пользователя;
- не отправляет сообщения в группу или канал;
- не очищает `PendingScope.ADMIN` и `PendingScope.BROADCAST`;
- обрабатывает ожидаемые ошибки доменного хранилища сам, если меню рамы должно
  открываться при деградации Listener.

Не использовать hook как глобальный `reset_all`: один пользователь не должен
сбросить сбор сообщений или диалоги остальных.

Перед открытием собственного экрана Listener вызывает
`await chassis.screens.retire_active_screen(bot, user_id)`. Метод снимает
кнопки последней карточки рамы и не заменяет `before_chassis_menu_action`.
Этот паспорт не означает, что репозиторий Listener уже переведён.
`single_message_start` по умолчанию `False`: `/start` по-прежнему шлёт носитель Reply-клавиатуры и отдельную карточку. `True` склеивает только простой экран без Inline и без языка. Listener этим паспортом не переключается.

---

## 5. L2: расширенное досье `/user`

Коммит `6823f30` добавил два порта, которые дополняют штатную карточку
пользователя данными Listener.

| Порт | Результат | Позиция в карточке |
|---|---|---|
| `extra_user_dossier_lines(user_id)` | Последовательность строк | После штатного текста и lifecycle-статусов |
| `extra_user_dossier_rows(user_id)` | Последовательность рядов кнопок | Перед рядом «Назад / В главное меню» |

Оба callable могут быть синхронными или асинхронными. Фабрика передаёт им
Telegram `user_id` целевого пользователя, а не ID администратора.

### 5.1. Строки Listener

Рекомендуемый стабильный набор:

```text
Listener: слежение включено
Перехвачено сообщений: 12 480
Активность в группах: 7 групп • последнее событие 2026-10-03 14:20 UTC
Репутация: 82/100 • риск низкий
```

Пример адаптера:

```python
from html import escape


async def listener_dossier_lines(user_id: int) -> tuple[str, ...]:
    summary = await listener_dossiers.get_summary(user_id)
    if summary is None:
        return ("Listener: данных нет",)

    tracking = "включено" if summary.tracking_enabled else "выключено"
    return (
        f"Listener: слежение {tracking}",
        f"Перехвачено сообщений: {summary.message_count}",
        f"Активность в группах: {summary.group_count}",
        f"Репутация: {escape(summary.reputation_label)}",
    )
```

Карточка отправляется с HTML parse mode. Любой текст из групп, профиля или БД
Listener необходимо экранировать через `html.escape`.

### 5.2. Кнопки Listener и фактический формат API

Семантически порт добавляет `sequence[sequence[InlineKeyboardButton]]` в
готовую карточку. Фактический входной формат API рамы `2.0.0` (как и в `0.3.1`) — ряды пар
`(text, callback_data)`; рама сама создаёт `InlineKeyboardButton`.

```python
async def listener_dossier_rows(user_id: int):
    return (
        (("🗂 Лог сообщений", f"adm_ops:listener:messages:{user_id}"),),
        (("📊 Статистика групп", f"adm_ops:listener:groups:{user_id}"),),
    )
```

Не передавать в этот порт готовые объекты `InlineKeyboardButton`: текущий
адаптер распаковывает каждый элемент как пару `text, callback_data`.

Обязательные ограничения:

- `callback_data` начинается с `adm_ops:` — только этот префикс маршрутизируется
  в `extra_admin_actions.handle_callback`;
- значение укладывается в лимит Telegram 64 байта;
- идентификатор пользователя берётся из callback и повторно валидируется;
- кнопки не должны содержать сырой текст или секреты;
- пустая последовательность означает «дополнительных кнопок нет».

### 5.3. Обработчик дополнительных действий

```python
from aiogram.types import CallbackQuery


class ListenerAdminActions:
    def home_rows(self):
        # Listener не обязан добавлять кнопки на главный экран админки.
        return ()

    async def handle_callback(self, call: CallbackQuery) -> bool:
        data = call.data or ""
        prefix = "adm_ops:listener:"
        if not data.startswith(prefix):
            return False

        try:
            _, _, action, raw_user_id = data.split(":", maxsplit=3)
            user_id = int(raw_user_id)
        except (TypeError, ValueError):
            await call.answer("Некорректная команда", show_alert=True)
            return True

        if action == "messages":
            await listener_admin.show_message_log(call, user_id)
            return True
        if action == "groups":
            await listener_admin.show_group_stats(call, user_id)
            return True

        await call.answer("Действие не поддерживается", show_alert=True)
        return True
```

Рама применяет staff ACL до вызова `handle_callback`. Listener всё равно
проверяет корректность целевого `user_id` и доменные ограничения доступа.
Метод возвращает `True`, если callback распознан и обработан; для чужого
`adm_ops:*` — `False`.

---

## 6. Канонический монтаж Listener

Ниже — схема сборки. Имена доменных сервисов являются адаптерами Listener,
а не частью API рамы.

```python
from aiogram import Bot, Dispatcher, Router

from bot_chassis import PendingInputStore, PendingScope
from bot_chassis.commands import register_button_chassis_startup
from bot_chassis.config import BotChassisConfig
from bot_chassis.factory import create_complete_chassis
from bot_chassis.user_lifecycle import CANON_ALLOWED_UPDATES

LISTENER_ALLOWED_UPDATES = (*CANON_ALLOWED_UPDATES, "channel_post")


async def build_listener(bot: Bot):
    dp = Dispatcher()
    domain_router = Router(name="listener_domain")
    pending = PendingInputStore(ttl_seconds=900.0)

    register_listener_group_handlers(domain_router, listener_service)
    register_listener_private_handlers(domain_router, listener_service, pending)

    async def before_chassis_menu(user_id: int) -> None:
        await listener_dialogs.cancel(user_id)
        pending.clear(user_id, scope=PendingScope.DOMAIN)

    config = BotChassisConfig(
        bot_id="chat_listener",
        db_path="chat_listener_chassis.db",
        superadmin_ids=(123456789,),
        support_chat_id=-1001234567890,
        audit_chat_id=-1001234567891,
        enable_payments=False,
        welcome_text=None,
    )

    chassis = await create_complete_chassis(
        bot,
        config,
        dp=dp,
        domain_router=domain_router,
        domain_rows=(("📈 Моя активность",),),
        project_label="Chat Listener",
        pending_store=pending,
        before_chassis_menu_action=before_chassis_menu,
        extra_user_dossier_lines=listener_dossier_lines,
        extra_user_dossier_rows=listener_dossier_rows,
        extra_admin_actions=ListenerAdminActions(),
        allowed_updates=LISTENER_ALLOWED_UPDATES,
    )

    register_button_chassis_startup(chassis.dp, bot)
    return chassis


async def run(bot: Bot) -> None:
    chassis = await build_listener(bot)
    await chassis.dp.start_polling(
        bot,
        allowed_updates=list(LISTENER_ALLOWED_UPDATES),
    )
```

В рабочем Listener конфигурация и ID приходят из его settings/env-слоя; числа
из примера не копируются в production.

Для файловой SQLite значение `backup_policy=None` включает штатный ночной
бэкап. Явное `False` отключает его; для `:memory:` и URI с `mode=memory`
планировщик бэкапа не создаётся.

`message` покрывает сообщения супергрупп, а публикации каналов приходят отдельным
update `channel_post`. Если Listener анализирует правки, он дополнительно включает
`edited_message` и/или `edited_channel_post` и регистрирует одноимённые observers.

### 6.1. Что возвращает фабрика

| Поле `CompleteChassis` | Использование Listener |
|---|---|
| `dp` | Запуск polling/webhook с уже собранным порядком роутеров |
| `storage` | Только данные рамы; не склад перехваченных сообщений |
| `work_gate` | Проверка допуска перед доменной работой, если Listener её применяет |
| `access`, `vouchers`, `cabinet` | Опциональные порты пользовательского продукта |
| `pending_store` | Тот же экземпляр, который передан в фабрику |
| `thread_store` | Хранилище диалога поддержки рамы |
| `screens` | Трекер экранов рамы; `await chassis.screens.retire_active_screen(bot, user_id)` перед переходом в кузов |

Listener не должен создавать второй `Dispatcher` после сборки или вручную
переставлять дочерние роутеры: это разрушит зафиксированный приоритет.

---

## 7. Поведение при ошибках и деградации

| Сбой | Ожидаемое поведение |
|---|---|
| Досье Listener недоступно | Вернуть короткую строку «Listener: данные временно недоступны» либо пустой набор по принятой политике; не подменять штатное досье |
| Нет данных по пользователю | Строка «Listener: данных нет», дополнительные кнопки можно скрыть |
| Неизвестный `adm_ops:listener:*` | Ответить на callback и вернуть `True`, чтобы не оставлять «часики» Telegram |
| Чужой `adm_ops:*` | Вернуть `False` |
| Ошибка сброса диалога перед меню | Либо обработать внутри hook и пропустить в меню, либо осознанно прервать открытие; политика должна быть покрыта тестом |
| Событие из группы не удалось сохранить | Записать ошибку/метрику по политике Listener; не отвечать техническим текстом в наблюдаемый чат |
| Listener выключен | Рама продолжает private-сценарии; L2 возвращает безопасную заглушку или пустые наборы |

Не включать в строки карточки traceback, DSN, токены, внутренние SQL-ошибки или
неэкранированный пользовательский контент.

---

## 8. Антипаттерны стыковки

| Антипаттерн | Последствие | Правильно |
|---|---|---|
| Второй `Command("start")` в Listener | Конфликт владельца старта; фабрика остановит сборку | Старт принадлежит раме, кузов использует `render_start_callback` при необходимости |
| `F.text` без `ChatType`/state в domain router | Кузов съедает меню, поддержку и команды | Точные фильтры по типу чата и сценарию |
| Ответ после каждого собранного сообщения | Спам в супергруппах/каналах | Пассивное сохранение без ответа |
| Один глобальный флаг «пользователь в форме» | Пользователи и админ-поиск затирают друг друга | Ключ `(scope, user_id)` или отдельный FSM Listener |
| Очистка всех scope в menu-hook | Теряется админский поиск/рассылка | Очищать только доменный режим нужного пользователя |
| Callback без `adm_ops:` | Рама не передаст клик в `ExtraAdminActions` | `adm_ops:listener:<action>:<user_id>` |
| Готовый `InlineKeyboardButton` в L2 rows | Ошибка распаковки текущего адаптера | Пары `(text, callback_data)` |
| Запрос доменной БД из исходников рамы | Жёсткая сцепка и утечка домена | Адаптер callable в репозитории Listener |

---

## 9. Чек-лист проверки стыковки

### 9.1. Сборка

- [ ] Listener использует `create_complete_chassis`, а не ручную копию рамы.
- [ ] `domain_router` передан фабрике один раз и до этого не включён в `dp`.
- [ ] В `domain_router` отсутствует `Command("start")`.
- [ ] `pending_store` — один экземпляр; `chassis.pending_store is pending_store`.
- [ ] Переданы оба L1-hook: store и `before_chassis_menu_action`.
- [ ] Переданы оба L2-provider и один экземпляр `extra_admin_actions`.
- [ ] Polling/webhook получает канонические updates, включая `my_chat_member`,
  и Listener-добавку `channel_post`.

### 9.2. Private Chat

- [ ] `/start` даёт один носитель нижней клавиатуры и не дублируется Listener.
- [ ] `/menu`, `/help`, `/support` работают только в личном чате.
- [ ] Кабинет, Info и Поддержка сначала сбрасывают активный диалог Listener.
- [ ] Вход в Поддержку после hook устанавливает штатное ожидание сообщения.
- [ ] Форма Listener не перехватывает текст активной поддержки.
- [ ] Повторный вызов menu-hook безопасен.

### 9.3. Супергруппы и каналы

- [ ] Сообщение (`message`) и публикация (`channel_post`) сохраняются ровно один раз.
- [ ] Наблюдающий обработчик не отвечает в чат.
- [ ] `/admin`, `/user`, `/menu`, `/help`, `/support` в супергруппе не дают
  сервисного ответа рамы.
- [ ] Reply-клавиатура и личные карточки не появляются в группе/канале.
- [ ] Неподдерживаемый тип `GROUP` не включается неявно.

### 9.4. Изоляция состояний

- [ ] `user_navigation` и `admin_navigation` проверены одновременно для одного
  `user_id`.
- [ ] Очистка доменной формы не стирает админский поиск.
- [ ] Очистка пользовательской навигации не стирает domain scope, если сценарии
  объявлены независимыми.
- [ ] Протухшее состояние исчезает после TTL.
- [ ] Состояние одного пользователя не влияет на другого.

### 9.5. Досье и callbacks

- [ ] `/user <id>` показывает штатную карточку и строки Listener внизу.
- [ ] Счётчик сообщений, группы и статус слежения соответствуют доменной БД.
- [ ] Пользовательские строки HTML-экранированы.
- [ ] При отсутствии данных карточка остаётся рабочей.
- [ ] Кнопки Listener стоят перед «Назад / В главное меню».
- [ ] Все callback_data начинаются с `adm_ops:listener:` и не превышают 64 байта.
- [ ] Staff может открыть разрешённые Listener-экраны; посторонний пользователь — нет.
- [ ] `handle_callback` возвращает `True` для своих действий и `False` для чужих.
- [ ] Битый `user_id` не приводит к исключению и не открывает чужое досье.

### 9.6. Регрессия

- [ ] Узкие mount/contract-тесты Listener проходят.
- [ ] Тест порядка роутеров подтверждает `Admin → Payments → Localization →
  Listener Domain → Start → Button Chassis`.
- [ ] Тесты рамы проходят без изменения `tests/test_chassis.py`.
- [ ] Нет правок доменной логики Listener внутри `src/bot_chassis`.
- [ ] Live smoke, push и системный рестарт выполняются только отдельной командой.

---

## 10. Критерии приёмки

Стыковка считается завершённой, когда одновременно выполнены четыре условия:

1. Listener стабильно собирает события из разрешённых супергрупп и каналов,
   не создавая там сервисных ответов.
2. Личные меню и админка рамы доступны только в Private Chat и не конфликтуют
   с приватными формами Listener.
3. `/user` показывает доменную сводку и открывает Listener-действия через
   `adm_ops:*` под ACL рамы.
4. Автоматические тесты подтверждают порядок роутеров, изоляцию scope,
   menu-hook и молчание рамы в группах.

Любое изменение сигнатур L1/L2, префикса `adm_ops:*` или порядка роутеров
требует синхронного обновления этого паспорта и contract-тестов Listener.
