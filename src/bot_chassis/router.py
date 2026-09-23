"""
Основной маршрутизатор универсального костяка бота (bot_chassis.router).
Связывает постоянное нижнее меню, экраны Кабинета, Info и Поддержки,
а также обрабатывает двусторонний мост Chat Listener.
"""

import asyncio
from typing import Optional
from aiogram import Router, types, F, Bot
from aiogram.filters import CommandStart, Command
from loguru import logger

from .contracts import (
    BTN_CABINET,
    BTN_INFO,
    BTN_SUPPORT,
    ALL_MAIN_MENU_BUTTONS,
    is_main_menu_button,
    CALLBACK_PREFIX_CABINET,
    CALLBACK_PREFIX_INFO,
    CALLBACK_PREFIX_SUPPORT,
    CALLBACK_PREFIX_NAV,
)
from .keyboards import (
    build_main_menu_keyboard,
    build_cabinet_inline_keyboard,
    build_info_inline_keyboard,
    build_support_inline_keyboard,
)
from .lifecycle import (
    edit_or_send,
    close_previous_user_screen,
    close_screen,
)
from .dispatcher import get_task_tracker
from .followup import (
    get_pending_input_store,
    PendingInput,
    PendingInputKind,
)
from .support_bridge import (
    send_user_report_to_support,
    deliver_support_reply_to_user,
)


def create_bot_chassis_router(
    support_chat_id: Optional[int] = None,
    project_name: str = "Profiling Framework",
) -> Router:
    """
    Фабрика универсального роутера bot_chassis.
    Принимает support_chat_id для работы моста Chat Listener.
    """
    router = Router(name="bot_chassis")
    tracker = get_task_tracker()
    pending_store = get_pending_input_store()

    # ----------------------------------------------------------------------
    # 1. СТАРТ (/start): Флеш-экран 3 сек -> Приветствие + 152-ФЗ + Меню
    # ----------------------------------------------------------------------
    @router.message(CommandStart())
    async def handle_start(message: types.Message):
        user_id = message.from_user.id if message.from_user else 0
        current_task = asyncio.current_task()
        if not tracker.should_process(user_id, "start", current_task):
            return

        try:
            # Сбрасываем любые зависшие режимы ожидания ввода
            pending_store.clear(user_id)

            # Шаг 1: Стильный флеш-экран преимуществ на 3 секунды
            flash_text = (
                f"✨ <b>{project_name}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"⚡ <i>Глубокий психолингвистический анализ</i>\n"
                f"🔒 <i>100% анонимно (RAM-only обработка)</i>\n"
                f"🎯 <i>Научно валидированные шкалы (C1–C7)</i>"
            )
            flash_msg = await message.answer(flash_text, parse_mode="HTML")

            # Пауза 3.0 секунды
            await asyncio.sleep(3.0)

            # Шаг 2: Бесшовная замена на официальное приветствие с правилами
            main_text = (
                f"👋 <b>Добро пожаловать в {project_name}!</b>\n\n"
                f"Я провожу глубокую аналитику <b>Telegram-каналов</b>, личных текстов "
                f"или <b>диалогов двух человек</b> на предмет психотипа, эмоций, скрытых мотивов и манипуляций.\n\n"
                f"📌 <b>Как начать анализ:</b>\n"
                f"• Отправьте ссылку на открытый канал (например, <code>@channel</code>).\n"
                f"• Или загрузите экспорт переписки/канала в формате <b>JSON</b> или <b>TXT</b>.\n\n"
                f"⚖️ <i>Отправляя данные, вы соглашаетесь с правилами сервиса (152-ФЗ). "
                f"Тексты обрабатываются в оперативной памяти и не сохраняются на диск. "
                f"Отчёт носит вероятностный характер.</i>"
            )

            menu_kb = build_main_menu_keyboard()
            await edit_or_send(flash_msg, main_text, reply_markup=menu_kb, parse_mode="HTML")

        finally:
            tracker.release(user_id, current_task)

    # ----------------------------------------------------------------------
    # 2. КНОПКА: [👤 Личный кабинет]
    # ----------------------------------------------------------------------
    @router.message(F.text.in_({BTN_CABINET, "Личный кабинет", "💼 Личный кабинет"}))
    async def handle_cabinet_button(message: types.Message):
        user_id = message.from_user.id if message.from_user else 0
        current_task = asyncio.current_task()
        if not tracker.should_process(user_id, "menu:cabinet", current_task):
            return

        try:
            pending_store.clear(user_id)
            user = message.from_user
            username_str = f"@{user.username}" if (user and user.username) else "нет username"

            # Закрываем предыдущий открытый инлайн-экран
            await close_previous_user_screen(message.bot, user_id, message.message_id)

            cabinet_text = (
                f"💼 <b>Личный кабинет</b>\n\n"
                f"👤 <b>Пользователь:</b> {username_str} (<code>{user_id}</code>)\n"
                f"⭐ <b>Баланс Stars:</b> 15 Stars (доступно отчётов: 1)\n"
                f"📅 <b>Статус аккаунта:</b> Активен\n\n"
                f"📊 <b>Ваши последние анализы:</b>\n"
                f"<i>История отчётов пуста. Отправьте файл или ссылку на канал для первого исследования.</i>"
            )

            inline_kb = build_cabinet_inline_keyboard(has_reports=False)
            await message.answer(cabinet_text, reply_markup=inline_kb, parse_mode="HTML")

        finally:
            tracker.release(user_id, current_task)

    # ----------------------------------------------------------------------
    # 3. КНОПКА: [ℹ️ Info]
    # ----------------------------------------------------------------------
    @router.message(F.text.in_({BTN_INFO, "Info", "О сервисе", "ℹ️ О сервисе"}))
    async def handle_info_button(message: types.Message):
        user_id = message.from_user.id if message.from_user else 0
        current_task = asyncio.current_task()
        if not tracker.should_process(user_id, "menu:info", current_task):
            return

        try:
            pending_store.clear(user_id)
            await close_previous_user_screen(message.bot, user_id, message.message_id)

            info_text = (
                f"ℹ️ <b>О психолингвистическом комплексе</b>\n\n"
                f"Сервис проводит фундаментальную многофакторную оценку речи:\n"
                f"• <b>Личностный профиль:</b> Big Five (OCEAN), Юнгианские типы, Тёмная триада.\n"
                f"• <b>Эмоциональный спектр:</b> RuBERT аффекты, 2D-проектор Рассела (VAD).\n"
                f"• <b>Коммуникация:</b> Трансактный анализ PAC (Эрик Берн), Карпман.\n"
                f"• <b>Речевая безопасность:</b> Аудит скрытого шантажа и токсичного контроля.\n\n"
                f"Выберите интересующий раздел ниже:"
            )

            inline_kb = build_info_inline_keyboard(locale="ru")
            await message.answer(info_text, reply_markup=inline_kb, parse_mode="HTML")

        finally:
            tracker.release(user_id, current_task)

    # ----------------------------------------------------------------------
    # 4. КНОПКА: [💬 Поддержка]
    # ----------------------------------------------------------------------
    @router.message(F.text.in_({BTN_SUPPORT, "Поддержка", "💬 Поддержка", "Report"}))
    async def handle_support_button(message: types.Message):
        user_id = message.from_user.id if message.from_user else 0
        current_task = asyncio.current_task()
        if not tracker.should_process(user_id, "menu:support", current_task):
            return

        try:
            # Активируем режим ожидания ввода сообщения в поддержку
            pending_store.set(
                user_id,
                PendingInput(kind=PendingInputKind.SUPPORT_MESSAGE, origin_chat_id=message.chat.id),
            )
            await close_previous_user_screen(message.bot, user_id, message.message_id)

            support_text = (
                f"💬 <b>Служба поддержки ({project_name})</b>\n\n"
                f"Напишите ваш вопрос или опишите проблему <b>прямо сюда в ответном сообщении</b>.\n\n"
                f"Вы можете отправить текст, скриншот или голосовое сообщение — "
                f"команда сервиса получит его и ответит вам прямо в этот диалог.\n\n"
                f"<i>Для отмены просто нажмите любую кнопку в меню внизу.</i>"
            )

            inline_kb = build_support_inline_keyboard()
            await message.answer(support_text, reply_markup=inline_kb, parse_mode="HTML")

        finally:
            tracker.release(user_id, current_task)

    # ----------------------------------------------------------------------
    # 5. ОТВЕТ АДМИНА В ЧАТЕ ПОДДЕРЖКИ (Reply в support_chat_id)
    # ----------------------------------------------------------------------
    @router.message(F.reply_to_message)
    async def handle_admin_reply(message: types.Message):
        # Если сообщение пришло из чата техподдержки и является ответом
        if support_chat_id and message.chat.id == support_chat_id:
            success, status = await deliver_support_reply_to_user(message.bot, message)
            if not success:
                await message.reply(f"⚠️ {status}")
            else:
                await message.react([types.ReactionTypeEmoji(emoji="👍")])

    # ----------------------------------------------------------------------
    # 6. ВВОД СООБЩЕНИЯ ПОЛЬЗОВАТЕЛЯ В ПОДДЕРЖКУ (Followup)
    # ----------------------------------------------------------------------
    @router.message()
    async def handle_user_followup(message: types.Message):
        user_id = message.from_user.id if message.from_user else 0

        # Если текст сообщения совпадает с кнопкой меню — игнорируем followup
        if is_main_menu_button(message.text):
            pending_store.clear(user_id)
            return

        pending = pending_store.get(user_id)
        if pending and pending.kind == PendingInputKind.SUPPORT_MESSAGE:
            pending_store.clear(user_id)
            if support_chat_id:
                sent_msg_id = await send_user_report_to_support(
                    bot=message.bot,
                    support_chat_id=support_chat_id,
                    user_message=message,
                    project_name=project_name,
                )
                if sent_msg_id:
                    await message.answer(
                        "✅ <b>Ваше сообщение передано в службу поддержки.</b>\n"
                        "Мы ответим вам прямо в этот диалог, как только прочитаем.",
                        parse_mode="HTML",
                        reply_markup=build_main_menu_keyboard(),
                    )
                    return

            await message.answer(
                "⚠️ Не удалось отправить сообщение в поддержку (чат поддержки не сконфигурирован).\n"
                "Пожалуйста, повторите попытку позже.",
                reply_markup=build_main_menu_keyboard(),
            )

    # ----------------------------------------------------------------------
    # 7. ИНЛАЙН-ОБРАБОТЧИКИ (Callbacks)
    # ----------------------------------------------------------------------
    @router.callback_query(F.data == "nav:close")
    async def handle_nav_close(query: types.CallbackQuery):
        await query.answer()
        try:
            await query.message.delete()
        except Exception:
            await query.message.edit_reply_markup(reply_markup=None)

    @router.callback_query(F.data.startswith("info:lang:"))
    async def handle_lang_switch(query: types.CallbackQuery):
        lang = query.data.split(":")[-1]
        await query.answer(f"Язык переключен на: {lang.upper()}")
        # Перерисовываем Info на новом языке
        new_text = (
            "ℹ️ <b>About Profiling Framework</b>\n\n"
            "The service conducts comprehensive psycholinguistic speech profiling."
            if lang == "en" else
            "ℹ️ <b>О психолингвистическом комплексе</b>\n\n"
            "Сервис проводит фундаментальную оценку речи на базе валидированных научных шкал."
        )
        await edit_or_send(query, new_text, reply_markup=build_info_inline_keyboard(locale=lang), parse_mode="HTML")

    return router
