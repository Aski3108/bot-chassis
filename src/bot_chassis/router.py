"""Основной маршрутизатор шасси кнопочного интерфейса (Button Chassis).

Ключевые свойства:
1. Доменные кнопки (domain_rows) автоматически входят в список кнопок,
   сбрасывающих ожидание ввода тикета поддержки.
2. Сообщение /menu несёт нижнюю Reply-клавиатуру и НИКОГДА не регистрируется
   как удаляемая карточка. Нижняя полоска кнопок не пропадёт.
3. Карточки Кабинета, Info и Поддержки регистрируются в UserScreenTracker и закрываются
   в соответствии с политикой CardClosePolicy (DELETE или DROP_MARKUP).
4. Порты render_cabinet_callback и render_info_callback: если колбэк возвращает
   отправленное Message, оно автоматически запоминается в трекере экранов.
5. Команды /help и /support открывают соответствующие разделы.
6. Тумблеры enable_cabinet, enable_info, enable_support позволяют отключать разделы.
7. Поддержка персональной локали пользователя через get_user_locale(user_id).
8. СТРОГИЙ фильтр SupportTicketActiveFilter: чужие ссылки, файлы и команды
   пролетают сквозь шасси к доменному шлюзу.
"""

from __future__ import annotations
import asyncio
from typing import Optional, Callable, Awaitable, Sequence
from aiogram import Router, types, F, Bot
from aiogram.enums import ChatType
from aiogram.filters import Command, Filter
from loguru import logger

from .contracts import (
    BTN_CABINET_RU,
    BTN_CABINET_EN,
    BTN_INFO_RU,
    BTN_INFO_EN,
    BTN_SUPPORT_RU,
    BTN_SUPPORT_EN,
    is_main_menu_button,
    extract_domain_labels,
    CB_SUPPORT_CANCEL,
    CB_NAV_CLOSE,
)
from .keyboards import (
    build_main_menu_keyboard,
    build_support_prompt_keyboard,
)
from .lifecycle import UserScreenTracker, CardClosePolicy
from .dispatcher import ActiveTaskTracker
from .followup import PendingInputStore, PendingInput, PendingInputKind
from .support_bridge import (
    SupportThreadStore,
    send_user_report_to_support,
    deliver_support_reply_to_user,
)


class SupportTicketActiveFilter(Filter):
    """
    Фильтр, пропускающий сообщение ТОЛЬКО если пользователь прямо сейчас пишет в саппорт.
    Если пользователь нажал любую кнопку меню (служебную или доменную) — тикет прерывается!
    """
    def __init__(
        self,
        store: PendingInputStore,
        domain_labels: Optional[frozenset[str]] = None,
    ) -> None:
        self.store = store
        self.domain_labels = domain_labels or frozenset()

    async def __call__(self, message: types.Message) -> bool:
        if not message.from_user:
            return False
        if message.text and message.text.startswith("/"):
            return False
        # Клик по любой кнопке меню (включая доменные «Ваши чаты») сбрасывает ввод
        if is_main_menu_button(message.text, domain_labels=self.domain_labels):
            self.store.clear(message.from_user.id)
            return False
        return self.store.is_active(message.from_user.id, PendingInputKind.SUPPORT_MESSAGE)


def create_button_chassis_router(
    support_chat_id: Optional[int] = None,
    domain_rows: Optional[Sequence[Sequence[str]]] = None,
    enable_cabinet: bool = True,
    enable_info: bool = True,
    enable_support: bool = True,
    render_cabinet_callback: Optional[Callable[[types.Message, int, Bot], Awaitable[Optional[types.Message]]]] = None,
    render_info_callback: Optional[Callable[[types.Message, int, Bot], Awaitable[Optional[types.Message]]]] = None,
    cabinet_close_policy: CardClosePolicy = CardClosePolicy.DELETE,
    info_close_policy: CardClosePolicy = CardClosePolicy.DELETE,
    get_user_locale: Optional[Callable[[int], str]] = None,
    task_tracker: Optional[ActiveTaskTracker] = None,
    pending_store: Optional[PendingInputStore] = None,
    screen_tracker: Optional[UserScreenTracker] = None,
    thread_store: Optional[SupportThreadStore] = None,
    project_label: str = "Сервис",
    default_locale: str = "ru",
    extra_support_inline: Optional[Sequence[Sequence[tuple[str, str]]]] = None,
) -> Router:
    """
    Фабрика универсального роутера шасси кнопок.
    
    Все зависимости экземплярные (не делят память между ботами).
    """
    router = Router(name="button_chassis")
    tracker = task_tracker or ActiveTaskTracker()
    pending = pending_store or PendingInputStore(ttl_seconds=900.0)
    screens = screen_tracker or UserScreenTracker()
    threads = thread_store if thread_store is not None else SupportThreadStore()

    domain_labels = extract_domain_labels(domain_rows)

    def _resolve_locale(user_id: int) -> str:
        if get_user_locale:
            try:
                return get_user_locale(user_id) or default_locale
            except Exception:
                pass
        return default_locale

    def _menu_kb(user_id: int):
        loc = _resolve_locale(user_id)
        return build_main_menu_keyboard(
            domain_rows=domain_rows,
            locale=loc,
            enable_cabinet=enable_cabinet,
            enable_info=enable_info,
            enable_support=enable_support,
        )

    # ----------------------------------------------------------------------
    # 1. КОМАНДА /menu: Восстановление нижней клавиатуры (НЕ УДАЛЯЕТСЯ!)
    # ----------------------------------------------------------------------
    @router.message(Command("menu"), F.chat.type == ChatType.PRIVATE)
    async def handle_cmd_menu(message: types.Message):
        user_id = message.from_user.id if message.from_user else 0
        pending.clear(user_id)
        # Закрываем предыдущую карточку контента, но само сообщение с клавиатурой живёт!
        await screens.close_previous_card(message.bot, user_id)

        await message.answer(
            "📱 <b>Главное меню</b>\n\nИспользуйте кнопки внизу экрана:",
            reply_markup=_menu_kb(user_id),
            parse_mode="HTML",
        )

    # ----------------------------------------------------------------------
    # 2. РАЗДЕЛ: [👤 Личный кабинет] (кнопка меню)
    # ----------------------------------------------------------------------
    if enable_cabinet:
        cabinet_aliases = {BTN_CABINET_RU, BTN_CABINET_EN, "Личный кабинет", "Кабинет", "💼 Личный кабинет", "Account"}

        @router.message(F.text.in_(cabinet_aliases))
        async def handle_cabinet(message: types.Message):
            user_id = message.from_user.id if message.from_user else 0
            current_task = asyncio.current_task()
            if not tracker.should_process(user_id, "menu:cabinet", current_task):
                return

            try:
                pending.clear(user_id)
                # Закрываем предыдущую карточку экрана перед показом новой
                await screens.close_previous_card(message.bot, user_id)

                if render_cabinet_callback:
                    sent = await render_cabinet_callback(message, user_id, message.bot)
                    if sent and isinstance(sent, types.Message):
                        screens.remember_card(user_id, sent.chat.id, sent.message_id, policy=cabinet_close_policy)
                    else:
                        logger.warning(
                            f"render_cabinet_callback вернул {type(sent).__name__} вместо aiogram.types.Message. "
                            f"Экран не зафиксирован в UserScreenTracker и не закроется автоматически."
                        )
                else:
                    # Нейтральная карточка шасси (без зашитой коммерции)
                    sent = await message.answer(
                        f"👤 <b>Личный кабинет</b>\n\n"
                        f"ID: <code>{user_id}</code>\n"
                        f"Раздел настроен в шасси.",
                        parse_mode="HTML",
                    )
                    screens.remember_card(user_id, sent.chat.id, sent.message_id, policy=cabinet_close_policy)
            finally:
                tracker.release(user_id, current_task)

    # ----------------------------------------------------------------------
    # 3. РАЗДЕЛ: [ℹ️ Info] (кнопка меню и команда /help)
    # ----------------------------------------------------------------------
    if enable_info:
        info_aliases = {BTN_INFO_RU, BTN_INFO_EN, "Info", "О сервисе", "ℹ️ О сервисе", "Информация", "FAQ"}

        async def _open_info(message: types.Message):
            user_id = message.from_user.id if message.from_user else 0
            current_task = asyncio.current_task()
            if not tracker.should_process(user_id, "menu:info", current_task):
                return

            try:
                pending.clear(user_id)
                await screens.close_previous_card(message.bot, user_id)

                if render_info_callback:
                    sent = await render_info_callback(message, user_id, message.bot)
                    if sent and isinstance(sent, types.Message):
                        screens.remember_card(user_id, sent.chat.id, sent.message_id, policy=info_close_policy)
                    else:
                        logger.warning(
                            f"render_info_callback вернул {type(sent).__name__} вместо aiogram.types.Message. "
                            f"Экран не зафиксирован в UserScreenTracker и не закроется автоматически."
                        )
                else:
                    # Нейтральная карточка Info
                    sent = await message.answer(
                        f"ℹ️ <b>О сервисе ({project_label})</b>\n\n"
                        f"Информационный раздел проекта.",
                        parse_mode="HTML",
                    )
                    screens.remember_card(user_id, sent.chat.id, sent.message_id, policy=info_close_policy)
            finally:
                tracker.release(user_id, current_task)

        @router.message(F.text.in_(info_aliases))
        async def handle_info(message: types.Message):
            await _open_info(message)

        @router.message(Command("help"), F.chat.type == ChatType.PRIVATE)
        async def handle_cmd_help(message: types.Message):
            await _open_info(message)

    # ----------------------------------------------------------------------
    # 4. РАЗДЕЛ: [💬 Поддержка] (кнопка меню и команда /support)
    # ----------------------------------------------------------------------
    if enable_support:
        support_aliases = {BTN_SUPPORT_RU, BTN_SUPPORT_EN, "Поддержка", "Служба поддержки", "🛟 Поддержка", "Report", "Support"}

        async def _open_support(message: types.Message):
            user_id = message.from_user.id if message.from_user else 0
            current_task = asyncio.current_task()
            if not tracker.should_process(user_id, "menu:support", current_task):
                return

            try:
                # Активируем режим ожидания ввода тикета
                pending.set(
                    user_id,
                    PendingInput(kind=PendingInputKind.SUPPORT_MESSAGE, origin_chat_id=message.chat.id),
                )
                await screens.close_previous_card(message.bot, user_id)

                support_prompt = (
                    f"💬 <b>Служба поддержки ({project_label})</b>\n\n"
                    f"Напишите ваш вопрос или опишите проблему <b>прямо в ответном сообщении</b>.\n\n"
                    f"Вы можете отправить текст, скриншот или голосовое сообщение — "
                    f"команда получит его и ответит прямо сюда.\n\n"
                    f"<i>Для отмены нажмите кнопку ниже или выберите любой пункт меню.</i>"
                )
                prompt_kb = build_support_prompt_keyboard(
                    cancel_callback=CB_SUPPORT_CANCEL,
                    extra_rows=extra_support_inline,
                )
                sent = await message.answer(support_prompt, reply_markup=prompt_kb, parse_mode="HTML")
                screens.remember_card(user_id, sent.chat.id, sent.message_id, policy=CardClosePolicy.DELETE)
            finally:
                tracker.release(user_id, current_task)

        @router.message(F.text.in_(support_aliases))
        async def handle_support(message: types.Message):
            await _open_support(message)

        @router.message(Command("support"), F.chat.type == ChatType.PRIVATE)
        async def handle_cmd_support(message: types.Message):
            await _open_support(message)

        # Инлайн-кнопка отмены ввода тикета
        @router.callback_query(F.data == CB_SUPPORT_CANCEL)
        async def handle_support_cancel(query: types.CallbackQuery):
            user_id = query.from_user.id if query.from_user else 0
            pending.clear(user_id)
            screens.forget_card(user_id)
            await query.answer("Обращение отменено")
            if query.message:
                try:
                    await query.message.delete()
                except Exception:
                    await query.message.edit_reply_markup(reply_markup=None)

    # ----------------------------------------------------------------------
    # 5. ОБЩИЕ ИНЛАЙН-ОБРАБОТЧИКИ
    # ----------------------------------------------------------------------
    @router.callback_query(F.data == CB_NAV_CLOSE)
    async def handle_nav_close(query: types.CallbackQuery):
        user_id = query.from_user.id if query.from_user else 0
        screens.forget_card(user_id)
        await query.answer()
        if query.message:
            try:
                await query.message.delete()
            except Exception:
                await query.message.edit_reply_markup(reply_markup=None)

    # ----------------------------------------------------------------------
    # 6. ПРИЁМ ТИКЕТА ПОЛЬЗОВАТЕЛЯ (СТРОГИЙ ФИЛЬТР! Никакого голого router.message)
    # ----------------------------------------------------------------------
    if enable_support:
        @router.message(SupportTicketActiveFilter(pending, domain_labels=domain_labels))
        async def handle_user_support_ticket(message: types.Message):
            user_id = message.from_user.id if message.from_user else 0
            pending.clear(user_id)

            if not support_chat_id:
                await message.answer(
                    "⚠️ Служба поддержки временно недоступна (чат поддержки не настроен)."
                )
                return

            copied_id = await send_user_report_to_support(
                bot=message.bot,
                support_chat_id=support_chat_id,
                user_message=message,
                thread_store=threads,
                project_label=project_label,
            )
            if copied_id:
                # Чек тикета НЕ должен быть новым носителем клавиатуры
                await message.answer(
                    "✅ <b>Ваше сообщение передано в службу поддержки.</b>\n"
                    "Мы ответим вам прямо в этот диалог.",
                    parse_mode="HTML",
                )
            else:
                await message.answer(
                    "⚠️ Не удалось отправить сообщение (возможно, превышен лимит активных обращений без ответа)."
                )

    # ----------------------------------------------------------------------
    # 7. ОТВЕТ АДМИНИСТРАТОРА (СТРОГО внутри support_chat_id с Reply)
    # ----------------------------------------------------------------------
    if enable_support and support_chat_id:
        @router.message(F.chat.id == support_chat_id, F.reply_to_message)
        async def handle_admin_reply_message(message: types.Message):
            success, status = await deliver_support_reply_to_user(
                bot=message.bot,
                admin_reply_message=message,
                thread_store=threads,
            )
            if not success:
                # Если ответ не привязан к тикету (админы переписываются между собой) — тишина
                if status in {"UNKNOWN_THREAD", "FOREIGN_ORIGIN"}:
                    return
                # Уведомляем админа ТОЛЬКО при реальной ошибке доставки известному пользователю
                await message.reply(f"⚠️ {status}")
            else:
                try:
                    await message.react([types.ReactionTypeEmoji(emoji="👍")])
                except Exception:
                    pass

    return router
