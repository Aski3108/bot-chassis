"""Слоты личного кабинета (§3.2) и клей к render_cabinet_callback."""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Protocol, Sequence

from aiogram import Bot, types

from ..storage.repositories.referrals import ReferralsRepository
from ..storage.repositories.subscriptions import SubscriptionsRepository
from ..storage.repositories.transactions import TransactionsRepository
from ..storage.repositories.users import UsersRepository


@dataclass(slots=True, frozen=True)
class CabinetSlot:
    slot_id: str
    title: str
    content: str
    buttons: tuple = ()


class CabinetSlotsProviderPort(Protocol):
    async def get_cabinet_slots(self, bot_id: str, user_id: int) -> Sequence[CabinetSlot]: ...


class DefaultCabinetSlotsAdapter(CabinetSlotsProviderPort):
    def __init__(
        self,
        subs_repo: SubscriptionsRepository,
        tx_repo: TransactionsRepository,
        users_repo: UsersRepository | None = None,
        referrals_repo: ReferralsRepository | None = None,
        bot_username: str = "",
        enable_payments: bool = True,
        enable_referrals: bool = False,
    ):
        self._subs = subs_repo
        self._tx = tx_repo
        self._users = users_repo
        self._referrals = referrals_repo
        self._bot_username = bot_username
        self._enable_payments = enable_payments
        self._enable_referrals = enable_referrals

    async def get_cabinet_slots(self, bot_id: str, user_id: int) -> Sequence[CabinetSlot]:
        slots: list[CabinetSlot] = []
        if self._users:
            user = await self._users.get_user(bot_id, user_id)
            if user:
                username = f"@{user.username}" if user.username else "—"
                registered = user.created_at[:10] if user.created_at else "—"
                slots.append(
                    CabinetSlot(
                        "profile",
                        "Профиль",
                        f"ID: {user.user_id} | {username} | Зарегистрирован: {registered}",
                    )
                )
        sub = await self._subs.get_active_subscription(bot_id, user_id)
        if sub and sub.is_lifetime:
            access_text = "🎁 Доступ: VIP (Бессрочно)"
        elif sub and sub.expires_at:
            access_text = f"🎁 Доступ: VIP (до {sub.expires_at[:10]})"
        else:
            access_text = "Доступ: Базовый"
        slots.append(CabinetSlot("access", "Доступ", access_text))
        if self._enable_payments:
            vouchers = await self._tx.get_active_vouchers(bot_id, user_id)
            slots.append(CabinetSlot("vouchers", "Талоны", f"🎟 Доступно талонов: {len(vouchers)}"))
        if self._enable_referrals and self._referrals:
            refs = await self._referrals.get_referrals_count(bot_id, user_id)
            if self._bot_username:
                link = f"https://t.me/{self._bot_username}?start=ref_{user_id}"
            else:
                link = f"ref_{user_id}"
            slots.append(
                CabinetSlot(
                    "referrals",
                    "Рефералы",
                    f"👥 Приглашено друзей: {refs} | Ваша ссылка: {link}",
                )
            )
        return slots


def build_cabinet_renderer(
    adapter: CabinetSlotsProviderPort,
    bot_id: str,
) -> Callable[[types.Message, int, Bot], Awaitable[Optional[types.Message]]]:
    async def _render(message: types.Message, user_id: int, bot: Bot) -> Optional[types.Message]:
        del bot
        slots = await adapter.get_cabinet_slots(bot_id, user_id)
        lines = ["👤 <b>Личный кабинет</b>"]
        for slot in slots:
            lines.append(f"<b>{html.escape(slot.title)}</b>\n{html.escape(slot.content)}")
        text = "\n\n".join(lines)
        return await message.answer(text, parse_mode="HTML")

    return _render
