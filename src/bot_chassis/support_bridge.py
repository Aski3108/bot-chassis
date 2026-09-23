"""
Двусторонний мост технической поддержки Chat Listener Bridge (bot_chassis.support_bridge).
Позволяет пользователю общаться со службой поддержки прямо внутри бота без раскрытия
личных аккаунтов администраторов:
1. Сообщение пользователя пересылается в закрытый админский чат.
2. Администратор нажимает Reply в Telegram-клиенте на это сообщение.
3. Бот копирует ответ (включая голосовые, видео, фото, документы) пользователю в личку.
"""

from typing import Optional, Dict
from html import escape
from aiogram import Bot, types
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from loguru import logger

# Хранилище связей сообщений: {admin_message_id: user_id}
_SUPPORT_THREADS: Dict[int, int] = {}


def register_support_thread(admin_msg_id: int, user_id: int) -> None:
    """Связывает ID пересланного сообщения у админа с ID пользователя."""
    _SUPPORT_THREADS[admin_msg_id] = user_id


def resolve_user_by_admin_reply(reply_to_message_id: int) -> Optional[int]:
    """Находит ID пользователя по ID сообщения, на которое отвечает админ."""
    return _SUPPORT_THREADS.get(reply_to_message_id)


async def send_user_report_to_support(
    bot: Bot,
    support_chat_id: int,
    user_message: types.Message,
    project_name: str = "Profiling Framework",
) -> Optional[int]:
    """
    Доставляет обращение пользователя в чат техподдержки:
    1. Отправляет карточку с метаданными пользователя.
    2. Копирует исходное сообщение (текст/медиа/голос).
    3. Регистрирует связь для последующего ответа через Reply.
    """
    user = user_message.from_user
    user_id = user.id if user else 0
    username_str = f"@{user.username}" if (user and user.username) else "нет username"
    full_name = escape(user.full_name if user else "Пользователь")

    header_text = (
        f"📩 <b>Новое обращение в поддержку</b>\n"
        f"<b>Проект:</b> {escape(project_name)}\n"
        f"<b>От:</b> {full_name} ({username_str})\n"
        f"<b>User ID:</b> <code>{user_id}</code>\n"
        f"<i>Для ответа просто нажмите 'Ответить' (Reply) на сообщение ниже.</i>"
    )

    try:
        # Отправляем карточку
        await bot.send_message(
            chat_id=support_chat_id,
            text=header_text,
            parse_mode="HTML",
        )
        # Копируем оригинальное сообщение пользователя
        copied_msg = await bot.copy_message(
            chat_id=support_chat_id,
            from_chat_id=user_message.chat.id,
            message_id=user_message.message_id,
        )
        
        # Регистрируем в маппинге
        register_support_thread(copied_msg.message_id, user_id)
        logger.info(f"📨 Обращение от {user_id} успешно доставлено в чат поддержки {support_chat_id}.")
        return copied_msg.message_id
    except Exception as e:
        logger.error(f"❌ Не удалось доставить обращение в поддержку: {e}")
        return None


async def deliver_support_reply_to_user(
    bot: Bot,
    admin_reply_message: types.Message,
    support_header: str = "💬 <b>Ответ службы поддержки:</b>",
) -> tuple[bool, str]:
    """
    Доставляет ответ администратора пользователю в личные сообщения.
    Возвращает (успех: bool, статус_текст: str).
    """
    replied_to = admin_reply_message.reply_to_message
    if not replied_to:
        return False, "Не найдено исходное сообщение для ответа."

    target_user_id = resolve_user_by_admin_reply(replied_to.message_id)
    if not target_user_id:
        return False, "Не удалось определить адресата (устаревшая или неизвестная сессия)."

    try:
        # 1. Отправляем шапку
        await bot.send_message(
            chat_id=target_user_id,
            text=support_header,
            parse_mode="HTML",
        )
        # 2. Копируем сам ответ админа (текст, голос, скриншот и т.д.)
        await bot.copy_message(
            chat_id=target_user_id,
            from_chat_id=admin_reply_message.chat.id,
            message_id=admin_reply_message.message_id,
        )
        logger.info(f"📬 Ответ поддержки успешно доставлен пользователю {target_user_id}.")
        return True, "Ответ успешно доставлен пользователю."
    except TelegramForbiddenError:
        logger.warning(f"⚠️ Пользователь {target_user_id} заблокировал бота. Доставка ответа невозможна.")
        return False, "Пользователь заблокировал бота; сообщение не доставлено."
    except Exception as e:
        logger.error(f"❌ Ошибка доставки ответа поддержки пользователю {target_user_id}: {e}")
        return False, f"Ошибка отправки: {e}"
