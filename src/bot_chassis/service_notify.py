"""Куда уходит служебное сообщение: чат и, при необходимости, тема форума."""

from __future__ import annotations

from dataclasses import dataclass

from .config import BotChassisConfig


@dataclass(frozen=True, slots=True)
class ServiceDestination:
    chat_id: int
    thread_id: int | None


def thread_kwargs(thread_id: int | None) -> dict[str, int]:
    """Не передавать message_thread_id, пока тема не задана."""
    if thread_id is None:
        return {}
    return {"message_thread_id": thread_id}


def resolve_service_destination(config: BotChassisConfig, channel: str) -> ServiceDestination | None:
    """support — чат поддержки; audit — только audit-чат; ops/events/payment — audit либо старый support."""
    if channel == "support":
        chat_id = config.support_chat_id
        thread_id = config.support_thread_id
    elif channel == "audit":
        chat_id = config.audit_chat_id
        thread_id = config.audit_thread_id
    elif channel == "payment":
        if config.audit_chat_id is not None:
            chat_id = config.audit_chat_id
            thread_id = config.audit_thread_id
        else:
            chat_id = config.support_chat_id
            thread_id = None
    elif channel == "ops":
        if config.audit_chat_id is not None:
            chat_id = config.audit_chat_id
            thread_id = config.ops_thread_id
        else:
            chat_id = config.support_chat_id
            thread_id = None
    elif channel == "events":
        if config.audit_chat_id is not None:
            chat_id = config.audit_chat_id
            thread_id = config.events_thread_id
        else:
            chat_id = config.support_chat_id
            thread_id = None
    else:
        raise ValueError(f"unknown service channel: {channel}")
    if chat_id is None:
        return None
    return ServiceDestination(chat_id=chat_id, thread_id=thread_id)


async def deliver_service_message(bot, destination: ServiceDestination | None, text: str, **kwargs):
    if destination is None or bot is None:
        return None
    return await bot.send_message(
        destination.chat_id,
        text,
        **thread_kwargs(destination.thread_id),
        **kwargs,
    )
