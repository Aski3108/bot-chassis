"""Сборка полной рамы: порты, middleware и порядок роутеров."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Sequence

from aiogram import Bot, Dispatcher, Router
from aiogram import F
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from .admin.router import create_admin_router
from .config import BotChassisConfig, resolved_origin
from .dispatcher import ActiveTaskTracker
from .followup import PendingInputStore
from .keyboards import build_main_menu_keyboard
from .lifecycle import UserScreenTracker
from .localization import (
    ChassisScreen,
    InitialLocalePolicy,
    MarkupContext,
    create_localization_router,
    decorate_info_markup,
)
from .middleware import register_chassis_middlewares
from .payments.router import create_payments_router
from .ports.access import AccessPort, DefaultAccessAdapter
from .ports.admin_extra import ExtraAdminActions
from .ports.cabinet import CabinetSlotsProviderPort, DefaultCabinetSlotsAdapter, build_cabinet_renderer
from .ports.donations import resolve_donation_items
from .ports.payments import SkuVoucherConsumerPort, VoucherManagerPort, DefaultVoucherManagerAdapter
from .ports.referrals import DefaultReferralAdapter, ReferralPort
from .ports.work_gate import DefaultWorkGateAdapter, WorkGatePort
from .router import create_button_chassis_router
from .storage import Storage, create_storage
from .storage.sqlite_support_thread_store import SqliteSupportThreadStore
from .support_bridge import SupportThreadStore
from .user_lifecycle import register_membership_handler, warn_if_my_chat_member_missing

_MENU_TEXT = "📱 <b>Главное меню</b>\n\nИспользуйте кнопки внизу экрана:"
_START_CARRIER_TEXT = "Главное меню"
_DEFAULT_START_CARD_TEXT = "📱 <b>Главное меню / Main menu</b>"


@dataclass(frozen=True, slots=True)
class StartRenderContext:
    """Контекст единого стартового экрана кузова."""

    message: Message
    user_id: int
    bot: Bot | None
    locale: str


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
    thread_store: object | None = None
    pending_store: PendingInputStore | None = None


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
    project_label: str = "Сервис",
    render_info_callback=None,
    extra_admin_actions: ExtraAdminActions | None = None,
    thread_store=None,
    extra_support_inline: Sequence[Sequence[tuple[str, str]]] | None = None,
    pending_store: PendingInputStore | None = None,
    before_chassis_menu_action=None,
    extra_user_dossier_lines=None,
    extra_user_dossier_rows=None,
    render_start_callback: Callable[[StartRenderContext], Awaitable[object]] | None = None,
    on_locale_changed=None,
    initial_locale_policy: InitialLocalePolicy | None = None,
    initial_locale_resolver: Callable[[str | None], str] | None = None,
    bot_display_name_provider=None,
    allowed_updates: Sequence[str] | None = None,
    donation_catalog=None,
    donation_hint: str | None = None,
    review_sink=None,
) -> CompleteChassis:
    if storage is None:
        storage = await create_storage(config)
    if dp is None:
        dp = Dispatcher()
    storage.bot_statuses.bind_process(resolved_origin(config), int(bot.id))
    warn_if_my_chat_member_missing(allowed_updates)
    register_membership_handler(dp, storage, config)

    if config.enable_buttons and domain_router is not None and _router_handles_start(domain_router):
        raise ValueError(
            "domain_router не должен регистрировать /start: единый /start принадлежит bot_chassis"
        )

    locale_cache = register_chassis_middlewares(
        dp,
        config=config,
        storage=storage,
        locale_policy=initial_locale_policy,
        locale_resolver=initial_locale_resolver,
        bot_display_name_provider=bot_display_name_provider,
    )
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

    resolved_pending = pending_store or PendingInputStore()
    donation_items = resolve_donation_items(config, donation_catalog)

    if config.enable_admin:
        dp.include_router(
            create_admin_router(
                config.bot_id,
                storage,
                config,
                extra_actions=extra_admin_actions,
                extra_user_dossier_lines=extra_user_dossier_lines,
                extra_user_dossier_rows=extra_user_dossier_rows,
                bot_display_name_provider=bot_display_name_provider,
                pending_store=resolved_pending,
            )
        )
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
            on_locale_changed=on_locale_changed,
        )
    )
    if domain_router is not None:
        dp.include_router(domain_router)
    resolved_thread_store = thread_store
    if config.enable_buttons:
        if resolved_thread_store is None:
            if config.db_path and config.db_path != ":memory:":
                resolved_thread_store = SqliteSupportThreadStore(
                    config.db_path,
                    tenant_bot_id=config.bot_id,
                    origin_bot_id=resolved_origin(config),
                    origin_telegram_bot_id=int(bot.id),
                )
            else:
                resolved_thread_store = SupportThreadStore()
        resolved_support_inline = extra_support_inline or ()
        screens = UserScreenTracker()

        async def _on_support_back(message: Message, user_id: int) -> None:
            locale = locale_cache.get(user_id) or config.default_locale
            if render_start_callback is None:
                if not config.enable_language_switch:
                    return
                markup = decorate_info_markup(
                    None,
                    MarkupContext(locale=locale, user_id=user_id),
                )
                delivered = await message.answer(
                    _DEFAULT_START_CARD_TEXT,
                    reply_markup=markup,
                    parse_mode="HTML",
                )
                screens.remember_card(user_id, delivered.chat.id, delivered.message_id)
                return
            rendered = await render_start_callback(
                StartRenderContext(
                    message=message,
                    user_id=user_id,
                    bot=message.bot,
                    locale=locale,
                )
            )
            if isinstance(rendered, Message):
                screens.remember_card(user_id, rendered.chat.id, rendered.message_id)
                return
            if not isinstance(rendered, ChassisScreen):
                return
            markup = rendered.markup
            if config.enable_language_switch:
                markup = decorate_info_markup(markup, MarkupContext(locale=locale, user_id=user_id))
            delivered = await message.answer(
                rendered.text,
                reply_markup=markup,
                parse_mode=rendered.parse_mode,
            )
            screens.remember_card(user_id, delivered.chat.id, delivered.message_id)

        dp.include_router(
            _create_start_router(
                config,
                locale_cache,
                domain_rows,
                resolved_pending,
                screens,
                render_start_callback=render_start_callback,
                language_switch_enabled=config.enable_language_switch,
            )
        )
        dp.include_router(
            create_button_chassis_router(
                support_chat_id=config.support_chat_id,
                domain_rows=domain_rows,
                render_cabinet_callback=build_cabinet_renderer(cabinet, config.bot_id),
                get_user_locale=lambda uid: locale_cache.get(uid) or config.default_locale,
                default_locale=config.default_locale,
                task_tracker=ActiveTaskTracker(),
                pending_store=resolved_pending,
                screen_tracker=screens,
                thread_store=resolved_thread_store,
                project_label=project_label,
                render_info_callback=render_info_callback,
                extra_support_inline=resolved_support_inline,
                before_chassis_menu_action=before_chassis_menu_action,
                language_switch_enabled=config.enable_language_switch,
                support_thread_id=config.support_thread_id,
                donation_items=donation_items,
                donation_hint=donation_hint,
                review_enabled=review_sink is not None,
                on_support_back=_on_support_back,
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
        thread_store=resolved_thread_store,
        pending_store=resolved_pending,
    )


def _create_start_router(
    config: BotChassisConfig,
    locale_cache: dict[int, str],
    domain_rows: Sequence[Sequence[str]] | None,
    pending: PendingInputStore,
    screens: UserScreenTracker,
    render_start_callback: Callable[[StartRenderContext], Awaitable[object]] | None = None,
    language_switch_enabled: bool = False,
) -> Router:
    router = Router(name="chassis_start")

    @router.message(
        Command("start", ignore_mention=True),
        F.chat.type == ChatType.PRIVATE,
    )
    async def handle_start(message: Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        pending.clear(user_id)
        if message.bot is not None:
            await screens.close_previous_card(message.bot, user_id)
        locale = locale_cache.get(user_id) or config.default_locale
        keyboard = build_main_menu_keyboard(domain_rows=domain_rows, locale=locale)
        if render_start_callback is None:
            if not language_switch_enabled:
                welcome = config.welcome_text if config.welcome_text is not None else _MENU_TEXT
                await message.answer(welcome, reply_markup=keyboard, parse_mode="HTML")
                return
            carrier = config.welcome_text if config.welcome_text is not None else _START_CARRIER_TEXT
            await message.answer(carrier, reply_markup=keyboard, parse_mode="HTML")
            markup = decorate_info_markup(
                None,
                MarkupContext(locale=locale, user_id=user_id),
            )
            delivered = await message.answer(
                _DEFAULT_START_CARD_TEXT,
                reply_markup=markup,
                parse_mode="HTML",
            )
            screens.remember_card(user_id, delivered.chat.id, delivered.message_id)
            return
        carrier = config.welcome_text if config.welcome_text is not None else _START_CARRIER_TEXT
        await message.answer(carrier, reply_markup=keyboard, parse_mode="HTML")
        rendered = await render_start_callback(
            StartRenderContext(
                message=message,
                user_id=user_id,
                bot=message.bot,
                locale=locale,
            )
        )
        if isinstance(rendered, Message):
            screens.remember_card(user_id, rendered.chat.id, rendered.message_id)
            return
        if not isinstance(rendered, ChassisScreen):
            return
        markup = rendered.markup
        if language_switch_enabled:
            markup = decorate_info_markup(markup, MarkupContext(locale=locale, user_id=user_id))
        delivered = await message.answer(
            rendered.text,
            reply_markup=markup,
            parse_mode=rendered.parse_mode,
        )
        screens.remember_card(user_id, delivered.chat.id, delivered.message_id)

    return router


def _router_handles_start(router: Router) -> bool:
    """Проверяет конфликт владения системной командой /start."""

    for handler in router.message.handlers:
        for filter_object in handler.filters:
            command_filter = filter_object.callback
            if not isinstance(command_filter, Command):
                continue
            for command in command_filter.commands:
                command_name = getattr(command, "command", command)
                if isinstance(command_name, str) and command_name.lstrip("/").casefold() == "start":
                    return True
    return False
