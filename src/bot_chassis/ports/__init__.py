"""Порты рамы и дефолтные адаптеры над Storage."""

from .access import AccessPort, DefaultAccessAdapter
from .cabinet import (
    CabinetSlot,
    CabinetSlotsProviderPort,
    DefaultCabinetSlotsAdapter,
    build_cabinet_renderer,
)
from .donations import DonationCatalogPort, resolve_donation_items
from .reviews import ReviewPublishResult, ReviewSinkPort, TelegramReviewSink
from .payments import (
    DefaultVoucherManagerAdapter,
    SkuVoucher,
    SkuVoucherConsumerPort,
    VoucherManagerPort,
)
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
    "ReferralPort",
    "ReviewPublishResult",
    "ReviewSinkPort",
    "TelegramReviewSink",
    "SkuVoucher",
    "SkuVoucherConsumerPort",
    "VoucherManagerPort",
    "WorkGatePort",
    "build_cabinet_renderer",
    "resolve_donation_items",
]
