"""
Эталонный запуск полной рамы Bot Chassis.
Не расширяет examples/run_example.py: тот файл остаётся примером только кнопок.

Кузов здесь — маленький роутер /ping и кнопка «Ваши задачи».
Он читает порты с объекта CompleteChassis, рама сама кузов не вызывает.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Mapping

from aiogram import Bot, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from bot_chassis.commands import register_button_chassis_startup
from bot_chassis.config import BotChassisConfig, SkuItem
from bot_chassis.factory import CompleteChassis, create_complete_chassis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_complete_chassis")

DOMAIN_ROWS = (("📊 Ваши задачи",),)


class _Body:
    chassis: CompleteChassis | None = None


def build_config(environ: Mapping[str, str]) -> BotChassisConfig:
    superadmins = _ids(environ.get("CHASSIS_SUPERADMIN_IDS") or environ.get("ADMIN_IDS"))
    return BotChassisConfig(
        bot_id=environ.get("CHASSIS_BOT_ID", "demo").strip() or "demo",
        db_path=environ.get("CHASSIS_DB_PATH", "bot_chassis.db").strip() or "bot_chassis.db",
        superadmin_ids=superadmins,
        skus=(SkuItem(sku_code="demo", title="Демо", description="Пробный товар", stars_price=1),),
        support_chat_id=_int_or_none(environ.get("SUPPORT_CHAT_ID")),
        audit_chat_id=_int_or_none(environ.get("CHASSIS_AUDIT_CHAT_ID") or environ.get("AUDIT_CHAT_ID")),
        enable_language_switch=_flag(environ.get("CHASSIS_ENABLE_LANGUAGE_SWITCH")),
        enable_referrals=_flag(environ.get("CHASSIS_ENABLE_REFERRALS")),
    )


def create_demo_domain(body: _Body) -> Router:
    router = Router(name="domain")

    @router.message(Command("ping"))
    async def handle_ping(message: Message) -> None:
        await _answer_if_open(body, message, "pong")

    @router.message(F.text == "📊 Ваши задачи")
    async def handle_tasks(message: Message) -> None:
        await _answer_if_open(body, message, "Задач пока нет. Это демо кузова.")

    return router


async def _answer_if_open(body: _Body, message: Message, text: str) -> None:
    chassis = body.chassis
    user = message.from_user
    if chassis is None or user is None:
        return
    allowed, reason = await chassis.work_gate.can_accept_work(chassis.config.bot_id, user.id)
    if not allowed:
        if reason:
            await message.answer(reason)
        return
    await message.answer(text)


def _ids(raw: str | None) -> tuple[int, ...]:
    if not raw:
        return ()
    values = []
    for part in raw.split(","):
        number = _int_or_none(part)
        if number is not None:
            values.append(number)
    return tuple(values)


def _int_or_none(raw: str | None) -> int | None:
    if raw is None:
        return None
    text = raw.strip()
    if text.lstrip("-").isdigit():
        return int(text)
    return None


def _flag(raw: str | None) -> bool:
    return bool(raw) and raw.strip().lower() in {"1", "true", "yes", "on"}


async def main() -> None:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        logger.error("BOT_TOKEN не задан. Скопируйте examples/.env.example и задайте переменную окружения.")
        return

    body = _Body()
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        chassis = await create_complete_chassis(
            bot,
            build_config(os.environ),
            domain_router=create_demo_domain(body),
            domain_rows=DOMAIN_ROWS,
        )
        body.chassis = chassis
        register_button_chassis_startup(chassis.dp, bot)
        logger.info("Полная рама запущена. Остановка: Ctrl+C.")
        await chassis.dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
