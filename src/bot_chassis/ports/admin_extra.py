"""Optional project-specific actions appended to the universal admin home."""

from __future__ import annotations

from typing import Protocol, Sequence

from aiogram.types import CallbackQuery


class ExtraAdminActions(Protocol):
    def home_rows(self) -> Sequence[Sequence[tuple[str, str]]]:
        """Ряды главного экрана админки. Рама показывает их только root."""
        ...

    async def handle_callback(self, call: CallbackQuery) -> bool: ...
