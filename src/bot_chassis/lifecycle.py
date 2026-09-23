"""Управление жизненным циклом экранов и защита интерфейса Telegram (Button Chassis).

Ключевые правила Telegram Bot API:
1. Сообщение, которое несёт нижнюю Reply-клавиатуру, НИКОГДА не удаляется!
   Иначе в мобильных клиентах Telegram нижняя полоска кнопок пропадает.
2. Карточки экранов (Кабинет, Info, Поддержка) — это отдельные инлайн-сообщения.
   Они отслеживаются через UserScreenTracker и закрываются по заданной политике:
   - CardClosePolicy.DELETE (удаление служебных экранов, чтобы чат не забивался).
   - CardClosePolicy.DROP_MARKUP (снятие кнопок, текст сохраняется для ценных отчётов).
3. edit_or_send гасит ошибку 'message is not modified' и защищает от передачи ReplyKeyboardMarkup в edit_text.
"""

from __future__ import annotations
import asyncio
from enum import Enum
from typing import Optional, Tuple
from aiogram import types, Bot
from aiogram.types import ReplyKeyboardMarkup, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from loguru import logger


class CardClosePolicy(str, Enum):
    """Политика закрытия предыдущей карточки экрана."""
    DELETE = "delete"              # Удалить сообщение с экрана (по умолчанию для меню)
    DROP_MARKUP = "drop_markup"    # Сохранить текст сообщения, но снять инлайн-кнопки (для отчётов)


class UserScreenTracker:
    """
    Экземплярный трекер активных карточек пользователя.
    Отслеживает карточки экранов отдельно от сообщений с нижней клавиатурой.
    """
    def __init__(self) -> None:
        # {user_id: (chat_id, message_id, CardClosePolicy)}
        self._cards: dict[int, tuple[int, int, CardClosePolicy]] = {}

    def remember_card(
        self,
        user_id: int,
        chat_id: int,
        message_id: int,
        policy: CardClosePolicy = CardClosePolicy.DELETE,
    ) -> None:
        """Запоминает интерактивную карточку экрана пользователя."""
        self._cards[user_id] = (chat_id, message_id, policy)

    def get_card(self, user_id: int) -> Optional[tuple[int, int, CardClosePolicy]]:
        """Возвращает (chat_id, message_id, policy) последней карточки."""
        return self._cards.get(user_id)

    def forget_card(self, user_id: int) -> None:
        """Удаляет запись о карточке из памяти трекера."""
        self._cards.pop(user_id, None)

    async def close_previous_card(
        self,
        bot: Bot,
        user_id: int,
        current_message_id: Optional[int] = None,
    ) -> None:
        """
        Закрывает предыдущую интерактивную карточку экрана пользователя
        в соответствии с её индивидуальной политикой (DELETE или DROP_MARKUP).
        Никогда не трогает сообщение, несущее нижнюю Reply-клавиатуру.
        """
        entry = self.get_card(user_id)
        if not entry:
            return
        chat_id, msg_id, policy = entry
        if current_message_id and msg_id == current_message_id:
            return

        self.forget_card(user_id)
        await close_card_screen(bot, chat_id, msg_id, policy=policy)


async def close_card_screen(
    bot: Bot,
    chat_id: int,
    message_id: int,
    policy: CardClosePolicy = CardClosePolicy.DELETE,
    timeout: float = 0.8,
) -> None:
    """Безопасное закрытие карточки экрана с таймаутом."""
    async def _close():
        if policy == CardClosePolicy.DELETE:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
                return
            except (TelegramBadRequest, TelegramForbiddenError):
                pass
            except Exception as e:
                logger.debug(f"Не удалось удалить сообщение {chat_id}:{message_id}: {e}")

        # Снимаем инлайн-кнопки
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
        logger.debug(f"Таймаут закрытия карточки {chat_id}:{message_id}")


async def edit_or_send(
    event: types.Message | types.CallbackQuery,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup | ReplyKeyboardMarkup] = None,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = True,
) -> types.Message:
    """
    Универсальный метод отрисовки UI:
    - Если передан ReplyKeyboardMarkup — Telegram запрещает edit_message_text,
      поэтому отправляется новое сообщение через answer().
    - Если передан InlineKeyboardMarkup (или None) — редактирует текущее сообщение
      с перехватом ошибки 'message is not modified'.
    """
    is_reply_kb = isinstance(reply_markup, ReplyKeyboardMarkup)

    if not is_reply_kb:
        if isinstance(event, types.CallbackQuery):
            if event.message:
                try:
                    return await event.message.edit_text(
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                        disable_web_page_preview=disable_web_page_preview,
                    )
                except TelegramBadRequest as e:
                    if "message is not modified" in str(e).lower():
                        return event.message
                except Exception:
                    pass
            # Fallback для CallbackQuery
            return await event.bot.send_message(
                chat_id=event.from_user.id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
            )

        if isinstance(event, types.Message):
            # Редактировать можно ТОЛЬКО сообщение самого бота (например, карточку).
            # Входящее сообщение от пользователя Telegram API редактировать запрещает (400 Bad Request).
            if event.from_user and event.from_user.is_bot:
                try:
                    return await event.edit_text(
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                        disable_web_page_preview=disable_web_page_preview,
                    )
                except TelegramBadRequest as e:
                    if "message is not modified" in str(e).lower():
                        return event
                except Exception:
                    pass
            return await event.answer(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
            )

    # Отправка нового сообщения
    if isinstance(event, types.CallbackQuery):
        return await event.bot.send_message(
            chat_id=event.from_user.id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
        )
    return await event.answer(
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
        disable_web_page_preview=disable_web_page_preview,
    )
