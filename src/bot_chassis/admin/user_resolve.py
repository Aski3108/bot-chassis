"""Один разбор цели команд: числовой ID или @username."""

from __future__ import annotations

import html
from dataclasses import dataclass

from ..storage import Storage
from ..storage.repositories.users import UserRecord, normalize_username


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    kind: str
    user_id: int | None = None
    matches: tuple[UserRecord, ...] = ()


async def resolve_user_token(storage: Storage, bot_id: str, token: str) -> ResolvedTarget:
    text = token.strip()
    if not text:
        return ResolvedTarget("invalid")
    if text.isdigit():
        return ResolvedTarget("id", int(text))
    name = normalize_username(text)
    if not name:
        return ResolvedTarget("invalid")
    matches = await storage.users.find_by_username(bot_id, name)
    if len(matches) == 1:
        return ResolvedTarget("user", matches[0].user_id, tuple(matches))
    if len(matches) > 1:
        return ResolvedTarget("ambiguous", matches=tuple(matches))
    return ResolvedTarget("missing")


def format_ambiguous_users(matches: tuple[UserRecord, ...] | list[UserRecord]) -> str:
    lines = ["Найдено несколько пользователей:"]
    for user in matches:
        nick = f"@{html.escape(user.username)}" if user.username else "—"
        lines.append(f"{user.user_id} {nick}")
    lines.append("Уточните числовой ID.")
    return "\n".join(lines)
