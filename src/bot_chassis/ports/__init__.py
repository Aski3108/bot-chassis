"""Порты рамы и дефолтные адаптеры над Storage."""

from .access import AccessPort, DefaultAccessAdapter
from .cabinet import (
    CabinetSlot,
    CabinetSlotsProviderPort,
    DefaultCabinetSlotsAdapter,
    build_cabinet_renderer,
)
from .donations import DonationCatalogPort, merge_payment_skus, resolve_donation_items
from .reviews import ReviewPublishResult, ReviewSinkPort, TelegramReviewSink
from .payments import (
    DefaultVoucherManagerAdapter,
    SkuVoucher,
    SkuVoucherConsumerPort,
    VoucherManagerPort,
)
from .process_control import ProcessControlPort, ProcessOperationResult, ProcessTarget
from .referrals import DefaultReferralAdapter, ReferralPort
from .work_gate import DefaultWorkGateAdapter, WorkGatePort

__all__ = [
    "AccessPort",
    "CabinetSlot",
    "CabinetSlotsProviderPort",
    "DefaultAccessAdapter",
    "DefaultCabinetSlotsAdapter",
    "DefaultReferralAdapter",
    "DefaultVoucherManagerAdapter",
    "DefaultWorkGateAdapter",
    "DonationCatalogPort",
    "ProcessControlPort",
    "ProcessOperationResult",
    "ProcessTarget",
    "ReferralPort",
    "ReviewPublishResult",
    "ReviewSinkPort",
    "TelegramReviewSink",
    "SkuVoucher",
    "SkuVoucherConsumerPort",
    "VoucherManagerPort",
    "WorkGatePort",
    "build_cabinet_renderer",
    "merge_payment_skus",
    "resolve_donation_items",
]
