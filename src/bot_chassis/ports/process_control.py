"""Управление процессами: рама не знает systemd, Docker и имён unit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class ProcessTarget:
    """Цель, которую задаёт кузов или серверный адаптер."""

    target_id: str
    label: str
    is_controller: bool = False
    status: str = ""


@dataclass(frozen=True, slots=True)
class ProcessOperationResult:
    """Итог одной цели. status: ok / error / timeout."""

    operation_id: str
    target_id: str
    status: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK


class ProcessControlPort(Protocol):
    """Кузов или серверный адаптер. Рама не знает systemd, Docker и имён unit.

    Для одного процесса рама зовёт ``restart``. Для «всех» сама вызывает
    ``restart`` по очереди (управляющий последним) и пишет промежуточный итог
    после каждой цели. ``restart_all`` остаётся методом адаптера и тестов;
    рама его не вызывает, чтобы не потерять пошаговый ops-отчёт.
    """
    async def list_targets(self) -> Sequence[ProcessTarget]: ...

    async def restart(self, target_id: str) -> ProcessOperationResult: ...

    async def restart_all(self) -> Sequence[ProcessOperationResult]:
        """Пакетный рестарт адаптера/тестов. Рама для «всех» зовёт ``restart`` по очереди."""
        ...

    async def get_status(self, operation_id: str) -> ProcessOperationResult | None: ...


def order_targets(targets: Sequence[ProcessTarget]) -> list[ProcessTarget]:
    """Управляющие цели идут последними, порядок внутри групп сохраняется."""
    others = [item for item in targets if not item.is_controller]
    controllers = [item for item in targets if item.is_controller]
    return others + controllers
