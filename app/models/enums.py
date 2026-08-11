from enum import StrEnum


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentCheckResult(StrEnum):
    NON_TERMINAL = "non_terminal"


# example: Sale.payment_status == PaymentStatus.PAID


class SaleItemType:
    PRODUCT = "product"
    SERVICE = "service"
