# Bot Chassis 0.3.1 — пакет UI, навигации и поддержки

**Статус:** принят владельцем 2026-10-01.
**Источник требований:** `docs/CHASSIS_SUPPORT_AND_UI_SPEC.md`.
**Этот файл — единственный технический контракт релиза `0.3.1`.**
Очередь и статусы Gate — `.agents/TASK_TODO.md`. Второй спецификации не заводить.

Базовая ветка: `feat/chassis-0.3`. Фактический HEAD на момент написания —
`d3c79cd`. Предыдущий релиз на ветке — `0.3.0` (тег не ставился).

---

## 0. Как этим планом пользоваться

Исполнитель делает **ровно один Gate за раз**, по порядку, и останавливается.
Следующий Gate не начинать без отдельной команды владельца.

Для каждого Gate ниже указаны:

- **Файлы** — полный список того, что разрешено трогать. Файл не из списка не
  менять.
- **Делать** — пронумерованные операции. Выполнить все, ни одну не пропустить.
- **Запрещено** — то, что исполнитель может «додумать». Не делать.
- **Проверка** — конкретные команды и ожидаемый результат.

Если хоть один пункт непонятен, если фактический код расходится с описанием,
или если проверка не сходится — **остановиться и написать владельцу**.
Не «исправлять по смыслу», не делать соседние улучшения, не рефакторить.

### Сквозные правила пакета

1. Старые подписи кнопок остаются в алиасах распознавания **навсегда**. Это не
   «старая ветка», а обязательная совместимость: у пользователя, который не
   нажимал `/start` после обновления, на экране физически висит старая
   Reply-клавиатура со старым текстом. Если убрать алиас, его кнопки умрут.
2. Старые `callback_data` остаются принимаемыми, но **только как дополнительный
   вход в уже существующий обработчик**. Второй обработчик с дублирующей
   логикой заводить запрещено.
3. Мёртвый код удаляется в том же Gate, который сделал его мёртвым. Параметр,
   который больше никто не читает, не остаётся в сигнатуре «на всякий случай».
4. Ни одной новой строки с русским или эмодзи в SQLite. В БД только ASCII-коды
   состояний. Это решение Gate 3, оно в силе.
5. Домен кузова в раму не класть.

---

## Gate C0. Коррекция control plane

Чисто документационный Gate. Код не трогать.

**Предусловие.** C0 — только документы. Код `0.3.1` не начинается. Чужой
хвост в рабочем дереве не смешивать с этим Gate.

1. Три файла `src/bot_chassis/admin/audit.py`,
   `src/bot_chassis/middleware/error_monitor.py`,
   `src/bot_chassis/payments/router.py` могут висеть в `git status` **без
   содержимого** (совпадает hash с HEAD). Сначала `git diff` по каждому.
   Если diff пустой — `git restore` этих трёх файлов. Отдельный «коммит
   коррекции 0.3.0» по ним **не** заводить: менять нечего.
   Если diff непустой — остановиться и спросить владельца. C0 эти файлы не
   принимает.
2. Документационный хвост полного аудита `0.3.0` (`AUDIT_0_3_PROMPT.md`,
   `AUDIT_LOG_0_3.md`, `AUDIT_0_3_FULL_PROMPT.md`) входит в C0 как документы.
   Иначе проверка «status только из списка C0» не сойдётся.
3. `BASE_REF` — текущий кодовый HEAD **до** коммита C0 (на момент написания
   плана это `d3c79cd`). Это не SHA будущего документационного коммита.

**Причина.** В ветке лежат четыре коммита (`20db9e1`, `d0b170f`, `5baf6c1`,
`d3c79cd`), которых нет ни в одном журнале. `SESSION_STATE.md`, `NEW_CHAT.md` и
`VERSION_LOG.md` утверждают, что HEAD = `9c9418f`. Запланированный
`FULL-0.3-RELEASE` нацелен на устаревший SHA.

**Файлы:** `.agents/PROJECT_LOG.md`, `.agents/SESSION_STATE.md`,
`.agents/NEW_CHAT.md`, `.agents/AGENTS.md`, `.agents/TASK_TODO.md`,
`.agents/ACTIVE_PLANS.md`,
`.agents/AUDIT_0_3_PROMPT.md`, `.agents/AUDIT_LOG_0_3.md`,
`.agents/AUDIT_0_3_FULL_PROMPT.md`, `.agents/UPGRADE_0_3_1_PLAN.md`,
`.agents/AUDIT_0_3_1_PROMPT.md`, `docs/CHASSIS_SUPPORT_AND_UI_SPEC.md`,
`VERSION_LOG.md`.

**Делать:**

1. В `PROJECT_LOG.md` добавить запись за 2026-10-01 по канону журнала: дата,
   почему, коммиты `20db9e1..d3c79cd`, затронутые файлы
   (`src/bot_chassis/keyboards.py`, `src/bot_chassis/router.py`,
   `tests/test_factory.py`, `tests/test_gate5a_support.py`), что проверялось,
   чего не трогали. Отдельной строкой записать, что решение `d0b170f` (убрать
   «Назад» с формы тикета) отменено принятым каноном навигации Gate U2.
   Ещё одной отдельной строкой зафиксировать решение владельца: `Отмена`
   повторно рисует только стартовую карточку через `render_start_callback`, но
   не шлёт второй носитель Reply Keyboard; полный `/start` не повторяется.
2. В `SESSION_STATE.md` и `NEW_CHAT.md` заменить устаревший HEAD `9c9418f` на
   явно названный `BASE_REF` — последний кодовый SHA перед C0. Landing кода
   `0.3.0` остаётся `7fe5d93`. Не называть SHA документационного коммита C0
   «фактическим HEAD»: самоссылочный SHA внутри собственного коммита
   невозможен.
3. В `VERSION_LOG.md` в строке `Branch` указать `Base for 0.3.1: BASE_REF`.
4. В `TASK_TODO.md` **не переписывать очередь заново**, если она уже содержит
   Gate C0–R1, B7 и handoff в PsyBot. Сверить с этим планом. Дописать только
   расхождения: `BASE_REF`, предусловие C0, объединение `FULL-0.3-RELEASE` с
   B7. Дублирующие блоки очереди не создавать.
5. В `ACTIVE_PLANS.md` добавить трек `A7. Bot Chassis 0.3.1` со ссылкой на этот
   файл, если его ещё нет.
6. Зафиксировать решение: пункт 5 спецификации (вычистка `Language / Язык` в
   PsyBot) **в этот репозиторий не входит**. Он живёт в
   `C:\Python\tg_psy_tests`, и правила запрещают менять его из этого корня.
   В `TASK_TODO.md` это уже отдельная строка handoff — не дублировать.
7. В `AGENTS.md` и `NEW_CHAT.md` синхронно снять три противоречия bootstrap,
   не ослабляя остальные правила:
   - для Gate `0.3.1` единственный технический источник —
     `.agents/UPGRADE_0_3_1_PLAN.md`; старый план остаётся источником только
     для `0.3`;
   - Gate U1 вправе заменить в `tests/test_chassis.py` ровно одну строку 104
     (литерал `"ℹ️ Info/FAQ"` → `BTN_INFO_RU`), число тестов остаётся 19;
   - Gate U2 вправе удалить только `cancel_callback` / `cancel_label` из
     `build_support_prompt_keyboard`, с обязательной записью breaking change в
     `CHANGELOG.md` и чек-листе миграции. Другие сигнатуры не ломать.
8. Добавить в Git этот план, `.agents/AUDIT_0_3_1_PROMPT.md`,
   `.agents/AUDIT_0_3_FULL_PROMPT.md` и `docs/CHASSIS_SUPPORT_AND_UI_SPEC.md`.
   Содержимое плана и аудит-промпта `0.3.1` в C0 **не редактировать** — только
   `git add`. Правки контракта — отдельная команда владельца, не этот Gate.

**Запрещено:** менять код; править содержимое
`.agents/UPGRADE_0_3_1_PLAN.md` и `.agents/AUDIT_0_3_1_PROMPT.md`; ставить
теги; пушить; заводить фантомный коммит по трём py-файлам с пустым diff.

**Проверка:** три py-файла из предусловия не в `git status`; `git diff --check`
чистый; `git status --short` не содержит изменений вне перечисленных файлов;
после коммита `git diff --name-only BASE_REF` совпадает со списком C0.
SHA `BASE_REF` существует и однозначно обозначен в журналах.

---

## Gate U1. Подписи основной клавиатуры

**Цель.** RU: `[👤 Аккаунт] [ℹ️ Инфо/FAQ] [Поддержка]`.
EN не меняется: `[👤 Account] [ℹ️ Info/FAQ] [💬 Support]`.

**Файлы:** `src/bot_chassis/contracts.py`, `src/bot_chassis/router.py`,
`src/bot_chassis/keyboards.py`, `src/bot_chassis/ports/cabinet.py`,
`tests/test_chassis.py` (ровно одна строка, см. п. 5),
`tests/test_gate1_menu_contract.py`, `docs/CHASSIS.md`.

**Делать:**

1. В `contracts.py` изменить три значения, и только их:
   - `BTN_CABINET_RU = "👤 Аккаунт"`
   - `BTN_INFO_RU = "ℹ️ Инфо/FAQ"`
   - `BTN_SUPPORT_RU = "Поддержка"`
   `BTN_CABINET_EN`, `BTN_INFO_EN`, `BTN_SUPPORT_EN` не трогать.
   Слэш в `Инфо/FAQ` без пробелов. У `Поддержка` эмодзи нет вообще.
2. В `contracts.py` дописать в алиасы старые строки **литералами**, потому что
   константы, через которые они раньше попадали в наборы, сменили значение:
   - в `LEGACY_BTN_CABINET_ALIASES` добавить `"👤 Личный кабинет"`;
   - в `LEGACY_BTN_INFO_ALIASES` добавить `"ℹ️ Info/FAQ"` и `"Инфо/FAQ"`;
   - в `LEGACY_BTN_SUPPORT_ALIASES` добавить `"💬 Поддержка"`.
   Проверить глазами, что после правки в каждом из трёх наборов присутствуют и
   новая, и старая подпись.
3. В `router.py` удалить три локальных хардкод-набора и заменить их на общие
   из `contracts.py`. Это обязательная часть Gate, а не уборка «заодно»:
   - строка ~180: `cabinet_aliases = {BTN_CABINET_RU, BTN_CABINET_EN,
     "Личный кабинет", ...}` → `cabinet_aliases = set(LEGACY_BTN_CABINET_ALIASES)`;
   - строка ~296: `support_aliases = {BTN_SUPPORT_RU, ...}` →
     `support_aliases = set(LEGACY_BTN_SUPPORT_ALIASES)`;
   - `info_aliases` уже берётся из `LEGACY_BTN_INFO_ALIASES` — оставить как есть.
   После этого убрать из блока `from .contracts import (...)` в `router.py` те
   имена, которые перестали использоваться (`BTN_CABINET_RU`, `BTN_CABINET_EN`,
   `BTN_SUPPORT_RU`, `BTN_SUPPORT_EN`), и добавить
   `LEGACY_BTN_CABINET_ALIASES`, `LEGACY_BTN_SUPPORT_ALIASES`. Мёртвых импортов
   не оставлять.
4. Заменить устаревшие подписи в текстах и докстрингах:
   - `keyboards.py`, докстринг `build_main_menu_keyboard`: пример раскладки на
     `[👤 Аккаунт] [ℹ️ Инфо/FAQ] [Поддержка]`;
   - `router.py`, нейтральная карточка кабинета (~строка 207):
     `👤 <b>Личный кабинет</b>` → `👤 <b>Аккаунт</b>`;
   - `ports/cabinet.py`, `build_cabinet_renderer` (~строка 96):
     `"👤 <b>Личный кабинет</b>"` → `"👤 <b>Аккаунт</b>"`;
   - `router.py`, комментарии-заголовки секций 2 и 4 — привести к новым
     подписям.
5. **Разрешённое владельцем исключение в замороженном файле.**
   `tests/test_chassis.py`, строка 104 содержит литерал `"ℹ️ Info/FAQ"`:
   ```python
   [BTN_CABINET_RU, "ℹ️ Info/FAQ", BTN_SUPPORT_RU],
   ```
   Заменить литерал на константу:
   ```python
   [BTN_CABINET_RU, BTN_INFO_RU, BTN_SUPPORT_RU],
   ```
   Это **единственная** разрешённая правка в `tests/test_chassis.py` во всём
   пакете `0.3.1`. Число тестов (19) не меняется, другие строки не трогать,
   импорты файла не трогать. Исключение фиксируется в `PROJECT_LOG.md` в
   Gate R1.
6. В `tests/test_gate1_menu_contract.py` добавить один новый тест
   `test_ru_labels_0_3_1_and_legacy_aliases`:
   - `build_main_menu_keyboard(locale="ru")` даёт ровно один ряд
     `["👤 Аккаунт", "ℹ️ Инфо/FAQ", "Поддержка"]`;
   - `build_main_menu_keyboard(locale="en")` даёт
     `["👤 Account", "ℹ️ Info/FAQ", "💬 Support"]`;
   - `is_main_menu_button("👤 Личный кабинет")`, `is_main_menu_button("💬 Поддержка")`
     и `is_main_menu_button("ℹ️ Info/FAQ")` возвращают `True`;
   - в `BTN_SUPPORT_RU` нет ни одного символа из диапазона эмодзи (достаточно
     `assertEqual(BTN_SUPPORT_RU, "Поддержка")`).
7. В `docs/CHASSIS.md` обновить таблицу/описание подписей служебной тройки и
   добавить абзац: старые подписи остаются распознаваемыми алиасами, кузову
   ничего делать не нужно.

**Запрещено:** менять EN-подписи; менять `callback_data`; удалять любой алиас;
трогать `tests/test_chassis.py` где-либо кроме строки 104; менять число тестов
в `tests/test_chassis.py`.

**Проверка:**

```powershell
python -m pytest tests/test_chassis.py -q          # 19 passed
python -m pytest tests/test_gate1_menu_contract.py tests/test_gate1a_locale.py -q
python -m pytest tests -q
python -m compileall -q src/bot_chassis
git diff --check
```

Ожидание: `tests/test_chassis.py` — ровно 19 passed; полный сьют зелёный и
больше прежнего ровно на 1 тест.

---

## Gate U2. Канон навигации «Отмена» vs «Назад»

**Цель.** Корень раздела → нижняя кнопка `Отмена`, закрывает экран и
перерисовывает стартовый экран. Вложенный подэкран → нижняя кнопка `Назад`,
возвращает на один уровень вверх. Канон держит рама, кузов навигацию не пишет.

**Отменяемое решение.** Коммит `d0b170f` убрал «Назад» с формы тикета. Это
решение отменено владельцем 2026-10-01. Два теста, которые он перевернул
(`tests/test_factory.py` и `tests/test_gate5a_support.py`,
`assertNotIn("core_sup:hub", ...)`), в этом Gate возвращаются к `assertIn`.

**Файлы:** `src/bot_chassis/contracts.py`, `src/bot_chassis/keyboards.py`,
`src/bot_chassis/router.py`, `src/bot_chassis/factory.py`,
`src/bot_chassis/ports/cabinet.py`, `src/bot_chassis/__init__.py`,
`tests/test_factory.py`, `tests/test_gate5a_support.py`,
`tests/test_gate1_menu_contract.py`, `tests/test_gate1a_locale.py`,
`tests/test_gate12_release.py`, `docs/CHASSIS.md`.

`test_gate1a_locale.py` и `test_gate12_release.py` трогать **только если**
после выноса доставки стартовой карточки сломались их ассерты. Менять логику
этих тестов запрещено: подправить ожидания под card-only `Отмена`, если они
проверяют лишний носитель клавиатуры.

**Делать:**

1. `contracts.py`: добавить канонический идентификатор отмены
   ```python
   CB_NAV_CANCEL: str = f"{CALLBACK_PREFIX_NAV}cancel"
   LABEL_CANCEL_RU: str = "Отмена"
   LABEL_CANCEL_EN: str = "Cancel"
   LABEL_BACK_RU: str = "Назад"
   LABEL_BACK_EN: str = "Back"
   ```
   `CB_SUPPORT_BACK` и `CB_SUPPORT_CANCEL` **оставить объявленными** — они
   приедут с сообщений, отправленных до обновления. Рядом поставить
   комментарий: «совместимость, обрабатываются тем же хэндлером, что
   `CB_NAV_CANCEL` / `CB_SUPPORT_HUB`».
2. `keyboards.py`, `build_support_overview_keyboard` — корень Поддержки:
   нижний ряд `← Назад` / `core_sup:back` заменить на
   `InlineKeyboardButton(text=LABEL_CANCEL_RU, callback_data=CB_NAV_CANCEL)`.
   Также убрать эмодзи с двух инлайн-кнопок (требование §3.3 спецификации):
   `📝 Написать в поддержку` → `Написать в поддержку`,
   `💛 Поддержать проект` → `Поддержать проект`.
   Кнопку `⭐ Оставить отзыв` оставить как есть — спецификация её не трогает.
3. `keyboards.py`, `build_support_prompt_keyboard` — вложенный подэкран.
   После `d0b170f` параметры `back_callback` и `back_label` стали мёртвыми, а
   карточка временно использует `cancel_callback` / `cancel_label`. Новый канон
   возвращает этой функции единственный смысл «Назад»: прежние back-параметры
   снова становятся рабочими, временные cancel-параметры удаляются.
   Сигнатура:
   ```python
   def build_support_prompt_keyboard(
       back_callback: str = CB_SUPPORT_HUB,
       back_label: str = LABEL_BACK_RU,
       extra_rows: Sequence[Sequence[tuple[str, str]]] | None = None,
   ) -> InlineKeyboardMarkup:
   ```
   Нижний ряд — ровно одна кнопка `back_label` → `back_callback`.
   Параметры `cancel_callback` и `cancel_label` **удалить** из сигнатуры и из
   докстринга: после этой правки их никто не читает. Это ломающее изменение для
   прямых вызовов из кузовов — оно обязано попасть в `CHANGELOG.md` и в
   чек-лист миграции `docs/CHASSIS.md` в Gate R1.
4. `keyboards.py`, `build_donation_keyboard` — уже отдаёт `← Назад` на
   `CB_SUPPORT_HUB`. Заменить подпись на `LABEL_BACK_RU` (без стрелки), чтобы
   текст кнопки был строго «Назад». Callback не менять.
5. `keyboards.py`: добавить функцию дописывания канонического ряда отмены.
   Образец для подражания — `decorate_info_markup` в `localization.py`,
   которая так же дописывает один ряд и не плодит дубли:
   ```python
   def append_cancel_row(
       markup: InlineKeyboardMarkup | None,
       *,
       label: str = LABEL_CANCEL_RU,
       callback_data: str = CB_NAV_CANCEL,
   ) -> InlineKeyboardMarkup:
       """Канонический ряд «Отмена» внизу корневого экрана.

       Уже стоящий ряд с этим callback_data заменяется, а не дублируется.
       """
   ```
   Поведение: пройти по существующим рядам, удалить **только кнопки** с
   `callback_data == callback_data`, остальные кнопки и ряды сохранить в
   исходном порядке, пустые после удаления ряды убрать, добавить ряд отмены
   последним. Целый ряд с соседними полезными кнопками не выбрасывать.
   Рядом добавить общий помощник вложенного экрана:
   ```python
   def append_back_row(
       markup: InlineKeyboardMarkup | None,
       *,
       callback_data: str,
       label: str = LABEL_BACK_RU,
   ) -> InlineKeyboardMarkup:
   ```
   Он работает по тому же правилу без дублей и всегда ставит `Назад`
   последним рядом. Для кузовных FAQ/платёжных подэкранов передаётся callback
   родительского корня. Функция идемпотентна по `callback_data`: повторное
   применение с тем же callback заменяет прежнюю кнопку и не создаёт дубль.
   Клавиатуры рамы, которые сами уже строят канонический нижний ряд
   (`build_support_prompt_keyboard`, `build_donation_keyboard`), через helper
   не прогонять: их builder обязан сразу вернуть окончательную разметку, без
   второго этапа декорирования.
6. `router.py`: один обработчик закрытия/отмены на все совместимые
   идентификаторы, но без изменения старого смысла `CB_NAV_CLOSE`.
   - Расширить существующий `handle_nav_close` (`F.data == CB_NAV_CLOSE`) до
     `F.data.in_({CB_NAV_CLOSE, CB_NAV_CANCEL, CB_SUPPORT_BACK})`.
   - Внутри сначала сохранить значение `query.data`, затем
     `screens.forget_card(user_id)`, `await query.answer()` и удалить сообщение
     (при неудаче — снять markup).
   - Для старого `CB_NAV_CLOSE` на этом остановиться: публичная кнопка
     «Закрыть» сохраняет прежнее действие и не превращается скрыто в переход
     на старт.
   - Только для `CB_NAV_CANCEL` и `CB_SUPPORT_BACK`: выполнить
     `pending.clear(user_id)` и вызвать доставку **стартовой карточки**
     (п. 8). Reply Keyboard здесь не слать.
     Если `on_support_back` передан, сам факт успешного завершения
     `await on_support_back(...)` считается успехом. Его штатный return —
     `None`; трактовать `None` как ошибку и слать вторую карточку запрещено.
     Если `on_support_back` отсутствует (роутер собран напрямую без фабрики),
     отправить нейтральную fallback-карточку рамы. Внутренние случаи
     `render_start_callback is None` / неизвестный результат обрабатывает
     фабричный callback по п. 8, а не роутер.
   - Удалить отдельный обработчик `handle_support_back`
     (`F.data == CB_SUPPORT_BACK`) целиком: его логика теперь живёт в общем
     хэндлере. Двух обработчиков на одно действие быть не должно.
   - Обработчик `handle_support_cancel` (`F.data == CB_SUPPORT_CANCEL`)
     **удалить**, а `CB_SUPPORT_CANCEL` добавить в фильтр
     `handle_support_hub`: `F.data.in_({CB_SUPPORT_HUB, CB_SUPPORT_CANCEL})`.
     Старая кнопка «Отмена» с формы тикета теперь ведёт в корень Поддержки —
     это и есть новый канон «Назад».
   - Параметр `on_support_back` в сигнатуре `create_button_chassis_router`
     оставить без переименования: он уже обозначает ровно «перерисовать старт».
7. `router.py`: корневые экраны получают «Отмена» автоматически.
   - Завести внутри `create_button_chassis_router` одну общую функцию доставки
     корневого экрана, чтобы Кабинет и Info не расходились:
     ```python
     async def _deliver_root_screen(
         message: types.Message,
         user_id: int,
         screen: ChassisScreen,
         policy: CardClosePolicy,
         *,
         with_language: bool,
     ) -> None:
     ```
     Внутри: взять `screen.markup`; если `with_language and
     language_switch_enabled` — прогнать через `decorate_info_markup`; затем
     **всегда** прогнать через `append_cancel_row`; отправить; запомнить в
     `screens.remember_card`.
     Порядок обязателен: языковой ряд выше, «Отмена» последняя строка.
   - Переписать ветку `isinstance(sent, ChassisScreen)` в `_open_info` на вызов
     `_deliver_root_screen(..., with_language=True)`. Логика языка не меняется.
   - В `handle_cabinet` добавить такую же ветку: если
     `render_cabinet_callback` вернул `ChassisScreen` — звать
     `_deliver_root_screen(..., with_language=False)`.
   - Ветка «кузов вернул уже отправленный `Message`» больше не может быть
     дырой в гарантии. Взять `sent.reply_markup`, прогнать через
     `append_cancel_row` и вызвать `sent.edit_reply_markup`. Если Telegram не
     дал изменить markup, отправить рядом отдельную навигационную карточку с
     единственной кнопкой `Отмена`; одного warning недостаточно. Аналогично
     сохранить языковой ряд Info, если он включён.
   - Нейтральные карточки-заглушки самой рамы (кабинет без колбэка, Info без
     колбэка) тоже обязаны получить ряд «Отмена» — провести их через тот же
     `_deliver_root_screen`.
   - Аннотации `render_cabinet_callback` и `render_info_callback` в сигнатуре
     `create_button_chassis_router` обновить до фактического объединения
     `types.Message | ChassisScreen | None`.
8. `factory.py`: стартовая **карточка** после `Отмена` — та же функция, что
   рисует карточку на `/start`. Носитель Reply Keyboard — **нет**.
   Решение владельца 2026-10-01: каждая `Отмена` не повторяет полный `/start`.
   Клавиатура persistent, второй «Главное меню» в чат не слать.
   - Вынести доставку стартовой карточки из `_create_start_router` в одну
     внутреннюю async-функцию `_deliver_start_card(...)`.
   - `/start` по-прежнему: сначала носитель с Reply Keyboard, затем
     `_deliver_start_card`. Поведение `/start` для пользователя не менять.
   - `_on_support_back` и обработчик `Отмена` вызывают **только**
     `_deliver_start_card`. Параметр `reply_markup=` клавиатуры туда не
     передавать.
   - Если `render_start_callback is None`: языковой тумблер включён →
     `_DEFAULT_START_CARD_TEXT` с `decorate_info_markup`; выключен →
     `welcome_text` или `_MENU_TEXT` как текст карточки **без** Reply Keyboard.
     Молчаливый `return` при выключенном языке запрещён.
   - Если `render_start_callback` вернул `None` или неизвестный тип — тот же
     fallback карточки; молча завершаться запрещено.
   - `_on_support_back` сохраняет контракт `Awaitable[None]`: после успешной
     доставки ничего возвращать не требуется. Не вводить `bool` и не менять
     публичную сигнатуру порта.
   - Не вызывать callback дважды и не создавать второй `/start`-обработчик.
   - Роутер без фабрики не знает кузовной `render_start_callback`, поэтому при
     отсутствии `on_support_back` отправляет только нейтральную fallback-
     карточку рамы. Вторую копию кузовного renderer в `router.py` не заводить.
9. `ports/cabinet.py`, `build_cabinet_renderer`: изменить возвращаемое значение
   с отправленного `Message` на `ChassisScreen(text=text)`, чтобы дефолтный
   кабинет рамы шёл по новому пути и получал «Отмена». Аннотацию типа
   обновить. Это внутренний рендерер рамы, он собирается в `factory.py` и
   наружу не экспортируется.
10. `__init__.py`: добавить в импорт и в `__all__` `CB_NAV_CANCEL`,
    `append_cancel_row`, `append_back_row`, `LABEL_CANCEL_RU`,
    `LABEL_BACK_RU`. Это экспорт навигационного скелета для кузовов, которые
    собирают собственные корневые и вложенные экраны.
11. Тексты подсказок привести в соответствие:
    - `_request_text()` в `router.py`: `<i>Отмена или пункт меню сбрасывают
      ожидание.</i>` → `<i>Назад или пункт меню сбрасывают ожидание.</i>`;
    - текст экрана ответа в обращение (`handle_support_user_reply`):
      `Отмена сбрасывает ожидание` → `Назад сбрасывает ожидание`.
12. Тесты:
    - `tests/test_factory.py` и `tests/test_gate5a_support.py`: вернуть
      `assertNotIn("core_sup:hub", ...)` → `assertIn("core_sup:hub", ...)`;
      там, где проверялось наличие `core_sup:cancel` на форме тикета, заменить
      ожидание на `core_sup:hub` и на подпись кнопки `Назад`.
    - `tests/test_gate1_menu_contract.py`: новый тест
      `test_navigation_canon_cancel_and_back`:
      - корень Поддержки содержит кнопку с текстом ровно `Отмена` и
        `callback_data == "core_nav:cancel"`, и не содержит `core_sup:back`;
      - форма тикета содержит ровно одну нижнюю кнопку с текстом `Назад` и
        `callback_data == "core_sup:hub"`;
      - клик по `core_nav:cancel` приводит к вызову `render_start_callback`
        ровно один раз и **не** шлёт Reply Keyboard;
      - без `render_start_callback` и при выключенном языке клик по
        `core_nav:cancel` всё равно шлёт штатную стартовую карточку, без
        Reply Keyboard;
      - если стартовый callback вернул `None`, отдан штатный fallback карточки;
      - фабричный `on_support_back`, успешно отправивший карточку и вернувший
        штатный `None`, не вызывает второй fallback;
      - при полном отсутствии `on_support_back` роутер отправляет одну
        нейтральную fallback-карточку;
      - `/start` по-прежнему шлёт носитель с Reply Keyboard, затем карточку;
      - клик по старому `core_sup:back` даёт тот же результат (совместимость);
      - клик по старому `core_nav:close` только закрывает карточку и не
        вызывает стартовый renderer;
      - клик по старому `core_sup:cancel` открывает корень Поддержки;
      - корневой экран Info, собранный из `ChassisScreen`, содержит последним
        рядом `Отмена`, а языковой ряд — выше неё;
      - повторный прогон `append_cancel_row` по уже декорированному markup не
        создаёт второй кнопки «Отмена» и не удаляет соседнюю кнопку из того же
        ряда;
      - `append_back_row` ставит ровно один последний ряд `Назад`; форма
        отзыва и каталог донатов ведут в корень Поддержки.

**Запрещено:** вводить второй порт возврата на старт; добавлять «Отмена» на
сам стартовый экран; слать Reply Keyboard из обработчика `Отмена`; менять
значения `CB_SUPPORT_HUB`, `CB_SUPPORT_REQUEST`, `CB_SUPPORT_DONATE`,
`CB_SUPPORT_REVIEW`; оставлять параллельные обработчики одного действия;
менять смысл старого `CB_NAV_CLOSE`; оставлять корневой `Message` без
навигации только с warning; прогонять `append_back_row` по клавиатурам,
которые уже содержат «Назад»; трогать `tests/test_chassis.py`.

**Проверка:**

```powershell
python -m pytest tests/test_gate1_menu_contract.py tests/test_gate5a_support.py tests/test_factory.py -q
python -m pytest tests/test_chassis.py -q          # 19 passed, без правок
python -m pytest tests -q
python -m compileall -q src/bot_chassis
```

Дополнительно вручную подтвердить grep-ом, что в `src/` не осталось ни одного
обработчика `core_sup:back` и ни одного обработчика `core_sup:cancel` кроме
перечисленных в п. 6 фильтров.

---

## Gate U3. Системные команды синей кнопки «Меню»

**Цель.** Порядок строго: `/start` сверху, доменные команды кузова в середине,
`/menu` внизу.

**Решение владельца по языку:** один набор команд, подписи двуязычные в уже
принятом стиле рамы. Точные строки:

- `/start` — `Старт / Start`
- `/menu` — `Меню / Menu`

Регистрация через `language_code` **не** используется: он привязан к языку
Telegram-клиента, а не к переключателю RU/EN рамы, и создал бы второй
расходящийся источник языка.

**Файлы:** `src/bot_chassis/commands.py`, `tests/test_gate1_menu_contract.py`,
`docs/CHASSIS.md`.

**Делать:**

1. В `setup_bot_commands` собрать список в три этапа и ровно в таком порядке:
   ```python
   head = [BotCommand(command="start", description="Старт / Start")]
   middle = []   # отфильтрованные custom_commands кузова, в порядке передачи
   tail = [BotCommand(command="menu", description="Меню / Menu")]
   ```
   Итог: `head + middle + tail`.
2. `_RESERVED_COMMANDS`: убрать `"start"` и `"menu"` из множества дублей не
   через удаление защиты, а так — множество остаётся
   `frozenset({"menu", "start", "help", "support"})`, и `middle` формируется
   фильтрацией `custom_commands` по нему. Смысл прежний: кузов не может ни
   перебить `/start` и `/menu`, ни продублировать их в середине. Скрытые
   `/help` и `/support` по-прежнему в синее меню не попадают.
3. Порядок внутри `middle` — ровно порядок, в котором кузов передал
   `custom_commands`. Сортировку не добавлять.
4. Дедупликация: если кузов передал одно и то же имя команды дважды,
   оставить первое вхождение. Это осознанное уточнение поведения: текущий
   `dict` сохраняет позицию первого ключа, но заменяет его значение последним
   объектом. Новая реализация обязана сохранить и позицию, и описание первого
   вхождения.
5. Обработчик `/start` уже живёт в `factory._create_start_router`, а `/menu` —
   в `router.handle_cmd_menu`. Новых обработчиков не заводить.
6. Тест `test_blue_menu_command_order` в `tests/test_gate1_menu_contract.py`:
   - вызвать `setup_bot_commands` с фейковым ботом и набором доменных команд:
     `start`, `menu`, `help`, `support` и двумя одинаково названными рабочими
     командами с разными описаниями;
   - проверить, что первым идёт `start` с описанием `Старт / Start`,
     последним — `menu` с описанием `Меню / Menu`;
   - проверить, что доменные `start` и `menu` отфильтрованы, рабочая доменная
     команда стоит ровно между ними и сохранено её **первое** описание;
   - проверить, что `help` и `support`, переданные кузовом, в список не попали;
   - отдельной парой рабочих команд проверить, что порядок середины совпадает
     с порядком передачи, сортировки нет.
7. `docs/CHASSIS.md`: описать контракт синего меню и явно написать, почему
   набор один и подписи двуязычные.

**Запрещено:** `set_my_commands` с `language_code`; регистрация `/help` или
`/support` в синем меню; свой обработчик `/start` в `commands.py`.

**Проверка:**

```powershell
python -m pytest tests/test_gate1_menu_contract.py tests/test_gate11_env.py -q
python -m pytest tests -q
```

---

## Gate S1. Строка «От:» во всех статусах тикета

**Цель.** `<b>От:</b> {full_name} ({username})` присутствует в карточке
оператора и при создании, и после «Закрыть обращение» / «Открыть снова».

**Корень дефекта.** `operator_card_text` (`support_bridge.py:131`) не получает
имени, потому что `SupportTicketTarget` его не содержит, а таблица
`support_threads` не хранит. Нужны два новых столбца.

**Файлы:** `src/bot_chassis/storage/schema.sql`,
`src/bot_chassis/storage/engine.py`,
`src/bot_chassis/storage/sqlite_support_thread_store.py`,
`src/bot_chassis/support_bridge.py`, `tests/test_gate5b_tickets.py`,
`tests/test_sqlite_support_store.py`, `tests/test_storage.py`.

**Делать:**

1. `schema.sql`, таблица `support_threads` (блок 5, строки ~82–101): добавить
   два столбца **перед** `created_at`:
   ```sql
   user_full_name TEXT,
   user_username TEXT,
   ```
   Это ASCII-имена столбцов; сами значения — пользовательские данные Telegram,
   не локализация рамы, правило «БД стерильна от эмодзи и кириллицы» это не
   нарушает (оно про коды состояний).
2. `engine.py`, в уже существующем блоке `if _table_exists(conn,
   "support_threads"):` (строки ~99–145) дописать две миграции по тому же
   образцу, что и соседние:
   ```python
   _add_column_if_missing(conn, "ALTER TABLE support_threads ADD COLUMN user_full_name TEXT")
   _add_column_if_missing(conn, "ALTER TABLE support_threads ADD COLUMN user_username TEXT")
   ```
   Новый блок миграции не создавать, порядок существующих вызовов не менять.
   `UPDATE`-добивку для старых строк не писать: у старых тикетов имени нет,
   и карточка обязана корректно работать без него.
3. `sqlite_support_thread_store.py`:
   - в `SupportTicketTarget` добавить два поля **в конец**, с дефолтами:
     `user_full_name: str | None = None`, `user_username: str | None = None`.
     Позиционную совместимость существующих полей не трогать;
   - `register(...)`: добавить **keyword-only** параметры в конец
     `*, full_name: str | None = None, username: str | None = None`;
   - `_insert_message(...)`: добавить такие же keyword-only параметры и писать
     их в новые столбцы. Для строки `message_role='copy'` писать те же
     значения, что и для `header` — так `resolve_ticket` по любой из двух
     строк вернёт имя;
   - `attach_message(...)`: при вставке новых строк копировать имя из
     `ticket` (из `get_ticket`), а не оставлять `NULL`;
   - `resolve_ticket`, `get_ticket`: добавить два новых столбца в `SELECT`;
   - `_row_to_target`: заполнить два новых поля. Пустую строку приводить к
     `None`.
   - `username` хранить **без** ведущего `@`. Нормализацию делать в одном
     месте — в `register`, через `username.lstrip("@") or None`.
4. `support_bridge.py`:
   - `operator_card_text` — новая сигнатура с keyword-only хвостом:
     ```python
     def operator_card_text(
         project_label: str,
         user_id: int,
         status: str,
         *,
         full_name: str | None = None,
         username: str | None = None,
     ) -> str:
     ```
     Формат вывода строго такой:
     ```
     📩 <b>Обращение в поддержку</b>
     <b>Проект:</b> {project}
     <b>От:</b> {full_name} ({username})
     <b>User ID:</b> <code>{user_id}</code>

     <b>Статус:</b> {status_line}
     ```
     Правила: строка `От:` выводится, только если известно хоть что-то; при
     отсутствии `full_name` подставлять `Пользователь`; при отсутствии
     `username` подставлять `нет username` — ровно та же формулировка, что уже
     используется в `send_user_report_to_support`, новой не изобретать.
     `full_name` экранировать через `escape` на выводе; в БД хранить сырым.
     Пустая строка перед `<b>Статус:</b>` обязательна.
   - `refresh_operator_card`: передавать `full_name=ticket.user_full_name,
     username=ticket.user_username`.
    - `send_user_report_to_support`: завести отдельные значения без смешения
      хранения и HTML:
      `raw_full_name = user.full_name if user else None`; для шапки использовать
      только `escape(raw_full_name or "Пользователь")`, а в `register` передать
      именно `raw_full_name`. В SQLite строка `A & B` обязана лежать как
      `A & B`, не как `A &amp; B`. `username` брать из `user.username` без `@`;
      префикс рисуется только на выводе. Переменную `username_str` для шапки
      оставить как есть, формат шапки не менять.
    - `thread_store` — публично подменяемый duck-type (объект с нужными
      методами), поэтому безусловно передавать новые kwargs старой реализации
      запрещено. Перед вызовом `register` безопасно проверить сигнатуру через
      `inspect.signature`. Если `inspect` сам бросил `TypeError`/`ValueError`
      (нестандартный callable) — вызвать прежнюю сигнатуру без новых полей.
      Если есть оба параметра `full_name` / `username` или `**kwargs` —
      передать их; иначе вызвать без новых полей.
      Не ловить общий `TypeError` **после** вызова `register`: он мог возникнуть
      внутри store, и повторный вызов способен зарегистрировать тикет дважды.
   - `SupportThreadStore` (JSON-store): в `register` добавить те же
     keyword-only параметры и сразу `del` их рядом с существующим
     `del ticket_id, message_thread_id`. JSON-store карточку не
     перерисовывает, хранить имя ему незачем; сигнатуры двух store обязаны
     совпадать.
5. Тесты (`tests/test_gate5b_tickets.py`):
   - `test_operator_card_keeps_author_in_all_statuses`: создать тикет, закрыть,
     открыть снова; после каждого перехода текст карточки содержит `От:`,
     имя и `@username`;
    - `test_operator_card_without_username`: пользователь без username — в
      карточке `нет username`, падений нет;
    - `test_author_name_is_stored_raw_and_escaped_once`: имя `A & B <C>` в
      SQLite сохранено дословно, а в новой и обновлённой HTML-карточке
      экранировано ровно один раз;
    - `test_operator_card_blank_line_before_status`: в тексте присутствует
      `"\n\n<b>Статус:</b>"`.
    - `test_legacy_custom_thread_store_without_author_kwargs`: старый
      пользовательский store с прежней сигнатурой `register` получает ровно
      один вызов и тикет успешно создаётся; внутренний `TypeError` из store не
      маскируется повторным вызовом.
   - `tests/test_storage.py`: тест миграции — создать БД по схеме `0.3.0`
     **без** новых столбцов, прогнать инициализацию, убедиться, что столбцы
     появились, старые строки живы и `get_ticket` для старой строки возвращает
     `user_full_name is None` без исключения.

**Запрещено:** хранить текст сообщений; менять первичный ключ
`support_threads`; добавлять позиционные параметры; трогать формат шапки
нового обращения; ломать старый пользовательский `thread_store`; делать
fallback через `except TypeError` вокруг вызова `register`.

**Проверка:**

```powershell
python -m pytest tests/test_gate5b_tickets.py tests/test_sqlite_support_store.py tests/test_storage.py -q
python -m pytest tests -q
```

---

## Gate S2. Ответ поддержки пользователю одним сообщением

**Цель.** Текстовый ответ оператора приходит пользователю **одним** сообщением
с шапкой и кнопкой под ним.

**Принятый владельцем гибрид:**

| Что ответил оператор | Что отправляет рама |
|---|---|
| Чистый текст (`message.text`) | одно `send_message`: шапка + пустая строка + текст |
| Медиа с поддержкой подписи: photo, video, document, audio, animation, voice* | одно `copy_message` с подставленной `caption` |
| Всё остальное (sticker, video_note, контакт, локация, медиагруппа) | как сейчас: шапка `send_message` + `copy_message` |

\* `voice` поддерживает подпись в Bot API; если при живой проверке окажется
иначе — не чинить догадкой, а перевести тип в третью строку таблицы и
сообщить владельцу.

**Физический предел Telegram.** «Одно сообщение» обязательно для обычного
ответа, который помещается в лимит Bot API. Если шапка вместе с текстом не
помещается в 4096 символов либо вместе с caption — в 1024 символа, применяется
старый безопасный режим `split`: шапка и полная копия ответа. Обрезать ответ,
терять текст или молча получать ошибку Telegram запрещено.

**Файлы:** `src/bot_chassis/support_bridge.py`, `tests/test_gate5b_tickets.py`.

**Делать:**

1. В `support_bridge.py` завести явную константу — никаких «магических» списков
   по месту:
   ```python
   _CAPTIONABLE_ATTRS = ("photo", "video", "document", "audio", "animation", "voice")
   ```
   Рядом определить `_MAX_MESSAGE_TEXT = 4096` и `_MAX_CAPTION = 1024`.
2. Завести чистую функцию без I/O, чтобы её можно было протестировать отдельно:
   ```python
   def compose_support_reply(
       admin_reply_message: types.Message,
       support_header: str,
   ) -> tuple[str, str | None]:
       """Возвращает (режим, текст). Режим: 'text' | 'caption' | 'split'."""
   ```
   Логика:
   - если `media_group_id` непустой → сразу `("split", None)`: один элемент
     альбома нельзя выдавать за доставку всей медиагруппы;
   - если `admin_reply_message.text` непустой — брать безопасное HTML-
     представление `admin_reply_message.html_text`, а не сырой `.text`;
     собрать `header + "\n\n" + html_text`; если консервативная длина готовой
     строки не больше `_MAX_MESSAGE_TEXT`, вернуть `("text", payload)`, иначе
     `("split", None)`;
   - иначе если есть любой атрибут из `_CAPTIONABLE_ATTRS` — брать
     `admin_reply_message.html_caption` (если caption есть), собрать caption с
     шапкой и вернуть `caption` только при длине не больше `_MAX_CAPTION`;
     при превышении вернуть `split`;
   - иначе → `("split", None)`.
   Сырые `.text` и `.caption` нельзя склеивать с `parse_mode="HTML"`:
   символы `<`, `>` и `&` ломают разбор. `html_text` / `html_caption` сохраняют
   Telegram entities и одновременно экранируют обычный текст. Консервативная
   проверка длины может раньше выбрать `split`, но не может обрезать данные.
3. В `deliver_support_reply_to_user` блок отправки (строки ~395–408)
   переписать по режиму:
   - `text` → один `bot.send_message(chat_id=target_user_id, text=..., parse_mode="HTML", reply_markup=reply_markup)`;
   - `caption` → один `bot.copy_message(..., caption=..., parse_mode="HTML", reply_markup=reply_markup)`;
   - `split` → существующее поведение без изменений.
4. **Критично, не пропустить:** ниже по функции есть блок
   `record_message(...)` для `copied.message_id`. В режимах `text` и `caption`
   отправленное сообщение — это результат одного вызова, и именно его
   `message_id` надо записывать. Переменная, в которую кладётся результат,
   должна быть одна для всех трёх веток. Логика дедупликации
   `message_recorded` и переход тикета в `in_progress` остаются прежними и
   должны работать во всех трёх режимах.
5. Кнопка `Ответить поддержке` обязана быть под итоговым сообщением во всех
   трёх режимах. В режиме `split` она, как и сейчас, под шапкой.
6. Тесты (`tests/test_gate5b_tickets.py`):
   - `test_text_reply_arrives_as_single_message`: ответ текстом → ровно один
     исходящий вызов пользователю, в тексте есть и шапка, и текст оператора, и
     `reply_markup` с `core_sup:ureply:`;
   - `test_media_with_caption_arrives_as_single_message`: фото с подписью →
     один `CopyMessage` с нужной `caption`;
    - `test_voice_without_caption_still_single_message`: подпись пустая, шапка
      всё равно доехала;
    - `test_sticker_reply_keeps_two_messages`: стикер → шапка + копия;
    - `test_html_metacharacters_are_safe`: текст и caption с `<`, `>` и `&`
      успешно собираются, экранированы и не теряют Telegram-форматирование;
    - `test_media_group_uses_split_mode`: фото с `media_group_id` не попадает в
      одиночный caption-режим;
    - `test_over_limit_reply_uses_split_without_truncation`: текст и caption на
      границе лимита после добавления шапки переходят в `split`, полная копия
      ответа отправлена без обрезания;
   - `test_single_message_mode_records_ticket_message`: во всех режимах тикет
     перешёл в `in_progress` и `record_message` записал корректный id;
   - отдельный юнит-тест на `compose_support_reply` для всех трёх режимов.

**Запрещено:** терять `record_message`; слать больше одного сообщения в
режимах `text` и `caption`; обрезать ответ ради одного сообщения; склеивать
сырой `.text` / `.caption` с HTML-шапкой; считать элемент медиагруппы одиночным
медиа; менять контракт возврата `deliver_support_reply_to_user`
(`tuple[bool, str]`) и набор статусов.

**Проверка:**

```powershell
python -m pytest tests/test_gate5b_tickets.py tests/test_gate2_topics.py -q
python -m pytest tests -q
```

---

## Gate S3. Инлайн-кнопка «📜 История диалога»

**Цель.** Оператор видит ленту тикета, не покидая чата поддержки.

**Принятое владельцем решение по содержимому.** Текст сообщений в БД не
заводится. История строится из метаданных `support_ticket_messages`: время,
направление и ссылка на само сообщение. Это сохраняет канон стерильной БД и не
создаёт новой приватной утечки.

В таблице на один реальный ход уже записаны две технические строки: оригинал и
доставленная копия. Для операторской истории канонична только строка из чата
поддержки (`telegram_chat_id == support_chat_id`). Поэтому один реальный ход
показывается один раз, с рабочей ссылкой; строки личного диалога в ленту не
включаются.

**Файлы:** `src/bot_chassis/contracts.py`,
`src/bot_chassis/storage/sqlite_support_thread_store.py`,
`src/bot_chassis/keyboards.py`, `src/bot_chassis/support_bridge.py`,
`src/bot_chassis/router.py`, `tests/test_gate5b_tickets.py`.

**Делать:**

1. `contracts.py`: `CB_SUPPORT_HISTORY_PREFIX: str = f"{CALLBACK_PREFIX_SUPPORT}thist:"`.
   Префикс короткий намеренно: `callback_data` ограничена 64 байтами, а
   `ticket_id` — это UUID длиной 36 символов.
2. `sqlite_support_thread_store.py`: новый метод
   ```python
   def list_messages(
       self,
       ticket_id: str,
       *,
       support_chat_id: int,
       limit: int = 20,
   ) -> list[SupportTicketMessage]:
   ```
   и рядом датакласс
   ```python
   @dataclass(slots=True, frozen=True)
   class SupportTicketMessage:
       direction: str
       telegram_chat_id: int
       telegram_message_id: int
       message_thread_id: int | None
       created_at: str
   ```
   SQL: выбрать по `(bot_id, ticket_id, telegram_chat_id=support_chat_id)`.
   Для точного порядка использовать монотонный SQLite `rowid`, а не
   `telegram_message_id`: ID сообщений из разных чатов несопоставимы, а
   `created_at` имеет секундную точность. Выбрать `ORDER BY rowid DESC LIMIT ?`,
   затем вернуть в хронологическом порядке (развернуть в Python). `limit`
   ограничивает реальные ходы, потому что приватные технические копии уже
   отфильтрованы. Соединение закрывать в `finally`, как во всех соседних
   методах.
3. `support_bridge.py`: чистая функция рендера, без I/O:
   ```python
   def support_history_text(
       ticket_id: str,
       messages: Sequence[SupportTicketMessage],
   ) -> str:
   ```
   Правила:
   - заголовок `📜 <b>История обращения</b>`, затем строки
     `<b>Тикет:</b> <code>{ticket_id}</code>` и `<b>Сообщений:</b> {n}`.
     `ticket_id` экранировать через `escape`, поэтому параметр функции не
     мёртвый;
   - одна строка на сообщение: `{время} {стрелка} {ссылка}`, где
      стрелка `⬅️` для `user_to_support` и `➡️` для `support_to_user`;
   - время выводить строго как `{created_at} UTC`, где `created_at` — сырое
     значение из БД (`YYYY-MM-DD HH:MM:SS`). Функцию `utc_now()` **не
     менять**: она намеренно без суффикса зоны. Суффикс ` UTC` только в
     renderer истории. Второй часовой пояс в раму не вводить;
   - ссылка строится **только** для супергрупп, то есть когда
     `telegram_chat_id` начинается с `-100`. Внутренний id — это строковое
     представление `telegram_chat_id` без префикса `-100`. Без темы:
     `https://t.me/c/{internal}/{message_id}`; с темой:
     `https://t.me/c/{internal}/{thread_id}/{message_id}`. Личная строка сюда
     попасть не должна из-за фильтра метода; если store вернул её вопреки
     контракту, ссылку не строить и вывести `недоступно`, не утекать в ЛС;
   - если сообщений нет — вернуть текст `История пуста`;
   - параметр `support_chat_id` в renderer не добавлять: фильтрация выполнена
     store, а мёртвые параметры запрещены;
   - все подставляемые значения числовые и системные, пользовательских строк в
     renderer нет.
4. `keyboards.py`, `build_operator_ticket_keyboard`: добавить **второй** ряд с
   кнопкой `📜 История диалога` →
   `f"{CB_SUPPORT_HISTORY_PREFIX}{ticket_id}"`. Первый ряд (закрыть / открыть
   снова) не трогать: его поведение «отработанное действие снимается заменой
   разметки» остаётся. Кнопка истории присутствует в обоих состояниях.
5. `router.py`: обработчик
   ```python
   @router.callback_query(F.data.startswith(CB_SUPPORT_HISTORY_PREFIX))
   ```
   - если `store_supports_continuation(threads)` ложно — `await query.answer()`
     и выход (JSON-store ленты не ведёт);
   - достать `ticket_id`, проверить `get_ticket`; если `None` —
     `query.answer("Обращение не найдено", show_alert=True)`;
    - вызвать `list_messages(ticket_id, support_chat_id=ticket.support_chat_id)`,
      собрать текст, отправить **новым сообщением в
      тот же чат и в ту же тему** через `thread_kwargs(ticket.message_thread_id)`,
     отвечая на карточку тикета (`reply_to_message_id` — header id).
     Карточку тикета не редактировать: она должна остаться на месте.
   - Сообщение истории кнопок не несёт — это «чистый текстовый отчёт», по
     канону админки Gate 9.
6. Тесты (`tests/test_gate5b_tickets.py`):
   - `test_history_button_present_in_both_states`: кнопка есть и у открытого, и
     у закрытого тикета, и не мешает кнопке закрытия;
    - `test_history_lists_messages_in_chronological_order`;
    - `test_history_shows_one_row_per_dialog_turn`: оригинал и доставленная
      копия одного хода не дают две строки; в выборку попадает каноническая
      запись из чата поддержки;
    - `test_history_limit_counts_dialog_turns`, включая несколько записей с
      одинаковым `created_at` — порядок определяется `rowid`;
    - `test_history_builds_supergroup_links_with_topic`: проверить обе формы
      ссылки, формат времени UTC и защитный fallback без ссылки для ошибочно
      переданной строки личного чата;
   - `test_history_on_empty_ticket`: текст `История пуста`, падения нет;
   - `test_history_does_not_edit_ticket_card`: среди исходящих вызовов нет
     `EditMessageText` по header id.

**Запрещено:** сохранять тексты и медиа в SQLite; пересылать сообщения
пользователя повторно; редактировать карточку тикета; строить ссылки на
приватный чат пользователя; показывать оригинал и копию как два разных хода;
сортировать события по `telegram_message_id` между разными чатами; менять
формат `utc_now()`.

**Проверка:**

```powershell
python -m pytest tests/test_gate5b_tickets.py tests/test_sqlite_support_store.py -q
python -m pytest tests -q
```

---

## Gate R1. Документы, версия и журналы

**Файлы:** `docs/CHASSIS.md`, `docs/CHASSIS_SUPPORT_AND_UI_SPEC.md`,
`CHANGELOG.md`, `VERSION_LOG.md`, `.agents/PROJECT_LOG.md`,
`.agents/SESSION_STATE.md`, `.agents/NEW_CHAT.md`, `.agents/TASK_TODO.md`,
`.agents/ACTIVE_PLANS.md`, `pyproject.toml` (только поле версии).

**Делать:**

1. Поднять версию пакета до `0.3.1` там же, где она объявлена для `0.3.0`
   (найти через `rg "0\.3\.0" pyproject.toml src/bot_chassis/__init__.py`).
2. `CHANGELOG.md`: раздел `0.3.1` с явным разделением:
   - **Изменено:** RU-подписи служебной тройки; канон «Отмена/Назад»; порядок
     синего меню; ответ поддержки одним сообщением.
    - **Добавлено:** `CB_NAV_CANCEL`, `append_cancel_row`, `append_back_row`,
      кнопка истории диалога, столбцы `user_full_name` / `user_username`.
    - **Ломающее:** из `build_support_prompt_keyboard` удалены параметры
      `cancel_callback` и `cancel_label`. Прямые вызывающие кузова обязаны
      перейти на `back_callback` / `back_label`.
    - **Совместимость:** старый `CB_NAV_CLOSE` сохраняет закрытие без перехода
      на старт; пользовательские `thread_store` со старой сигнатурой
      `register` продолжают работать; превышающий лимит Telegram ответ
      доставляется полностью в безопасном режиме из двух сообщений;
      `Отмена` рисует стартовую карточку без повторного носителя клавиатуры.
3. `docs/CHASSIS.md`: чек-лист миграции `0.3.0 → 0.3.1` для кузова. Минимум:
    что делать с `build_support_prompt_keyboard`; что корневой экран лучше
    возвращать как `ChassisScreen`; как применять `append_back_row` в статьях
    FAQ, платёжных и иных вложенных кузовных экранах; что уже отправленный
    `Message` рама тоже снабжает «Отменой»; что `Отмена` не повторяет полный
    `/start` и не шлёт носитель клавиатуры; что менять в коде кузова не нужно
    ничего, если он не вызывал раму напрямую.
4. `docs/CHASSIS_SUPPORT_AND_UI_SPEC.md`: пометить реализованные пункты и
   зафиксировать принятые владельцем решения по §2.3 (отклонено),
   §2.5 (история по метаданным), §5 (один двуязычный набор команд), §4.1
   (handoff в PsyBot, из этого корня не делается).
5. `VERSION_LOG.md`: запись по канону — tag, HEAD, предыдущий, почему, коммиты,
    потребители (Profiling / psybot). В поле tag написать `не ставился`.
    `Implementation HEAD` — последний кодовый SHA после S3; будущий
    документационный коммит R1 не пытаться записать внутрь самого себя. Тег
    **не** ставить.
6. `PROJECT_LOG.md`: запись за дату сдачи. Обязательно отдельной строкой
   зафиксировать разрешённое владельцем исключение — правку одной строки в
   замороженном `tests/test_chassis.py` (Gate U1, п. 5) — и то, что число
   тестов осталось 19.
7. `SESSION_STATE.md`, `NEW_CHAT.md`, `TASK_TODO.md`, `ACTIVE_PLANS.md`:
   привести к фактическому состоянию, следующим шагом указать `B7`.

**Запрещено:** `git tag`, `git push`, merge в `main`, трогать тег `profiling`,
live-smoke в Telegram.

**Проверка:**

```powershell
python -m pytest tests -q
python -m compileall -q src/bot_chassis
git diff --check
```

---

## Gate B7. Независимый аудит

Выполняется **в отдельном чате**, не исполнителем. Промпт:
`.agents/AUDIT_0_3_1_PROMPT.md`.

Граница: `FULL-0.3-RELEASE+0.3.1` — сквозной аудит `v0.2.2 → 0.3.1` по решению
владельца, то есть `0.3.0` и `0.3.1` проверяются вместе одним заходом.
Полный чек-лист `0.3.0` берётся из `.agents/AUDIT_0_3_FULL_PROMPT.md`,
специфика `0.3.1` — из `.agents/AUDIT_0_3_1_PROMPT.md`.

---

## Приложение. Что в пакет не входит

| Пункт | Решение владельца 2026-10-01 |
|---|---|
| §2.3 — вшить текст вопроса в карточку оператора | **Отклонено.** Ломает Reply-адресацию по копии и дедуп `record_message`. |
| §2.5 — история с текстами сообщений | **Отклонено.** БД остаётся без текстов; история строится по метаданным. |
| §4.1 — вычистка `Language / Язык` | **Не в этом репозитории.** Handoff в чат PsyBot (`C:\Python\tg_psy_tests`). |
| §4.2 — `enable_language_switch=False` у Profiling | Уже поддержано кодом (`config.py:32`). Это настройка потребителя, кода рамы не требует. |
| Переименование репозитория | Gate 13, пропущен владельцем 2026-09-29. |
| Тег `v0.3.1`, push, merge | Только по отдельной команде владельца. |
| Полный `/start` на каждую «Отмена» | **Отклонено 2026-10-01.** Только стартовая карточка, без носителя Reply Keyboard. |
