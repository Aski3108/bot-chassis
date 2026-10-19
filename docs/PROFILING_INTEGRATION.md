# Спецификация стыковки: Bot Chassis ↔ Profiling Framework

**Статус:** HOLD; документ описывает текущее крепление и целевую миграцию на Bot Chassis `1.0.0`

**Текущая точка hold:** tag `profiling` → commit `6823f30` (интерфейс рамы `0.2.1`)

**Рама:** `C:\Python\bot_chassis`

**Кузов:** Profiling Framework, отдельный репозиторий-потребитель

**Целевая точка сборки:** `bot_chassis.factory.create_complete_chassis`

**Целевая зависимость:** `bot-chassis @ git+https://github.com/Aski3108/bot-chassis.git@v1.0.0`

Настоящий документ фиксирует архитектурный контракт между переносимой рамой и
платформой психологического профайлинга авторов каналов и текстов. Он является
паспортом интеграции, а не разрешением двигать tag `profiling`, переключать
checkout потребителя или менять код Profiling из репозитория рамы.

---

## 1. Концепция стыковки («Рама и кузов»)

| Сторона | Владеет | Не владеет |
|---|---|---|
| **Profiling Framework (кузов)** | Ввод ссылки на Telegram-канал, загрузка TXT, приём текста, получение источника, психографический анализ, генерация отчёта, рендер инфографики, очередь тяжёлых задач | `/start` после миграции, системное синее меню, админка, платежные чеки и хранилище талонов |
| **Bot Chassis (рама)** | Единый `/start`, Reply-меню, синее меню команд, кабинет, Info, поддержка, админка, WorkGate, Stars, права доступа и талоны | Парсинг каналов, NLP/LLM, психологические модели, промпты, отчёты и изображения Profiling |

Пользовательский путь после разморозки:

1. `/start` обрабатывает рама и показывает постоянное нижнее меню.
2. `render_start_callback` возвращает раме лендинг Profiling.
3. Пользователь запускает анализ кнопкой `🔍 Профайлинг канала` или командой
   `/detect`.
4. Кузов проверяет `work_gate` до любой тяжёлой работы.
5. Кузов валидирует ссылку, TXT или текст и определяет тип отчёта.
6. Для платного подробного отчёта кузов проверяет право доступа либо атомарно
   списывает подходящий талон через `vouchers`.
7. Profiling выполняет анализ и отдаёт текстовый отчёт/инфографику. Рама не
   участвует в вычислении результата.

### 1.1. Граница данных

| Данные | Владелец | Канал стыковки |
|---|---|---|
| Telegram-пользователь, роли, санкции | Рама | middleware, `work_gate`, админка |
| Подписка/подарочный доступ | Рама | `chassis.access` |
| Оплата и активный талон | Рама | `chassis.vouchers` |
| Исходный текст/TXT/ссылка на канал | Profiling | Доменный router и хранилище кузова |
| Извлечённые публикации | Profiling | Доменный pipeline |
| Психографический отчёт | Profiling | Доменное хранилище/renderer |
| Итоговая инфографика | Profiling | Доменный renderer и Telegram delivery |

Рама не должна хранить сырые тексты, признаки модели, психологические оценки
или изображения отчётов в своих таблицах SQLite.

---

## 2. Технический HOLD на `0.2.1`

### 2.1. Зафиксированное состояние

| Параметр | Значение |
|---|---|
| Consumer hold | tag `profiling` |
| Commit рамы | `6823f30` |
| Интерфейс рамы | `0.2.1` |
| Состояние | Заморожено до миграции навигации и contract-тестов Profiling |
| Запрет | Не ретегать, не force-push и не переключать checkout без отдельного решения владельца |

Hold — это рабочая защита совместимости. Он не означает, что актуальная рама
должна сохранять старую модель `/start` ради Profiling.

### 2.2. Почему нельзя просто заменить SHA на `1.0.0`

В интерфейсе `0.2.1` Profiling мог иметь:

- собственный независимый `Command("start")`;
- собственную команду `/detect`;
- собственную логику формирования Telegram command menu;
- старое понимание «Отмена» и «Назад» внутри анализа.

В `0.3.0/0.3.1` изменились четыре контракта:

1. **Монополия `/start`.** Рама стала единственным владельцем
   `Command("start")`. Кузов передаёт лендинг через `render_start_callback`.
2. **Fail-fast конфликт.** Если `domain_router` всё ещё содержит обработчик
   `/start`, `create_complete_chassis` завершает сборку с `ValueError`.
3. **Единое синее меню.** Канон команды: `/start` сверху, доменные команды в
   переданном порядке посередине, `/menu` снизу.
4. **Навигационный канон.** «Отмена» закрывает корневой доменный раздел и
   возвращает стартовую карточку; «Назад» возвращает на один уровень внутри
   анализа.

Следовательно, смена зависимости без миграции может остановить процесс уже при
сборке фабрики либо создать два конкурирующих пользовательских пути.

Release `1.0.0` сохраняет эти четыре границы и добавляет только обратно
совместимые возможности: `single_message_start=False` по умолчанию,
`chassis.screens.retire_active_screen(...)`, безопасный backup файловой SQLite
при `backup_policy=None` и новую админку. Для первого переключения Profiling
оставляет single-message режим выключенным, явно решает политику backup и
гасит экран рамы перед открытием доменного сценария.

### 2.3. Инвариант hold

До завершения раздела 9:

- tag `profiling` остаётся на `6823f30`;
- документация рамы может развиваться, но checkout Profiling не двигается;
- исправления интеграции выполняются в репозитории кузова отдельной веткой;
- новая точка фиксации выбирается только после тестов и решения владельца.

---

## 3. Фабрика и порядок маршрутизации

Целевой монтаж выполняется через `create_complete_chassis`.

Порядок обработки aiogram:

1. **Admin Router** рамы.
2. **Payments Router** рамы.
3. **Localization Router** рамы.
4. **Profiling Domain Router** — `/detect`, ввод источника и callbacks анализа.
5. **Start Router** рамы — единственный владелец `/start`.
6. **Button Chassis Router** — кабинет, Info, поддержка и навигация рамы.

### 3.1. Требования к domain router

- Router передаётся в фабрику через `domain_router` ровно один раз.
- Обработчика `Command("start")` в нём нет.
- `/detect` работает только в `ChatType.PRIVATE`.
- Текстовый catch-all активируется только в состоянии ввода Profiling; голый
  `F.text` перехватит команды и кнопки рамы.
- Callback-префиксы кузова отделены от `core_*` и `adm_*`, например
  `profiling:*`.
- Тяжёлый анализ не запускается прямо в обработчике без проверки WorkGate и
  защиты от повторного старта.

```python
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command

profiling_domain = Router(name="profiling_domain")


@profiling_domain.message(
    Command("detect"),
    F.chat.type == ChatType.PRIVATE,
)
async def detect_command(message):
    await profiling_ui.open_source_screen(message)


@profiling_domain.message(
    F.chat.type == ChatType.PRIVATE,
    AwaitingProfilingText(),
    F.text,
)
async def accept_profiling_text(message):
    await profiling_flow.accept_text(message)
```

Недопустимо:

```python
@profiling_domain.message(Command("start"))
async def body_start(message):
    ...  # В 1.0.0 фабрика отвергнет такой router.
```

---

## 4. Единый `/start` и лендинг Profiling

Telegram не позволяет совместить постоянную `ReplyKeyboardMarkup` и
`InlineKeyboardMarkup` в одном `SendMessage`. Поэтому старт состоит из двух
сообщений:

1. **Носитель рамы** — короткое сообщение с постоянным нижним меню.
2. **Стартовая карточка Profiling** — результат `render_start_callback` с
   описанием продукта и inline-действиями.

### 4.1. Контракт renderer

`render_start_callback(context)` получает:

| Поле | Значение |
|---|---|
| `context.message` | Входное private-сообщение `/start` либо событие возврата |
| `context.user_id` | Telegram ID пользователя |
| `context.bot` | Текущий `Bot` либо `None` |
| `context.locale` | Активная локаль рамы |

Предпочтительный результат — `ChassisScreen`: рама сама отправит и запомнит
карточку. Допустим уже отправленный `Message`, но тогда lifecycle и разметка
частично остаются ответственностью кузова.

```python
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from bot_chassis.localization import ChassisScreen


async def render_profiling_start(context) -> ChassisScreen:
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔍 Начать профайлинг",
                    callback_data="profiling:source",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Как это работает",
                    callback_data="profiling:about",
                )
            ],
        ]
    )
    return ChassisScreen(
        text=(
            "<b>Profiling Framework</b>\n\n"
            "Анализ автора Telegram-канала или загруженного текста."
        ),
        markup=markup,
    )
```

Renderer не должен отправлять второй носитель Reply-клавиатуры. Нормальный
`/start` после миграции — ровно один носитель рамы и одна карточка Profiling.

### 4.2. Возврат на старт

`core_nav:cancel` повторно вызывает тот же `render_start_callback`, но не
создаёт новый носитель Reply-клавиатуры. Отдельный «домашний» renderer внутри
Profiling не нужен.

---

## 5. Нижнее и синее меню

### 5.1. Доменный ряд Reply Keyboard

Profiling передаёт фабрике один доменный ряд:

```python
domain_rows = (("🔍 Профайлинг канала",),)
```

Рама размещает его над служебным рядом Кабинета, Info и Поддержки. Тот же ряд
используется при перерисовке клавиатуры после смены языка.

Обработчик подписи должен быть private и вести в тот же корневой экран, что
`/detect`:

```python
@profiling_domain.message(
    F.chat.type == ChatType.PRIVATE,
    F.text == "🔍 Профайлинг канала",
)
async def profiling_button(message):
    await profiling_ui.open_source_screen(message)
```

### 5.2. Доменная команда `/detect`

В `1.0.0` фабрика `create_complete_chassis` не имеет аргумента
`domain_commands`. Команды передаются в startup-hook системного меню — это
часть общего контура сборки, но отдельный публичный API:

```python
from aiogram.types import BotCommand
from bot_chassis.commands import register_button_chassis_startup

profiling_commands = (
    BotCommand(command="detect", description="Запустить профайлинг"),
)

register_button_chassis_startup(
    chassis.dp,
    bot,
    custom_commands=profiling_commands,
)
```

Итоговый порядок синего меню:

| Позиция | Команда | Владелец |
|---|---|---|
| 1 | `/start` | Рама |
| 2 | `/detect` | Profiling |
| 3 | `/menu` | Рама |

`start`, `menu`, `help`, `support` зарезервированы. Если кузов передаст их в
`custom_commands`, рама отфильтрует дубли. Повторные доменные команды также
удаляются с сохранением первого вхождения.

---

## 6. Навигация анализа: «Отмена» и «Назад»

| Элемент | Где используется | Результат |
|---|---|---|
| **Отмена** | Корневой экран раздела Profiling | Выход из раздела на стартовую карточку через `core_nav:cancel` |
| **Назад** | Вложенный экран: выбор источника, загрузка, preview, параметры отчёта | Возврат ровно к родительскому экрану Profiling |
| **Отменить анализ** | Уже запущенная тяжёлая задача, если кузов это поддерживает | Доменная операция с отдельным callback, не `core_nav:cancel` |

Корневой экран:

```python
from bot_chassis import append_cancel_row

markup = append_cancel_row(source_type_markup)
```

Вложенный экран:

```python
from bot_chassis import append_back_row

markup = append_back_row(
    upload_markup,
    callback_data="profiling:back:source",
)
```

Правила:

- «Отмена» не ставится на каждом подэкране; иначе пользователь теряет
  пошаговую навигацию.
- «Назад» не должен вести на `/start`; он возвращает в конкретного родителя.
- Нельзя использовать `core_nav:cancel` для отмены фоновой задачи: возврат UI
  сам по себе не гарантирует остановку вычисления.
- Callback «Отменить анализ» должен быть идемпотентным и принадлежать Profiling.
- При возврате не создаётся второй носитель Reply-клавиатуры.

---

## 7. WorkGate перед тяжёлым анализом

Рама возвращает порт как `chassis.work_gate`, но не вызывает его за кузов.
Profiling обязан проверять допуск перед:

- скачиванием истории канала;
- разбором большого TXT;
- постановкой NLP/LLM-задачи в очередь;
- повторным запуском или регенерацией инфографики, если это платная работа.

```python
async def check_work_gate(message, chassis) -> bool:
    user = message.from_user
    if user is None:
        return False

    allowed, reason = await chassis.work_gate.can_accept_work(
        chassis.config.bot_id,
        user.id,
    )
    if allowed:
        return True
    if reason:
        await message.answer(reason)
    # reason is None означает теневой бан: сохраняем тишину.
    return False
```

Матрица:

| Состояние | `allowed` | `reason` | Поведение Profiling |
|---|---:|---|---|
| Работа разрешена | `True` | `None` | Продолжить |
| Maintenance | `False` | Текст причины/заглушка | Показать причину, не запускать задачу |
| Обычный бан | `False` | Причина бана/заглушка | Показать причину, не запускать задачу |
| Теневой бан | `False` | `None` | Молча завершить обработчик |

WorkGate не является проверкой оплаты. Сначала проверяется возможность работы,
затем — право на выбранный тип отчёта.

---

## 8. Права доступа и талоны подробного отчёта

### 8.1. Разделение портов

| Порт | Вопрос |
|---|---|
| `chassis.access.has_active_access(...)` | Есть ли у пользователя активное право по плану? |
| `chassis.vouchers.get_active_vouchers(...)` | Есть ли неиспользованный талон нужного SKU? |
| `chassis.vouchers.redeem_voucher(...)` | Удалось ли атомарно погасить выбранный талон? |

Profiling фиксирует одну продуктовую политику. Например:

- краткий preview бесплатен;
- полный психографический отчёт доступен по подписке `profiling_full` **или**
  за один талон SKU `profiling_report`;
- инфографика входит в тот же оплаченный job и не списывает второй талон при
  повторной доставке готового результата.

### 8.2. Каноническая последовательность

1. Проверить WorkGate.
2. Провалидировать источник и убедиться, что материала достаточно для анализа.
3. Проверить активный доступ.
4. Если доступа нет — получить активные талоны нужного SKU.
5. Перед постановкой **нового** платного job атомарно погасить один талон.
6. Сохранить доменный job с `voucher_id`/идемпотентным ключом.
7. Запустить анализ; повторная доставка того же job не списывает новый талон.

```python
REPORT_PLAN = "profiling_full"
REPORT_SKU = "profiling_report"


async def authorize_full_report(chassis, user_id: int):
    bot_id = chassis.config.bot_id

    if await chassis.access.has_active_access(
        bot_id,
        user_id,
        plan_code=REPORT_PLAN,
    ):
        return True, None

    vouchers = await chassis.vouchers.get_active_vouchers(
        bot_id,
        user_id,
        sku_code=REPORT_SKU,
    )
    if not vouchers:
        return False, "Для подробного отчёта нужен доступ или талон."

    voucher = vouchers[0]
    redeemed, error = await chassis.vouchers.redeem_voucher(
        bot_id,
        user_id,
        voucher.voucher_id,
    )
    if not redeemed:
        return False, error or "Талон уже использован. Обновите экран."

    return True, voucher.voucher_id
```

`get_active_vouchers` — это чтение, а не резерв. Источником истины является
результат `redeem_voucher`: два параллельных запуска могут увидеть один талон,
но успешно погасить его должен только один.

### 8.3. Ошибка после списания

Публичный `VoucherManagerPort` не предоставляет автоматический refund талона.
Поэтому кузов обязан:

- не списывать талон до валидации входа;
- хранить оплаченный job и уметь безопасно повторить его без второго списания;
- различать повторную доставку результата и новый анализ;
- иметь явную операционную политику компенсации при невосстановимом сбое
  (например, повтор job или ручная выдача нового талона администратором).

Не списывать талон после долгого вычисления: это создаёт бесплатную тяжёлую
работу при конкурентном проигрыше `redeem_voucher`.

---

## 9. Дорожная карта: разморозка `0.2.1 → 1.0.0`

Каждый шаг выполняется и проверяется в репозитории Profiling. Рама и tag
`profiling` до приёмки не меняются.

### Шаг 0. Зафиксировать исходную точку

- Записать текущий consumer SHA и версию зависимости.
- Подтвердить, что `profiling` указывает на `6823f30`.
- Снять baseline тестов и пользовательских путей `/start`, `/detect`, загрузки
  TXT, ссылки на канал и платного отчёта.
- Создать отдельную ветку миграции в репозитории кузова.

### Шаг 1. Передать `/start` раме

1. Удалить из domain router обработчик `Command("start")`.
2. Перенести построение лендинга в `render_start_callback(context)`.
3. Предпочтительно возвращать `ChassisScreen`.
4. Не отправлять из callback Reply-клавиатуру и дополнительное приветствие.
5. Передать callback в `create_complete_chassis`.
6. Проверить прямой `/start`, повторный `/start` и `core_nav:cancel`.

Критерий шага: фабрика собирается без `ValueError`; старт даёт один носитель
меню и одну карточку Profiling.

### Шаг 2. Зарегистрировать `/detect` и меню

1. Оставить обработчик `/detect` в domain router с Private Chat-фильтром.
2. Передать `BotCommand("detect", ...)` в
   `register_button_chassis_startup(..., custom_commands=...)`.
3. Передать `domain_rows=(("🔍 Профайлинг канала",),)` в фабрику.
4. Направить кнопку и `/detect` в один корневой сценарий.
5. Проверить результат `set_my_commands`: `start → detect → menu`.

Критерий шага: нет второго владельца `/start`/`menu`, `/detect` виден в синем
меню и открывает тот же экран, что доменная Reply-кнопка.

### Шаг 3. Проверить WorkGate, права и талоны

1. Поставить `can_accept_work` перед каждым тяжёлым entry point.
2. Проверить maintenance, обычный и теневой бан.
3. Зафиксировать SKU и plan code полного отчёта.
4. Проверить путь активной подписки без списания талона.
5. Проверить путь одного талона и атомарное погашение.
6. Проверить два конкурентных запуска с одним талоном.
7. Проверить повтор job/доставки после сбоя без второго списания.

Критерий шага: тяжёлая работа не начинается без допуска, а один оплаченный
job расходует не более одного талона.

### Шаг 4. Принять миграцию и снять hold

1. Прогнать узкие contract-тесты монтажа.
2. Прогнать полный тестовый набор Profiling.
3. Выполнить разрешённый владельцем smoke: `/start`, `/detect`, канал, TXT,
   сырой текст, платный отчёт, инфографика, навигация и рестарт процесса.
4. Зафиксировать проверенный tag рамы `v1.0.0` у потребителя.
5. Обновить control plane Profiling: статус, совместимую версию и результаты.
6. Только после решения владельца снять HOLD/изменить привязку `profiling`.

Критерий шага: тесты и smoke зелёные, откат описан, владелец явно подтвердил
новую точку. Самостоятельно двигать существующий tag запрещено.

---

## 10. Канонический монтаж `1.0.0`

Имена `ProfilingHandlers` и доменных сервисов ниже обозначают адаптеры кузова,
а не классы пакета `bot_chassis`.

```python
from aiogram import Bot, Dispatcher, Router
from aiogram.types import BotCommand

from bot_chassis.commands import register_button_chassis_startup
from bot_chassis.config import BotChassisConfig, SkuItem
from bot_chassis.factory import create_complete_chassis
from bot_chassis.user_lifecycle import CANON_ALLOWED_UPDATES


async def build_profiling(bot: Bot):
    dp = Dispatcher()
    domain = Router(name="profiling_domain")
    handlers = ProfilingHandlers(profiling_service)

    # Регистрация точных private handlers без Command("start").
    handlers.register(domain)

    config = BotChassisConfig(
        bot_id="profiling",
        db_path="profiling_chassis.db",
        superadmin_ids=(123456789,),
        support_chat_id=-1001234567890,
        audit_chat_id=-1001234567891,
        skus=(
            SkuItem(
                sku_code="profiling_report",
                title="Подробный профайлинг",
                description="Один полный отчёт с инфографикой",
                stars_price=250,
            ),
        ),
    )

    chassis = await create_complete_chassis(
        bot,
        config,
        dp=dp,
        domain_router=domain,
        domain_rows=(("🔍 Профайлинг канала",),),
        project_label="Profiling Framework",
        render_start_callback=render_profiling_start,
        allowed_updates=CANON_ALLOWED_UPDATES,
    )

    # Порты появляются после сборки фабрики и привязываются до polling.
    handlers.bind_ports(
        bot_id=chassis.config.bot_id,
        work_gate=chassis.work_gate,
        access=chassis.access,
        vouchers=chassis.vouchers,
    )

    register_button_chassis_startup(
        chassis.dp,
        bot,
        custom_commands=(
            BotCommand(command="detect", description="Запустить профайлинг"),
        ),
    )
    return chassis


async def run(bot: Bot) -> None:
    chassis = await build_profiling(bot)
    await chassis.dp.start_polling(
        bot,
        allowed_updates=list(CANON_ALLOWED_UPDATES),
    )
```

Production-конфигурация, цены и ID берутся из settings/env кузова. Значения из
примера — иллюстрация контракта, не готовый production-конфиг.

---

## 11. Чек-лист проверки стыковки

### 11.1. Hold и зависимость

- [ ] До приёмки tag `profiling` по-прежнему указывает на `6823f30`.
- [ ] Миграция ведётся в отдельной ветке репозитория Profiling.
- [ ] Рама не получила код NLP, загрузки каналов или рендера инфографики.
- [ ] Версия/commit рамы у потребителя закреплены явно, не плавающей веткой.

### 11.2. `/start` и фабрика

- [ ] В domain router нет `Command("start")`.
- [ ] `create_complete_chassis` не выбрасывает `ValueError`.
- [ ] Передан `render_start_callback`.
- [ ] Callback возвращает `ChassisScreen` либо уже отправленный `Message`.
- [ ] `/start` отправляет ровно один носитель Reply Keyboard и одну карточку.
- [ ] Повторный `/start` закрывает/обезвреживает прежнюю карточку по lifecycle рамы.
- [ ] `core_nav:cancel` возвращает карточку без второго носителя клавиатуры.

### 11.3. Меню и маршруты

- [ ] `domain_rows` содержит ровно `(("🔍 Профайлинг канала",),)`.
- [ ] `/detect` и доменная кнопка открывают один корневой сценарий.
- [ ] `/detect` ограничен `ChatType.PRIVATE`.
- [ ] Нет безусловного private `F.text`, поглощающего меню рамы.
- [ ] `set_my_commands` получает порядок `/start`, `/detect`, `/menu`.
- [ ] `/start` и `/menu` не дублируются в `custom_commands`.

### 11.4. Навигация

- [ ] Корневой экран Profiling использует «Отмена».
- [ ] Вложенные экраны используют «Назад» с конкретным parent callback.
- [ ] «Назад» не выбрасывает пользователя на `/start`.
- [ ] `core_nav:cancel` не используется как отмена фонового job.
- [ ] Доменная отмена job идемпотентна и не влияет на чужие задачи.

### 11.5. WorkGate

- [ ] Gate вызывается до скачивания канала, NLP/LLM и постановки тяжёлого job.
- [ ] Maintenance показывает безопасную причину и не запускает работу.
- [ ] Обычный бан показывает причину и не запускает работу.
- [ ] Теневой бан (`reason is None`) сохраняет тишину.
- [ ] Повторный entry point также проверяет gate.

### 11.6. Права и талоны

- [ ] Зафиксированы `profiling_full` и `profiling_report` либо их принятые аналоги.
- [ ] Активная подписка не расходует талон.
- [ ] Бесплатный preview не расходует талон.
- [ ] Невалидная ссылка/пустой TXT не расходуют талон.
- [ ] Полный отчёт без подписки расходует ровно один талон.
- [ ] Два параллельных запуска не могут успешно списать один талон дважды.
- [ ] Повторная доставка готовой инфографики не списывает талон.
- [ ] Ошибка после списания восстанавливается повтором того же job либо принятой
  компенсационной процедурой.

### 11.7. Источники и результат

- [ ] Валидная ссылка на доступный Telegram-канал проходит полный путь.
- [ ] Недоступный/закрытый канал даёт доменную ошибку без списания.
- [ ] TXT проверяется по размеру, кодировке и наличию содержимого.
- [ ] Вставленный текст проходит тот же нормализатор, что TXT.
- [ ] Отчёт связан с исходным job и пользователем.
- [ ] Инфографика доставляется один раз либо повторно без повторного анализа/оплаты.
- [ ] В служебные сообщения не попадают сырой текст, токены и traceback.

### 11.8. Тесты и приёмка

- [ ] Есть contract-тест запрета второго `/start`.
- [ ] Есть тест двухсоставного стартового экрана.
- [ ] Есть тест порядка `start → detect → menu`.
- [ ] Есть тесты «Отмена» и «Назад».
- [ ] Есть тест матрицы WorkGate.
- [ ] Есть конкурентный тест списания одного талона.
- [ ] Полный набор тестов Profiling проходит.
- [ ] Smoke выполнен только после отдельного разрешения владельца.
- [ ] Control plane обновлён после фактической приёмки, не заранее.

---

## 12. Критерии снятия HOLD

HOLD можно считать снятым только при одновременном выполнении условий:

1. Рама — единственный владелец `/start`, а лендинг Profiling подключён через
   `render_start_callback`.
2. Синее меню имеет порядок `/start → /detect → /menu`.
3. Доменная кнопка, `/detect`, «Отмена» и «Назад» образуют один непротиворечивый
   пользовательский маршрут.
4. WorkGate вызывается перед тяжёлыми задачами; права и талоны проверены, включая
   конкурентный запуск.
5. Полный набор тестов и разрешённый smoke Profiling прошли.
6. В control plane записаны проверенный SHA, результаты и способ отката.
7. Владелец отдельно подтвердил снятие hold и новую точку фиксации.

До выполнения всех семи условий `profiling = 6823f30` остаётся действующей
точкой совместимости. Этот документ сам по себе tag не перемещает.
