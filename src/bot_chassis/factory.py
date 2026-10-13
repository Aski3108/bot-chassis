"""Сборка полной рамы: порты, middleware и порядок роутеров."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Awaitable, Callable, Sequence

from aiogram import Bot, Dispatcher, Router
from aiogram import F
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message
from loguru import logger

from .admin.router import create_admin_router
from .config import BotChassisConfig, resolved_origin
from .contracts import extract_domain_labels
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
from .ports.donations import merge_payment_skus, resolve_donation_items
from .ports.payments import SkuVoucherConsumerPort, VoucherManagerPort, DefaultVoucherManagerAdapter
from .ports.referrals import DefaultReferralAdapter, ReferralPort
from .ports.work_gate import DefaultWorkGateAdapter, WorkGatePort
from .reviews import create_reviews_router
from .router import create_button_chassis_router
from .scheduler import BackupScheduler, ReportScheduler, register_backup_scheduler, register_report_scheduler
from .service_notify import deliver_startup_notification
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
    screens: UserScreenTracker
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
    backup_policy=None,
    reporting_policy=None,
    process_control=None,
    single_message_start: bool = False,
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
    donation_items = (
        resolve_donation_items(config, donation_catalog)
        if config.enable_payments
        else ()
    )
    payment_config = replace(
        config,
        skus=merge_payment_skus(config.skus, donation_items),
    )

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
                backup_policy=backup_policy,
                reporting_policy=reporting_policy,
                process_control=process_control,
            )
        )
    if config.enable_payments:
        dp.include_router(
            create_payments_router(config.bot_id, storage, payment_config, voucher_consumer)
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
    screens = UserScreenTracker()
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

        async def _render_start_result(message: Message, user_id: int) -> object:
            if render_start_callback is None:
                return None
            locale = locale_cache.get(user_id) or config.default_locale
            return await render_start_callback(
                StartRenderContext(
                    message=message,
                    user_id=user_id,
                    bot=message.bot,
                    locale=locale,
                )
            )

        async def _deliver_start_result(message: Message, user_id: int, rendered: object) -> None:
            locale = locale_cache.get(user_id) or config.default_locale

            async def _fallback_card() -> None:
                if config.enable_language_switch:
                    text = _DEFAULT_START_CARD_TEXT
                    markup = decorate_info_markup(
                        None,
                        MarkupContext(locale=locale, user_id=user_id),
                    )
                else:
                    text = config.welcome_text if config.welcome_text is not None else _MENU_TEXT
                    markup = None
                delivered = await message.answer(text, reply_markup=markup, parse_mode="HTML")
                screens.remember_card(user_id, delivered.chat.id, delivered.message_id)

            if isinstance(rendered, Message):
                screens.remember_card(user_id, rendered.chat.id, rendered.message_id)
                return
            if isinstance(rendered, ChassisScreen):
                markup = rendered.markup
                if config.enable_language_switch:
                    markup = decorate_info_markup(
                        markup,
                        MarkupContext(locale=locale, user_id=user_id),
                    )
                delivered = await message.answer(
                    rendered.text,
                    reply_markup=markup,
                    parse_mode=rendered.parse_mode,
                )
                screens.remember_card(user_id, delivered.chat.id, delivered.message_id)
                return
            await _fallback_card()

        async def _deliver_start_card(message: Message, user_id: int) -> None:
            rendered = await _render_start_result(message, user_id)
            await _deliver_start_result(message, user_id, rendered)

        async def _on_support_back(message: Message, user_id: int) -> None:
            await _deliver_start_card(message, user_id)

        dp.include_router(
            _create_start_router(
                config,
                locale_cache,
                domain_rows,
                resolved_pending,
                screens,
                deliver_start_card=_deliver_start_card,
                single_message_start=single_message_start,
                render_start_result=_render_start_result,
                deliver_start_result=_deliver_start_result,
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
        if review_sink is not None:
            dp.include_router(
                create_reviews_router(
                    config.bot_id,
                    reviews=storage.reviews,
                    roles=storage.roles,
                    pending=resolved_pending,
                    review_sink=review_sink,
                    origin_bot_id=resolved_origin(config),
                    project_label=project_label,
                    domain_labels=extract_domain_labels(domain_rows),
                )
            )

    if backup_policy is not None:
        register_backup_scheduler(
            dp,
            BackupScheduler(
                bot=bot,
                config=config,
                storage=storage,
                policy=backup_policy,
                origin_bot_id=resolved_origin(config),
                telegram_bot_id=int(bot.id),
            ),
        )
    if reporting_policy is not None:
        register_report_scheduler(
            dp,
            ReportScheduler(
                bot=bot,
                config=config,
                storage=storage,
                policy=reporting_policy,
                origin_bot_id=resolved_origin(config),
                telegram_bot_id=int(bot.id),
                donation_sku_codes=tuple(item.sku_code for item in donation_items),
            ),
        )

    async def _notify_startup() -> None:
        await deliver_startup_notification(bot, config)

    dp.startup.register(_notify_startup)

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
        screens=screens,
        thread_store=resolved_thread_store,
        pending_store=resolved_pending,
    )


def _create_start_router(
    config: BotChassisConfig,
    locale_cache: dict[int, str],
    domain_rows: Sequence[Sequence[str]] | None,
    pending: PendingInputStore,
    screens: UserScreenTracker,
    *,
    deliver_start_card: Callable[[Message, int], Awaitable[None]],
    single_message_start: bool = False,
    render_start_result: Callable[[Message, int], Awaitable[object]] | None = None,
    deliver_start_result: Callable[[Message, int, object], Awaitable[None]] | None = None,
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
        carrier = config.welcome_text if config.welcome_text is not None else _START_CARRIER_TEXT
        if not single_message_start:
            await message.answer(carrier, reply_markup=keyboard, parse_mode="HTML")
            await deliver_start_card(message, user_id)
            return
        rendered = None if render_start_result is None else await render_start_result(message, user_id)
        if (
            isinstance(rendered, ChassisScreen)
            and rendered.markup is None
            and not config.enable_language_switch
        ):
            await message.answer(rendered.text, reply_markup=keyboard, parse_mode=rendered.parse_mode)
            return
        if isinstance(rendered, ChassisScreen) and (
            rendered.markup is not None or config.enable_language_switch
        ):
            logger.warning("Single-message start не объединяет Inline-карточку с Reply-клавиатурой")
            await message.answer(carrier, reply_markup=keyboard, parse_mode="HTML")
            if deliver_start_result is not None:
                await deliver_start_result(message, user_id, rendered)
            return
        if isinstance(rendered, Message):
            logger.warning("Single-message start не редактирует уже отправленное сообщение кузова")
            await message.answer(carrier, reply_markup=keyboard, parse_mode="HTML")
            screens.remember_card(user_id, rendered.chat.id, rendered.message_id)
            return
        if not config.enable_language_switch:
            await message.answer(carrier, reply_markup=keyboard, parse_mode="HTML")
            return
        await message.answer(carrier, reply_markup=keyboard, parse_mode="HTML")
        if deliver_start_result is not None:
            await deliver_start_result(message, user_id, rendered)

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
