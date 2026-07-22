from pydantic import BaseModel, EmailStr


class PurchaseLookupRequest(BaseModel):
    email: EmailStr


class PurchaseLookupResponse(BaseModel):
    verified: bool
