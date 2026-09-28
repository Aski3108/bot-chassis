"""Сервисные мидлвари Update: ошибка → троттлинг → активность."""

from aiogram import Dispatcher

from ..config import BotChassisConfig
from ..localization import InitialLocalePolicy
from ..storage import Storage
from .error_monitor import ErrorAlertMiddleware
from .throttling import ThrottlingMiddleware
from .user_activity import UserActivityMiddleware


def register_chassis_middlewares(
    dp: Dispatcher,
    *,
    config: BotChassisConfig,
    storage: Storage,
    locale_cache: dict[int, str] | None = None,
    locale_policy: InitialLocalePolicy | None = None,
    locale_resolver=None,
    bot_display_name_provider=None,
) -> dict[int, str]:
    """Самый внешний — ErrorAlert. Первый зарегистрированный outer видит Update раньше."""
    cache = {} if locale_cache is None else locale_cache
    dp.update.outer_middleware(ErrorAlertMiddleware(config))
    dp.update.outer_middleware(ThrottlingMiddleware(config.bot_id, enabled=config.enable_throttling))
    dp.update.outer_middleware(
        UserActivityMiddleware(
            config.bot_id,
            storage,
            config,
            locale_cache=cache,
            locale_policy=locale_policy,
            locale_resolver=locale_resolver,
            bot_display_name_provider=bot_display_name_provider,
        )
    )
    return cache


__all__ = [
    "ErrorAlertMiddleware",
    "ThrottlingMiddleware",
    "UserActivityMiddleware",
    "register_chassis_middlewares",
]
