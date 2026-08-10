import pytest
from sqlalchemy.exc import IntegrityError

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


def test_different_products_can_share_provider_external_offer_id(db_session):
    products = [
        Product(
            family_slug="smartbudget",
            slug=f"shared-provider-offer-{index}",
            name="SmartBudget",
            edition="Standard",
            archive_path="archives/smartbudget.zip",
            status="in_sale",
        )
        for index in range(2)
    ]
    db_session.add_all(products)
    db_session.flush()
    repository = PaymentProviderOfferRepository(db_session)

    for product in products:
        repository.create(
            PaymentProviderOffer(
                product_id=product.id,
                provider="lava_top",
                external_offer_id="shared-dynamic-price-offer",
            )
        )

    mappings = db_session.query(PaymentProviderOffer).order_by(
        PaymentProviderOffer.product_id
    )
    assert [mapping.product_id for mapping in mappings] == [
        product.id for product in products
    ]
    assert {mapping.external_offer_id for mapping in mappings} == {
        "shared-dynamic-price-offer"
    }


def test_product_cannot_have_two_mappings_for_same_provider(db_session):
    product = Product(
        family_slug="smartbudget",
        slug="duplicate-product-provider-mapping",
        name="SmartBudget",
        edition="Standard",
        archive_path="archives/smartbudget.zip",
        status="in_sale",
    )
    db_session.add(product)
    db_session.flush()
    repository = PaymentProviderOfferRepository(db_session)
    repository.create(
        PaymentProviderOffer(
            product_id=product.id,
            provider="lava_top",
            external_offer_id="first-offer",
        )
    )

    with pytest.raises(IntegrityError):
        repository.create(
            PaymentProviderOffer(
                product_id=product.id,
                provider="lava_top",
                external_offer_id="second-offer",
            )
        )
