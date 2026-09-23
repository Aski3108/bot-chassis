"""
Управление жизненным циклом экранов и защита интерфейса Telegram (bot_chassis.lifecycle).
Реализует:
- Бесшовное обновление экранов (edit_or_send) с защитой от 'message is not modified'.
- Закрытие и очистку устаревших инлайн-сообщений (защита от 'кладбища экранов').
- Отслеживание последнего активного экрана пользователя.
"""

import asyncio
from typing import Optional, Dict, Tuple
from aiogram import types, Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from loguru import logger

# Хранилище последних отправленных экранов: {user_id: (chat_id, message_id)}
_USER_LAST_SCREEN: Dict[int, Tuple[int, int]] = {}


def remember_user_screen(user_id: int, chat_id: int, message_id: int) -> None:
    """Запоминает последнее интерактивное сообщение пользователя."""
    _USER_LAST_SCREEN[user_id] = (chat_id, message_id)


def get_user_last_screen(user_id: int) -> Optional[Tuple[int, int]]:
    """Возвращает (chat_id, message_id) последнего экрана пользователя."""
    return _USER_LAST_SCREEN.get(user_id)


def forget_user_screen(user_id: int) -> None:
    """Удаляет запись о последнем экране."""
    _USER_LAST_SCREEN.pop(user_id, None)


async def close_screen(
    bot: Bot,
    chat_id: int,
    message_id: int,
    timeout: float = 0.8,
) -> None:
    """
    Безопасно закрывает экран: сначала пытается удалить сообщение,
    а при невозможности (например, сообщение старше 48 часов) — убирает инлайн-кнопки.
    Выполняется с таймаутом, чтобы сетевые задержки Telegram не тормозили бота.
    """
    async def _close():
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
            return
        except (TelegramBadRequest, TelegramForbiddenError):
            pass
        except Exception as e:
            logger.debug(f"Не удалось удалить сообщение {chat_id}:{message_id}: {e}")

        try:
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=None,
            )
        except Exception:
            pass

    try:
        await asyncio.wait_for(_close(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.debug(f"Таймаут закрытия экрана {chat_id}:{message_id}")


async def close_previous_user_screen(
    bot: Bot,
    user_id: int,
    current_message_id: Optional[int] = None,
) -> None:
    """
    Закрывает предыдущий активный экран пользователя, если он отличается от текущего.
    Предотвращает накопление устаревших кликабельных меню в переписке.
    """
    last = get_user_last_screen(user_id)
    if not last:
        return
    prev_chat_id, prev_msg_id = last
    if current_message_id and prev_msg_id == current_message_id:
        return

    # Запускаем закрытие в фоне с гарантией не блокировать основной поток
    asyncio.create_task(close_screen(bot, prev_chat_id, prev_msg_id))
    forget_user_screen(user_id)


async def edit_or_send(
    event: types.Message | types.CallbackQuery,
    text: str,
    reply_markup: Optional[types.InlineKeyboardMarkup | types.ReplyKeyboardMarkup] = None,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = True,
) -> types.Message:
    """
    Универсальный бесшовный метод отрисовки UI.
    
    1. Если вызван из CallbackQuery или Message с возможностью редактирования:
       - Пытается вызвать edit_text.
       - При ошибке TelegramBadRequest ('message is not modified') — корректно возвращает текущее сообщение без падения.
       - При невозможности редактирования (например, смена текста медиа или устаревшее сообщение) — отправляет новое.
    2. Запоминает ID отправленного сообщения для последующего контролируемого закрытия.
    """
    bot = event.bot
    user_id = event.from_user.id if event.from_user else 0
    target_msg = event.message if isinstance(event, types.CallbackQuery) else event

    # Попытка редактирования (только для инлайн-клавиатур или без клавиатуры)
    # Telegram API запрещает передавать ReplyKeyboardMarkup в edit_message_text!
    can_edit = (
        isinstance(event, types.CallbackQuery) or
        (hasattr(target_msg, "edit_text") and not isinstance(reply_markup, types.ReplyKeyboardMarkup))
    )

    if can_edit and hasattr(target_msg, "edit_text"):
        try:
            res = await target_msg.edit_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
            )
            if user_id and isinstance(reply_markup, types.InlineKeyboardMarkup):
                remember_user_screen(user_id, res.chat.id, res.message_id)
            return res
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                return target_msg
            logger.debug(f"edit_text не удался ({e}), переход к отправке нового сообщения.")
        except Exception as e:
            logger.debug(f"Неожиданная ошибка edit_text: {e}")

    # Отправка нового сообщения
    chat_id = target_msg.chat.id if hasattr(target_msg, "chat") else user_id
    res = await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
        disable_web_page_preview=disable_web_page_preview,
    )

    if user_id:
        if isinstance(reply_markup, types.InlineKeyboardMarkup):
            remember_user_screen(user_id, res.chat.id, res.message_id)
        else:
            forget_user_screen(user_id)

    return res
