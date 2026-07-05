from app.models.product import Product
from app.models.product_price import ProductPrice
from app.repositories.products_repository import ProductsRepository


def test_list_products_by_family_slug_returns_only_in_sale_products(db_session):
    """
    Test case: list products by family_slug.

    What we verify:
    - products are filtered by family_slug
    - only products with status 'in_sale' are returned
    - products from another family are not returned
    """

    product_ru = Product(
        family_slug="smartbudget",
        slug="smartbudget-ru-standard",
        name="SmartBudget RU Standard",
        archive_path="",
        edition="Standard",

        status="in_sale",
    )
    product_int = Product(
        family_slug="smartbudget",
        slug="smartbudget-int-standard",
        name="SmartBudget INT Standard",
        archive_path="",
        edition="Standard",

        status="in_sale",
    )
    product_future = Product(
        family_slug="smartbudget",
        slug="smartbudget-ru-pro",
        name="SmartBudget RU Pro",
        archive_path="",
        edition="Pro",

        status="in_development",
    )
    another_family_product = Product(
        family_slug="another-product",
        slug="another-product-standard",
        name="Another Product Standard",
        archive_path="",
        edition="Standard",

        status="in_sale",
    )

    db_session.add_all(
        [
            product_ru,
            product_int,
            product_future,
            another_family_product,
        ]
    )
    db_session.commit()

    repository = ProductsRepository(db_session)

    result = repository.list_products_by_family_slug("smartbudget")

    result_slugs = {product.slug for product, price in result}

    assert result_slugs == {
        "smartbudget-ru-standard",
        "smartbudget-int-standard",
    }


def test_list_products_by_family_slug_returns_active_price(db_session):
    """
    Test case: list products by family_slug with active price.

    What we verify:
    - active product price is returned together with product
    - returned price belongs to the selected product
    """

    product = Product(
        family_slug="smartbudget",
        slug="smartbudget-int-standard",
        name="SmartBudget INT Standard",
        archive_path="",
        edition="Standard",

        status="in_sale",
    )

    db_session.add(product)
    db_session.flush()

    price = ProductPrice(
        product_id=product.id,
        currency_code="EUR",
        amount=39.00,
        is_active=True,
    )

    db_session.add(price)
    db_session.commit()

    repository = ProductsRepository(db_session)

    result = repository.list_products_by_family_slug("smartbudget")

    returned_product, returned_price = result[0]

    assert returned_product.slug == "smartbudget-int-standard"
    assert returned_price.currency_code == "EUR"
    assert returned_price.amount == 39.00
