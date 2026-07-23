from pydantic import BaseModel, ConfigDict, EmailStr


class PurchaseLookupRequest(BaseModel):
    email: EmailStr


class VerifiedProductPurchaseResponse(BaseModel):
    purchase_reference: str
    product_name: str
    edition: str

    model_config = ConfigDict(from_attributes=True)


class PurchaseLookupResponse(BaseModel):
    verified: bool
    purchases: list[VerifiedProductPurchaseResponse] | None = None
