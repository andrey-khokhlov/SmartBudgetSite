import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.models.payment_provider_offer import PaymentProviderOffer
from app.models.product import Product
from scripts.set_payment_provider_offer import (
    PaymentProviderOfferInputError,
    PaymentProviderOfferPersistenceError,
    PaymentProviderOfferProductNotFoundError,
    main,
    set_payment_provider_offer,
)


def create_product(db_session, slug: str = "payment-provider-offer-script-test"):
    product = Product(
        family_slug="smartbudget",
        slug=slug,
        name="SmartBudget",
        edition="Standard",
        archive_path="archives/smartbudget.zip",
        status="in_sale",
    )
    db_session.add(product)
    db_session.commit()
    return product


def get_mapping(db_session, product: Product) -> PaymentProviderOffer | None:
    return (
        db_session.query(PaymentProviderOffer)
        .filter(
            PaymentProviderOffer.product_id == product.id,
            PaymentProviderOffer.provider == "lava_top",
        )
        .one_or_none()
    )


def test_creates_mapping_for_existing_product_and_normalizes_values(db_session):
    product = create_product(db_session, "mapping-script-create-test")
    output = []

    change = set_payment_provider_offer(
        db_session,
        product_slug=product.slug,
        provider="  lava_top  ",
        external_offer_id="  offer-created  ",
        output=output.append,
    )

    mapping = get_mapping(db_session, product)
    assert change == "created"
    assert mapping is not None
    assert mapping.provider == "lava_top"
    assert mapping.external_offer_id == "offer-created"
    assert output == [
        "created: product=mapping-script-create-test provider=lava_top "
        "external_offer_id=offer-created"
    ]


def test_creates_shared_offer_mappings_for_different_products(db_session):
    products = [
        create_product(db_session, "mapping-script-shared-offer-int"),
        create_product(db_session, "mapping-script-shared-offer-ru"),
    ]

    changes = [
        set_payment_provider_offer(
            db_session,
            product_slug=product.slug,
            provider="lava_top",
            external_offer_id="shared-dynamic-price-offer",
            output=lambda message: None,
        )
        for product in products
    ]

    mappings = db_session.query(PaymentProviderOffer).order_by(
        PaymentProviderOffer.product_id
    )
    assert changes == ["created", "created"]
    assert [mapping.product_id for mapping in mappings] == [
        product.id for product in products
    ]
    assert {mapping.external_offer_id for mapping in mappings} == {
        "shared-dynamic-price-offer"
    }


def test_updates_existing_mapping(db_session):
    product = create_product(db_session, "mapping-script-update-test")
    db_session.add(
        PaymentProviderOffer(
            product_id=product.id,
            provider="lava_top",
            external_offer_id="old-offer",
        )
    )
    db_session.commit()
    output = []

    change = set_payment_provider_offer(
        db_session,
        product_slug=product.slug,
        provider="lava_top",
        external_offer_id="new-offer",
        output=output.append,
    )

    mapping = get_mapping(db_session, product)
    assert change == "updated"
    assert mapping is not None
    assert mapping.external_offer_id == "new-offer"
    assert output[0].startswith("updated:")


def test_unchanged_mapping_is_idempotent_and_creates_no_duplicate(
    db_session,
    monkeypatch,
):
    product = create_product(db_session, "mapping-script-unchanged-test")
    db_session.add(
        PaymentProviderOffer(
            product_id=product.id,
            provider="lava_top",
            external_offer_id="same-offer",
        )
    )
    db_session.commit()
    commit_calls = 0
    output = []

    def track_commit():
        nonlocal commit_calls
        commit_calls += 1

    monkeypatch.setattr(db_session, "commit", track_commit)

    change = set_payment_provider_offer(
        db_session,
        product_slug=product.slug,
        provider=" lava_top ",
        external_offer_id=" same-offer ",
        output=output.append,
    )

    assert change == "unchanged"
    assert commit_calls == 0
    assert db_session.query(PaymentProviderOffer).count() == 1
    assert output[0].startswith("unchanged:")


def test_missing_product_fails_clearly(db_session):
    with pytest.raises(
        PaymentProviderOfferProductNotFoundError,
        match="Product not found for exact slug: missing-product",
    ):
        set_payment_provider_offer(
            db_session,
            product_slug="missing-product",
            provider="lava_top",
            external_offer_id="offer-id",
        )


@pytest.mark.parametrize("provider", ["", "   \t"])
def test_empty_provider_is_rejected(db_session, provider):
    with pytest.raises(
        PaymentProviderOfferInputError,
        match="Provider must not be empty",
    ):
        set_payment_provider_offer(
            db_session,
            product_slug="any-product",
            provider=provider,
            external_offer_id="offer-id",
        )


@pytest.mark.parametrize("external_offer_id", ["", "   \t"])
def test_empty_external_offer_id_is_rejected(db_session, external_offer_id):
    with pytest.raises(
        PaymentProviderOfferInputError,
        match="External offer ID must not be empty",
    ):
        set_payment_provider_offer(
            db_session,
            product_slug="any-product",
            provider="lava_top",
            external_offer_id=external_offer_id,
        )


def test_persistence_error_rolls_back(db_session, monkeypatch):
    product = create_product(db_session, "mapping-script-rollback-test")
    rollback_calls = 0
    real_rollback = db_session.rollback

    def fail_commit():
        raise SQLAlchemyError("simulated persistence failure")

    def track_rollback():
        nonlocal rollback_calls
        rollback_calls += 1
        real_rollback()

    monkeypatch.setattr(db_session, "commit", fail_commit)
    monkeypatch.setattr(db_session, "rollback", track_rollback)

    with pytest.raises(PaymentProviderOfferPersistenceError):
        set_payment_provider_offer(
            db_session,
            product_slug=product.slug,
            provider="lava_top",
            external_offer_id="offer-not-persisted",
        )

    assert rollback_calls == 1
    assert db_session.query(PaymentProviderOffer).count() == 0


def test_main_prints_clear_failure_for_missing_product(
    db_session,
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        "scripts.set_payment_provider_offer.SessionLocal",
        lambda: db_session,
    )

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--product-slug",
                "missing-product",
                "--provider",
                "lava_top",
                "--external-offer-id",
                "offer-id",
            ]
        )

    assert exc_info.value.code == 1
    assert (
        "failed: Product not found for exact slug: missing-product"
        in capsys.readouterr().err
    )
