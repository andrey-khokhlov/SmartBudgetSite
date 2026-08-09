from app.models.payment_provider_offer import PaymentProviderOffer
from app.models.product import Product
from app.repositories.payment_provider_offer_repository import (
    PaymentProviderOfferRepository,
)


def test_get_by_product_and_provider_returns_matching_offer(db_session):
    product = Product(
        family_slug="smartbudget",
        slug="provider-offer-repository-test",
        name="SmartBudget",
        edition="Standard",
        archive_path="archives/smartbudget.zip",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()
    offer = PaymentProviderOffer(
        product_id=product.id,
        provider="lava_top",
        external_offer_id="lava-offer-1",
    )
    db_session.add(offer)
    db_session.flush()

    result = PaymentProviderOfferRepository(db_session).get_by_product_and_provider(
        product_id=product.id,
        provider="lava_top",
    )

    assert result is not None
    assert result.id == offer.id
    assert result.external_offer_id == "lava-offer-1"


def test_get_by_product_and_provider_does_not_cross_provider_boundary(db_session):
    product = Product(
        family_slug="smartbudget",
        slug="provider-offer-repository-miss-test",
        name="SmartBudget",
        edition="Standard",
        archive_path="archives/smartbudget.zip",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()
    db_session.add(
        PaymentProviderOffer(
            product_id=product.id,
            provider="stripe",
            external_offer_id="stripe-offer-1",
        )
    )
    db_session.flush()

    result = PaymentProviderOfferRepository(db_session).get_by_product_and_provider(
        product_id=product.id,
        provider="lava_top",
    )

    assert result is None
