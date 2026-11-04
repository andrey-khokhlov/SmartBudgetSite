# backend/app/products_catalog.py
from dataclasses import dataclass
from typing import List, Dict


@dataclass(frozen=True)
class Product:
    slug: str
    title_key: str
    subtitle_key: str
    description_key: str
    capabilities_title_key: str
    conditions_key: str
    highlights_keys: List[str]
    cta_key: str
    requirements_url: str | None = None
    requirements_label_key: str | None = None


PRODUCTS: List[Product] = [
    Product(
        slug="smartbudget",
        title_key="product_smartbudget_title",
        subtitle_key="product_smartbudget_subtitle",
        description_key="product_smartbudget_description",
        capabilities_title_key="product_smartbudget_capabilities_title",
        conditions_key="product_smartbudget_conditions",
        highlights_keys=[
            "product_smartbudget_h1",
            "product_smartbudget_h2",
            "product_smartbudget_h3",
        ],
        cta_key="product_smartbudget_cta",
        requirements_url="/faq?open=system-requirements#system-requirements-question",
        requirements_label_key="product_requirements_label",
    ),
]


def products_index() -> List[Dict]:
    # return [p.__dict__ for p in PRODUCTS]
    return [
        {
            "slug": p.slug,
            "title_key": p.title_key,
            "subtitle_key": p.subtitle_key,
            "description_key": p.description_key,
            "capabilities_title_key": p.capabilities_title_key,
            "conditions_key": p.conditions_key,
            "highlights_keys": p.highlights_keys,
            "cta_key": p.cta_key,
            "requirements_url": p.requirements_url,
            "requirements_label_key": p.requirements_label_key,
        }
        for p in PRODUCTS
    ]


def product_by_slug(slug: str) -> Product | None:
    return next((p for p in PRODUCTS if p.slug == slug), None)
