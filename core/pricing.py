"""Strategy Pattern — chính sách giá + payload VietQR."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import quote

from config import VIETQR_ACCOUNT, VIETQR_ACCOUNT_NAME, VIETQR_BANK


class PricingStrategy(ABC):
    name = "base"

    @abstractmethod
    def quote(self, weight_gram: float, unit_price_per_kg: int, product_code: str) -> dict[str, Any]:
        raise NotImplementedError


def vietqr_url(amount: int, product_code: str) -> str:
    info = quote(f"THANH TOAN {product_code}")
    name = quote(VIETQR_ACCOUNT_NAME)
    return (
        f"https://img.vietqr.io/image/{VIETQR_BANK}-{VIETQR_ACCOUNT}-compact2.png"
        f"?amount={max(0, int(amount))}&addInfo={info}&accountName={name}"
    )


class StandardPricing(PricingStrategy):
    name = "standard"

    def quote(self, weight_gram: float, unit_price_per_kg: int, product_code: str) -> dict[str, Any]:
        total = int(round((weight_gram / 1000.0) * unit_price_per_kg))
        return {
            "is_sellable": True,
            "unit_price_per_kg": unit_price_per_kg,
            "total_amount": total,
            "payment_status": "UNPAID",
            "qr_payload": vietqr_url(total, product_code),
            "pricing_strategy": self.name,
        }


class RejectedPricing(PricingStrategy):
    name = "rejected"

    def quote(self, weight_gram: float, unit_price_per_kg: int, product_code: str) -> dict[str, Any]:
        return {
            "is_sellable": False,
            "unit_price_per_kg": unit_price_per_kg,
            "total_amount": 0,
            "payment_status": "BLOCKED",
            "qr_payload": None,
            "pricing_strategy": self.name,
            "message": "Phát hiện thực phẩm hư hỏng — khóa thanh toán, vui lòng bỏ quả hỏng ra.",
        }


class DiscountPricing(PricingStrategy):
    """Giảm 50% cho thực phẩm chín/cận đát (tuỳ chọn)."""

    name = "discount"
    factor = 0.5

    def quote(self, weight_gram: float, unit_price_per_kg: int, product_code: str) -> dict[str, Any]:
        total = int(round((weight_gram / 1000.0) * unit_price_per_kg * self.factor))
        return {
            "is_sellable": True,
            "unit_price_per_kg": unit_price_per_kg,
            "total_amount": total,
            "payment_status": "UNPAID",
            "qr_payload": vietqr_url(total, product_code),
            "pricing_strategy": self.name,
            "discount_percent": 50,
        }


def select_pricing(quality_status: str, detected_class: str = "") -> PricingStrategy:
    if quality_status == "ROTTEN":
        return RejectedPricing()
    if "Ripe" in detected_class or "Overripe" in detected_class:
        return DiscountPricing()
    return StandardPricing()
