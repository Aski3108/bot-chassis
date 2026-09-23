"""
Управление сервисными командами Telegram Bot API и оповещениями запуска (bot_chassis.commands).
Реализует:
- Регистрацию bot.set_my_commands (синяя кнопка 'Меню' в клиентах Telegram).
- Оповещение администраторов при старте процесса с прикреплением актуальной клавиатуры.
"""

from typing import List, Sequence
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeDefault
from loguru import logger

from .keyboards import build_main_menu_keyboard


async def setup_bot_commands(bot: Bot) -> None:
    """
    Регистрирует список команд в Telegram Bot API.
    Гарантирует, что у пользователя ВСЕГДА будет доступна синяя кнопка 'Меню' в левом нижнем углу,
    даже если нижняя клавиатура была случайно свернута или очищена история переписки.
    """
    commands = [
        BotCommand(command="start", description="🚀 Запустить бота / Главное меню"),
        BotCommand(command="menu", description="📱 Открыть главное меню"),
        BotCommand(command="help", description="ℹ️ О сервисе и методологии"),
        BotCommand(command="support", description="💬 Служба поддержки"),
    ]
    try:
        await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
        logger.info("✅ Команды бота успешно зарегистрированы в Bot API (set_my_commands).")
    except Exception as e:
        logger.warning(f"⚠️ Не удалось зарегистрировать команды через set_my_commands: {e}")


async def notify_admins_on_startup(
    bot: Bot,
    admin_ids: Sequence[int],
    startup_message: str = "🚀 Бот успешно запущен и готов к работе.",
) -> int:
    """
    Оповещает администраторов о старте процесса и принудительно отправляет
    им актуальную нижнюю Reply-клавиатуру (решение проблемы потери кнопок при рестартах).
    """
    delivered = 0
    menu_keyboard = build_main_menu_keyboard()
    for admin_id in admin_ids:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=startup_message,
                reply_markup=menu_keyboard,
            )
            delivered += 1
        except Exception as e:
            logger.debug(f"Не удалось отправить уведомление о старте админу {admin_id}: {e}")
    
    logger.info(f"📢 Уведомление о старте доставлено {delivered}/{len(admin_ids)} администраторам.")
    return delivered
