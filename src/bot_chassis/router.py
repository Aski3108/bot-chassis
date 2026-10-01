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
    LEGACY_BTN_INFO_ALIASES,
    BTN_SUPPORT_RU,
    BTN_SUPPORT_EN,
    is_main_menu_button,
    extract_domain_labels,
    CB_SUPPORT_CANCEL,
    CB_SUPPORT_REQUEST,
    CB_SUPPORT_DONATE,
    CB_SUPPORT_REVIEW,
    CB_SUPPORT_BACK,
    CB_SUPPORT_HUB,
    CB_NAV_CLOSE,
    CB_SUPPORT_TICKET_CLOSE_PREFIX,
    CB_SUPPORT_TICKET_REOPEN_PREFIX,
    CB_SUPPORT_USER_REPLY_PREFIX,
)
from .keyboards import (
    build_main_menu_keyboard,
    build_support_prompt_keyboard,
    build_support_overview_keyboard,
    build_donation_keyboard,
)
from .lifecycle import UserScreenTracker, CardClosePolicy
from .dispatcher import ActiveTaskTracker
from .config import SkuItem
from .followup import PendingInputStore, PendingInput, PendingInputKind
from .localization import ChassisScreen, MarkupContext, decorate_info_markup
from .support_bridge import (
    SupportThreadStore,
    send_user_report_to_support,
    send_user_followup_to_support,
    deliver_support_reply_to_user,
    refresh_operator_card,
    store_supports_continuation,
)
from .storage.sqlite_support_thread_store import TicketLimitExceeded


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
        pending = self.store.get(message.from_user.id)
        return pending is not None and pending.kind in {
            PendingInputKind.SUPPORT_MESSAGE,
            PendingInputKind.SUPPORT_REPLY,
        }


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
    *,
    before_chassis_menu_action: Optional[Callable[[int], Awaitable[None]]] = None,
    language_switch_enabled: bool = False,
    support_thread_id: int | None = None,
    donation_items: Sequence[SkuItem] = (),
    donation_hint: str | None = None,
    review_enabled: bool = False,
    on_support_back: Optional[Callable[[types.Message, int], Awaitable[None]]] = None,
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

    async def _run_before_chassis_menu(user_id: int) -> None:
        if before_chassis_menu_action is None:
            return
        await before_chassis_menu_action(user_id)

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
                await _run_before_chassis_menu(user_id)
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
        info_aliases = set(LEGACY_BTN_INFO_ALIASES)

        async def _open_info(message: types.Message):
            user_id = message.from_user.id if message.from_user else 0
            current_task = asyncio.current_task()
            if not tracker.should_process(user_id, "menu:info", current_task):
                return

            try:
                await _run_before_chassis_menu(user_id)
                pending.clear(user_id)
                await screens.close_previous_card(message.bot, user_id)

                if render_info_callback:
                    sent = await render_info_callback(message, user_id, message.bot)
                    if isinstance(sent, ChassisScreen):
                        markup = sent.markup
                        if language_switch_enabled:
                            markup = decorate_info_markup(
                                markup,
                                MarkupContext(locale=_resolve_locale(user_id), user_id=user_id),
                            )
                        delivered = await message.answer(
                            sent.text,
                            reply_markup=markup,
                            parse_mode=sent.parse_mode,
                        )
                        screens.remember_card(
                            user_id,
                            delivered.chat.id,
                            delivered.message_id,
                            policy=info_close_policy,
                        )
                    elif sent and isinstance(sent, types.Message):
                        if language_switch_enabled:
                            logger.warning(
                                "render_info_callback уже отправил Message. "
                                "Языковая кнопка не вставлена. Верните ChassisScreen "
                                "или вызовите decorate_info_markup до отправки."
                            )
                        screens.remember_card(user_id, sent.chat.id, sent.message_id, policy=info_close_policy)
                    else:
                        logger.warning(
                            f"render_info_callback вернул {type(sent).__name__} вместо aiogram.types.Message. "
                            f"Экран не зафиксирован в UserScreenTracker и не закроется автоматически."
                        )
                else:
                    markup = None
                    if language_switch_enabled:
                        markup = decorate_info_markup(
                            None,
                            MarkupContext(locale=_resolve_locale(user_id), user_id=user_id),
                        )
                    # Нейтральная двуязычная карточка остаётся корректной после toggle.
                    sent = await message.answer(
                        f"ℹ️ <b>Info/FAQ ({project_label})</b>\n\n"
                        f"Информация о проекте / Project information.",
                        reply_markup=markup,
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
    # 4. РАЗДЕЛ: [💬 Поддержка] — обзор, скрытый /support сразу в форму
    # ----------------------------------------------------------------------
    if enable_support:
        support_aliases = {BTN_SUPPORT_RU, BTN_SUPPORT_EN, "Поддержка", "Служба поддержки", "🛟 Поддержка", "Report", "Support"}
        donate_rows = tuple(
            (f"{sku.title} — {sku.stars_price} ⭐", f"buy_sku:{sku.sku_code}")
            for sku in donation_items
        )

        def _overview_markup() -> types.InlineKeyboardMarkup:
            return build_support_overview_keyboard(
                show_review=review_enabled,
                show_donate=bool(donate_rows),
            )

        def _request_markup() -> types.InlineKeyboardMarkup:
            return build_support_prompt_keyboard(
                cancel_callback=CB_SUPPORT_CANCEL,
                extra_rows=extra_support_inline,
            )

        def _overview_text() -> str:
            return (
                f"💬 <b>Поддержка ({project_label})</b>\n\n"
                "Выберите действие."
            )

        def _request_text() -> str:
            return (
                f"💬 <b>Служба поддержки ({project_label})</b>\n\n"
                "Можно отправить текст, изображение, видео, голосовое сообщение или документ.\n\n"
                "<i>Отмена или пункт меню сбрасывают ожидание.</i>"
            )

        def _review_text() -> str:
            return (
                f"⭐ <b>Отзыв ({project_label})</b>\n\n"
                "Отправьте текст, одно медиа или медиа с подписью.\n\n"
                "<i>Перед отправкой спросим согласие на публичную публикацию.</i>"
            )

        async def _remember(user_id: int, sent: types.Message) -> None:
            screens.remember_card(user_id, sent.chat.id, sent.message_id, policy=CardClosePolicy.DELETE)

        async def _edit_or_answer(event: types.Message | types.CallbackQuery, text: str, markup) -> None:
            user_id = event.from_user.id if event.from_user else 0
            if isinstance(event, types.CallbackQuery) and event.message:
                try:
                    await event.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
                    await _remember(user_id, event.message)
                    return
                except Exception:
                    pass
            target = event.message if isinstance(event, types.CallbackQuery) else event
            if target is None:
                return
            sent = await target.answer(text, reply_markup=markup, parse_mode="HTML")
            await _remember(user_id, sent)

        async def _open_overview(event: types.Message | types.CallbackQuery, *, run_hook: bool = True) -> None:
            user_id = event.from_user.id if event.from_user else 0
            current_task = asyncio.current_task()
            if not tracker.should_process(user_id, "menu:support", current_task):
                return
            try:
                if run_hook:
                    await _run_before_chassis_menu(user_id)
                pending.clear(user_id)
                if isinstance(event, types.Message) and event.bot is not None:
                    await screens.close_previous_card(event.bot, user_id)
                await _edit_or_answer(event, _overview_text(), _overview_markup())
            finally:
                tracker.release(user_id, current_task)

        async def _open_request(event: types.Message | types.CallbackQuery, *, run_hook: bool = True) -> None:
            user_id = event.from_user.id if event.from_user else 0
            current_task = asyncio.current_task()
            if not tracker.should_process(user_id, "menu:support-request", current_task):
                return
            try:
                if run_hook:
                    await _run_before_chassis_menu(user_id)
                chat_id = event.message.chat.id if isinstance(event, types.CallbackQuery) and event.message else event.chat.id
                pending.set(
                    user_id,
                    PendingInput(kind=PendingInputKind.SUPPORT_MESSAGE, origin_chat_id=chat_id),
                )
                bot = event.bot
                if bot is not None and isinstance(event, types.Message):
                    await screens.close_previous_card(bot, user_id)
                await _edit_or_answer(event, _request_text(), _request_markup())
            finally:
                tracker.release(user_id, current_task)

        async def _open_review(event: types.Message | types.CallbackQuery, *, run_hook: bool = True) -> None:
            user_id = event.from_user.id if event.from_user else 0
            current_task = asyncio.current_task()
            if not tracker.should_process(user_id, "menu:support-review", current_task):
                return
            try:
                if run_hook:
                    await _run_before_chassis_menu(user_id)
                chat_id = event.message.chat.id if isinstance(event, types.CallbackQuery) and event.message else event.chat.id
                pending.set(
                    user_id,
                    PendingInput(kind=PendingInputKind.REVIEW, origin_chat_id=chat_id),
                )
                bot = event.bot
                if bot is not None and isinstance(event, types.Message):
                    await screens.close_previous_card(bot, user_id)
                await _edit_or_answer(event, _review_text(), _request_markup())
            finally:
                tracker.release(user_id, current_task)

        @router.message(F.text.in_(support_aliases))
        async def handle_support(message: types.Message):
            await _open_overview(message)

        @router.message(Command("support"), F.chat.type == ChatType.PRIVATE)
        async def handle_cmd_support(message: types.Message):
            await _open_request(message)

        @router.callback_query(F.data == CB_SUPPORT_REQUEST)
        async def handle_support_request(query: types.CallbackQuery):
            await query.answer()
            await _open_request(query, run_hook=False)

        if review_enabled:
            @router.callback_query(F.data == CB_SUPPORT_REVIEW)
            async def handle_support_review(query: types.CallbackQuery):
                await query.answer()
                await _open_review(query, run_hook=False)

        @router.callback_query(F.data == CB_SUPPORT_HUB)
        async def handle_support_hub(query: types.CallbackQuery):
            await query.answer()
            await _open_overview(query, run_hook=False)

        @router.callback_query(F.data == CB_SUPPORT_DONATE)
        async def handle_support_donate(query: types.CallbackQuery):
            if not donate_rows:
                await query.answer()
                return
            user_id = query.from_user.id if query.from_user else 0
            pending.clear(user_id)
            hint = f"\n\n{donation_hint}" if donation_hint else ""
            text = f"💛 <b>Поддержать проект</b>{hint}"
            markup = build_donation_keyboard(donate_rows)
            await query.answer()
            await _edit_or_answer(query, text, markup)

        @router.callback_query(F.data == CB_SUPPORT_BACK)
        async def handle_support_back(query: types.CallbackQuery):
            user_id = query.from_user.id if query.from_user else 0
            pending.clear(user_id)
            screens.forget_card(user_id)
            await query.answer()
            if query.message:
                try:
                    await query.message.delete()
                except Exception:
                    await query.message.edit_reply_markup(reply_markup=None)
            if on_support_back is not None and query.message is not None:
                await on_support_back(query.message, user_id)

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

        @router.callback_query(F.data.startswith(CB_SUPPORT_USER_REPLY_PREFIX))
        async def handle_support_user_reply(query: types.CallbackQuery):
            user_id = query.from_user.id if query.from_user else 0
            ticket_id = (query.data or "")[len(CB_SUPPORT_USER_REPLY_PREFIX):]
            get_ticket = getattr(threads, "get_ticket", None)
            ticket = get_ticket(ticket_id) if callable(get_ticket) else None
            if ticket is None or ticket.user_id != user_id:
                await query.answer("Обращение не найдено", show_alert=True)
                return
            if ticket.ticket_status not in {"open", "in_progress"}:
                await query.answer("Обращение уже закрыто", show_alert=True)
                return
            chat_id = query.message.chat.id if query.message else user_id
            pending.set(
                user_id,
                PendingInput(
                    kind=PendingInputKind.SUPPORT_REPLY,
                    origin_chat_id=chat_id,
                    ticket_id=ticket_id,
                ),
            )
            await query.answer()
            await _edit_or_answer(
                query,
                (
                    f"💬 <b>Ответ в обращение</b>\n\n"
                    "Можно отправить текст, изображение, видео, голосовое сообщение или документ.\n\n"
                    "<i>Сообщение уйдёт в тот же диалог. Отмена сбрасывает ожидание.</i>"
                ),
                _request_markup(),
            )

        @router.callback_query(F.data.startswith(CB_SUPPORT_TICKET_CLOSE_PREFIX))
        async def handle_support_ticket_close(query: types.CallbackQuery):
            if not store_supports_continuation(threads):
                await query.answer()
                return
            ticket_id = (query.data or "")[len(CB_SUPPORT_TICKET_CLOSE_PREFIX):]
            close_ticket = getattr(threads, "close_ticket", None)
            changed = close_ticket(ticket_id) if callable(close_ticket) else 0
            if not changed:
                await query.answer("Обращение уже закрыто")
                return
            await query.answer("Обращение закрыто")
            await refresh_operator_card(query.bot, threads, ticket_id, project_label)

        @router.callback_query(F.data.startswith(CB_SUPPORT_TICKET_REOPEN_PREFIX))
        async def handle_support_ticket_reopen(query: types.CallbackQuery):
            if not store_supports_continuation(threads):
                await query.answer()
                return
            ticket_id = (query.data or "")[len(CB_SUPPORT_TICKET_REOPEN_PREFIX):]
            reopen_ticket = getattr(threads, "reopen_ticket", None)
            try:
                changed = reopen_ticket(ticket_id) if callable(reopen_ticket) else 0
            except TicketLimitExceeded:
                await query.answer("Лимит активных обращений", show_alert=True)
                return
            if not changed:
                await query.answer("Нельзя открыть снова")
                return
            await query.answer("Обращение открыто снова")
            await refresh_operator_card(query.bot, threads, ticket_id, project_label)

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
            waiting = pending.get(user_id)
            pending.clear(user_id)

            if not support_chat_id:
                await message.answer(
                    "⚠️ Служба поддержки временно недоступна (чат поддержки не настроен)."
                )
                return

            if (
                waiting is not None
                and waiting.kind == PendingInputKind.SUPPORT_REPLY
                and waiting.ticket_id
            ):
                copied_id = await send_user_followup_to_support(
                    bot=message.bot,
                    user_message=message,
                    thread_store=threads,
                    ticket_id=waiting.ticket_id,
                )
            else:
                copied_id = await send_user_report_to_support(
                    bot=message.bot,
                    support_chat_id=support_chat_id,
                    user_message=message,
                    thread_store=threads,
                    project_label=project_label,
                    message_thread_id=support_thread_id,
                )
            if copied_id:
                # Чек тикета НЕ должен быть новым носителем клавиатуры
                if message.bot is not None:
                    await screens.close_previous_card(message.bot, user_id)
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
                expected_thread_id=support_thread_id,
                project_label=project_label,
            )
            if not success:
                # Если ответ не привязан к тикету (админы переписываются между собой) — тишина
                if status in {"UNKNOWN_THREAD", "FOREIGN_ORIGIN", "ALREADY_ANSWERED", "WRONG_THREAD"}:
                    return
                # Уведомляем админа ТОЛЬКО при реальной ошибке доставки известному пользователю
                await message.reply(f"⚠️ {status}")
            else:
                try:
                    await message.react([types.ReactionTypeEmoji(emoji="👍")])
                except Exception:
                    pass

    return router
