"""Сборка полной рамы: порты, middleware и порядок роутеров."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message

from .admin.router import create_admin_router
from .config import BotChassisConfig
from .dispatcher import ActiveTaskTracker
from .followup import PendingInputStore
from .keyboards import build_main_menu_keyboard
from .lifecycle import UserScreenTracker
from .localization import create_localization_router
from .middleware import register_chassis_middlewares
from .payments.router import create_payments_router
from .ports.access import AccessPort, DefaultAccessAdapter
from .ports.cabinet import CabinetSlotsProviderPort, DefaultCabinetSlotsAdapter, build_cabinet_renderer
from .ports.payments import SkuVoucherConsumerPort, VoucherManagerPort, DefaultVoucherManagerAdapter
from .ports.referrals import DefaultReferralAdapter, ReferralPort
from .ports.work_gate import DefaultWorkGateAdapter, WorkGatePort
from .router import create_button_chassis_router
from .storage import Storage, create_storage
from .support_bridge import SupportThreadStore

_MENU_TEXT = "📱 <b>Главное меню</b>\n\nИспользуйте кнопки внизу экрана:"


@dataclass(slots=True)
class CompleteChassis:
    dp: Dispatcher
    bot: Bot
    config: BotChassisConfig
    storage: Storage
    work_gate: WorkGatePort
    access: AccessPort
    vouchers: VoucherManagerPort
    referrals: ReferralPort
    cabinet: CabinetSlotsProviderPort
    locale_cache: dict[int, str]


async def create_complete_chassis(
    bot: Bot,
    config: BotChassisConfig,
    dp: Dispatcher | None = None,
    storage: Storage | None = None,
    voucher_consumer: SkuVoucherConsumerPort | None = None,
    cabinet_provider: CabinetSlotsProviderPort | None = None,
    domain_router: Router | None = None,
    domain_rows: Sequence[Sequence[str]] | None = None,
    *,
    vouchers_provider: VoucherManagerPort | None = None,
    referrals_provider: ReferralPort | None = None,
) -> CompleteChassis:
    if storage is None:
        storage = await create_storage(config)
    if dp is None:
        dp = Dispatcher()

    locale_cache = register_chassis_middlewares(dp, config=config, storage=storage)
    work_gate = DefaultWorkGateAdapter(storage.bot_settings, storage.users)
    access = DefaultAccessAdapter(storage.subscriptions)
    vouchers = vouchers_provider or DefaultVoucherManagerAdapter(storage.transactions)
    referrals = referrals_provider or DefaultReferralAdapter(storage.referrals)
    cabinet = cabinet_provider or DefaultCabinetSlotsAdapter(
        storage.subscriptions,
        storage.transactions,
        users_repo=storage.users,
        referrals_repo=storage.referrals if config.enable_referrals else None,
        enable_payments=config.enable_payments,
        enable_referrals=config.enable_referrals,
    )

    if config.enable_admin:
        dp.include_router(create_admin_router(config.bot_id, storage, config))
    if config.enable_payments:
        dp.include_router(
            create_payments_router(config.bot_id, storage, config, voucher_consumer)
        )
    dp.include_router(
        create_localization_router(
            config.bot_id,
            storage,
            enabled=config.enable_language_switch,
            locale_cache=locale_cache,
            domain_rows=domain_rows,
        )
    )
    if domain_router is not None:
        dp.include_router(domain_router)
    if config.enable_buttons:
        pending = PendingInputStore()
        screens = UserScreenTracker()
        dp.include_router(
            _create_start_router(config, locale_cache, domain_rows, pending, screens)
        )
        dp.include_router(
            create_button_chassis_router(
                support_chat_id=config.support_chat_id,
                domain_rows=domain_rows,
                render_cabinet_callback=build_cabinet_renderer(cabinet, config.bot_id),
                get_user_locale=lambda uid: locale_cache.get(uid) or config.default_locale,
                default_locale=config.default_locale,
                task_tracker=ActiveTaskTracker(),
                pending_store=pending,
                screen_tracker=screens,
                thread_store=SupportThreadStore(),
            )
        )

    return CompleteChassis(
        dp=dp,
        bot=bot,
        config=config,
        storage=storage,
        work_gate=work_gate,
        access=access,
        vouchers=vouchers,
        referrals=referrals,
        cabinet=cabinet,
        locale_cache=locale_cache,
    )


def _create_start_router(
    config: BotChassisConfig,
    locale_cache: dict[int, str],
    domain_rows: Sequence[Sequence[str]] | None,
    pending: PendingInputStore,
    screens: UserScreenTracker,
) -> Router:
    router = Router(name="chassis_start")

    @router.message(Command("start", ignore_mention=True))
    async def handle_start(message: Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        pending.clear(user_id)
        if message.bot is not None:
            await screens.close_previous_card(message.bot, user_id)
        locale = locale_cache.get(user_id) or config.default_locale
        welcome = config.welcome_text if config.welcome_text is not None else _MENU_TEXT
        await message.answer(
            welcome,
            reply_markup=build_main_menu_keyboard(domain_rows=domain_rows, locale=locale),
            parse_mode="HTML",
        )

    return router
