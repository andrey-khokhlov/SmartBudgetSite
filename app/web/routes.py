from fastapi import APIRouter, Request, HTTPException, Depends, Form, Query, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.products_catalog import products_index, product_by_slug
from app.core.i18n import get_lang, set_lang_cookie, t
from app.core.config import settings
from app.dependencies import get_db, require_admin
from app.repositories.feedback_admin_repository import FeedbackAdminRepository
from app.repositories.products_repository import ProductsRepository
from app.repositories.service_addon_repository import ServiceAddonRepository
from app.repositories.sales_repository import list_admin_sales
from app.services.admin_consultation_service import get_consultation_entitlements
from app.services.feedback_service import (
    send_feedback_reply,
    toggle_feedback_publish,
    toggle_feedback_resolved,
    save_feedback_reply_draft
    )
from app.services.feedback_prefill_service import (
    get_download_feedback_prefill_context,
)
from app.services.consultation_entitlement_service import (
    get_valid_consultation_entitlement_by_token,
)
from app.services.download_entitlement_service import (
    get_download_support_reference_by_token,
    get_valid_download_entitlement_by_token,
    record_download_attempt,
)
from app.services.product_release_service import (
    ProductReleaseService,
    ReleaseArchiveTooLargeError,
    inspect_release_archive,
)
from app.services.storage.r2_storage_service import R2SignedUrlError, R2StorageService
from app.models.product import ALLOWED_EDITIONS, ALLOWED_PRODUCT_STATUSES, Product
from app.models.product_price import ProductPrice
from app.utils.product_utils import get_product_package

from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from datetime import UTC, datetime, timezone, timedelta
from decimal import Decimal
from botocore.exceptions import BotoCoreError, ClientError


moscow_tz = timezone(timedelta(hours=3))

router = APIRouter()

templates = Jinja2Templates(directory="app/templates")

ADMIN_COOKIE_NAME = "admin_token"

admin_router = APIRouter(
    dependencies=[Depends(require_admin)]
)


def render(
    request: Request,
    template_name: str,
    context: dict,
    *,
    status_code: int = 200,
):
    lang = get_lang(request)

    response = templates.TemplateResponse(
        request,
        template_name,
        {
            "lang": lang,
            "t": lambda k: t(lang, k),
            **context,
        },
        status_code=status_code,
    )

    if (request.query_params.get("lang") or "").lower() in {"en", "ru"}:
        set_lang_cookie(response, lang)

    return response


DOWNLOAD_ERROR_TRANSLATION_KEYS = {
    "Download link was not found.": "download_error_unknown",
    "Download link has expired.": "download_error_expired",
    "Download link has been cancelled.": "download_error_cancelled",
    "This download has already been completed.": "download_error_completed",
    "Download attempt limit has been reached.": "download_error_attempt_limit",
    "Download release was not found.": "download_error_missing_release",
}


def _feedback_prefill_url(
    request: Request,
    support_reference: str | None,
) -> str:
    params = {
        "message_type": "purchase_or_download_issue",
        "lang": get_lang(request),
    }
    if support_reference is not None:
        params["support_reference"] = support_reference
    return str(request.url_for("feedback_page").include_query_params(**params))


def _render_download_error(
    request: Request,
    exc: HTTPException,
    support_reference: str | None,
):
    error_key = DOWNLOAD_ERROR_TRANSLATION_KEYS.get(
        str(exc.detail),
        "download_error_unavailable",
    )

    return render(
        request,
        "download.html",
        {
            "error_key": error_key,
            "support_reference": support_reference,
            "feedback_url": _feedback_prefill_url(request, support_reference),
        },
        status_code=exc.status_code,
    )


def _as_moscow_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(moscow_tz)


def _format_file_size(file_size: int | None) -> str | None:
    if file_size is None:
        return None
    if file_size < 1024:
        return f"{file_size} B"
    if file_size < 1024 * 1024:
        return f"{file_size / 1024:.1f} KB"
    return f"{file_size / (1024 * 1024):.1f} MB"


def _format_release_upload_limit(max_bytes: int) -> str:
    bytes_per_mib = 1024 * 1024
    if max_bytes % bytes_per_mib == 0:
        return f"{max_bytes // bytes_per_mib} MiB"
    return f"{max_bytes} bytes"


def format_money(value, lang: str = "ru"):
    """
    Format numeric value according to UI language.

    Business rules:
    - RU uses spaces for thousands and comma as decimal separator.
    - EN uses comma for thousands and dot as decimal separator.

    Side effects:
    - None. Formatting only.

    Invariants/restrictions:
    - Always returns value with 2 decimal places.
    """

    amount = Decimal(value)

    formatted = f"{amount:,.2f}"

    if lang == "ru":
        return formatted.replace(",", " ").replace(".", ",")

    return formatted


templates.env.filters["money"] = format_money


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return render(request, "index.html", {})


@router.get("/products", response_class=HTMLResponse)
async def products(request: Request):
    return render(request, "products.html", {
        "products": products_index(),
    })


@router.get("/faq", response_class=HTMLResponse)
async def faq(request: Request):
    return render(request, "faq.html", {})


@router.get("/feedback", response_class=HTMLResponse)
async def feedback_page(
    request: Request,
    message_type: str | None = Query(default=None),
    support_reference: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    preselected_type = (
        "purchase_or_download_issue"
        if message_type == "purchase_or_download_issue"
        else None
    )
    prefill_context = (
        get_download_feedback_prefill_context(
            db,
            support_reference,
            get_lang(request),
        )
        if preselected_type is not None
        and support_reference is not None
        else None
    )
    return render(
        request,
        "feedback.html",
        {
            "preselected_type": preselected_type,
            "prefill_context": prefill_context,
        },
    )


@router.get("/download/{download_token}", response_class=HTMLResponse)
def download_page(
    download_token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        entitlement = get_valid_download_entitlement_by_token(db, download_token)
    except HTTPException as exc:
        support_reference = get_download_support_reference_by_token(
            db,
            download_token,
        )
        return _render_download_error(
            request,
            exc,
            support_reference,
        )

    release = entitlement.release
    product_name = (
        release.product.name
        if release.product is not None
        else entitlement.sale_item.item_name
    )

    # return render(
    #     request,
    #     "download.html",
    #     {
    #         "product_name": "SmartBudget Standard",
    #         "release": type(
    #             "Release",
    #             (),
    #             {
    #                 "version": "1.2.0",
    #                 "original_filename": "SmartBudget_v1.2.0.zip",
    #                 "sha256_hash": "3b2d6f7d8a4d0b2e1f8b6c5a4d3e2f1c9b8a7d6e5f4c3b2a1d0e9f8a7b6c5d4",
    #             },
    #         )(),
    #         "released_at": datetime.now(UTC),
    #         "expires_at": datetime.now(UTC),
    #         "file_size": "18.6 MB",
    #         "remaining_attempts": 3,
    #         "support_reference": "DL-8F3A19",
    #         "signed_url_ttl_minutes": 15,
    #     },
    # )

    return render(
        request,
        "download.html",
        {
            "entitlement": entitlement,
            "release": release,
            "product_name": product_name,
            "file_size": _format_file_size(release.file_size),
            "released_at": (
                _as_moscow_time(release.released_at)
                if release.released_at is not None
                else None
            ),
            "expires_at": _as_moscow_time(entitlement.expires_at),
            "remaining_attempts": (
                settings.DOWNLOAD_MAX_ATTEMPTS - entitlement.attempt_count
            ),
            "support_reference": entitlement.support_reference,
            "feedback_url": _feedback_prefill_url(
                request,
                entitlement.support_reference,
            ),
            "signed_url_ttl_minutes": (
                settings.DOWNLOAD_SIGNED_URL_TTL_SECONDS + 59
            )
            // 60,
        },
    )


@router.post("/download/{download_token}")
def issue_download(
    download_token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        entitlement = record_download_attempt(db, download_token)
    except HTTPException as exc:
        support_reference = get_download_support_reference_by_token(
            db,
            download_token,
        )
        return _render_download_error(
            request,
            exc,
            support_reference,
        )

    storage_key = entitlement.release.storage_key
    db.commit()

    try:
        signed_url = R2StorageService().generate_signed_get_url(
            storage_key=storage_key,
            download_filename=entitlement.release.original_filename,
        )
    except (HTTPException, R2SignedUrlError):
        return _render_download_error(
            request,
            HTTPException(
                status_code=503,
                detail="Download storage is temporarily unavailable.",
            ),
            entitlement.support_reference,
        )

    return RedirectResponse(url=signed_url, status_code=303)


@router.get("/products/{slug}", response_class=HTMLResponse)
async def product_detail(request: Request, slug: str):
    product = product_by_slug(slug)
    if not product:
        raise HTTPException(status_code=404)

    template_name = "sm_landing.html" if slug == "smartbudget" else "product_detail.html"

    return render(request, template_name, {
        "product": product,
    })


@admin_router.get("/admin/feedback", response_class=HTMLResponse)
async def admin_feedback_list(
    request: Request,
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
):
    page_size = 50
    offset = (page - 1) * page_size

    repo = FeedbackAdminRepository(db)
    items_page = repo.list_feedback(
        limit=page_size + 1,
        offset=offset,
    )

    has_next = len(items_page) > page_size
    items = items_page[:page_size]

    return render(
        request,
        "admin_feedback_list.html",
        {
            "items": items,
            "page": page,
            "page_size": page_size,
            "has_next": has_next,
        },
    )

@admin_router.get("/admin/feedback/{feedback_id}", response_class=HTMLResponse)
async def admin_feedback_detail(
    request: Request,
    feedback_id: int,
    db: Session = Depends(get_db),
):
    repo = FeedbackAdminRepository(db)
    item = repo.get_feedback_by_id(feedback_id)

    if not item:
        raise HTTPException(status_code=404)

    local_reply_sent_at = None

    if item.reply_sent_at:
        local_reply_sent_at = item.reply_sent_at.astimezone(moscow_tz)

    return render(
        request,
        "admin_feedback_detail.html",
        {
            "item": item,
            "local_reply_sent_at": local_reply_sent_at,
        },
    )


@admin_router.post("/admin/feedback/{feedback_id}/resolve")
async def admin_feedback_resolve(
    feedback_id: int,
    db: Session = Depends(get_db),
):
    toggle_feedback_resolved(db=db, feedback_id=feedback_id)

    return RedirectResponse(
        url=f"/admin/feedback/{feedback_id}",
        status_code=303,
    )


@admin_router.post("/admin/feedback/{feedback_id}/reply")
async def admin_feedback_save_reply(
    feedback_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    form = await request.form()
    admin_reply = str(form.get("admin_reply", ""))

    save_feedback_reply_draft(
        db=db,
        feedback_id=feedback_id,
        admin_reply=admin_reply,
    )

    return RedirectResponse(
        url=f"/admin/feedback/{feedback_id}?saved=1",
        status_code=303,
    )


@admin_router.post("/admin/feedback/{feedback_id}/publish")
async def admin_feedback_toggle_publish(
    feedback_id: int,
    db: Session = Depends(get_db),
):
    toggle_feedback_publish(db=db, feedback_id=feedback_id)

    return RedirectResponse(
        url=f"/admin/feedback/{feedback_id}",
        status_code=303,
    )


@admin_router.post("/admin/feedback/{feedback_id}/send-email")
def send_feedback_email(
    feedback_id: int,
    db: Session = Depends(get_db),
):
    try:
        send_feedback_reply(db=db, feedback_id=feedback_id)

        return RedirectResponse(
            url=f"/admin/feedback/{feedback_id}?email_sent=1",
            status_code=303,
        )

    except HTTPException as e:
        return RedirectResponse(
            url=f"/admin/feedback/{feedback_id}?error={e.detail}",
            status_code=303,
        )


@router.get("/reviews/{slug}", response_class=HTMLResponse)
async def reviews_page(
    slug: str,
    request: Request,
    db: Session = Depends(get_db),
):
    feedback_repo = FeedbackAdminRepository(db)

    product = db.execute(
        select(Product).where(Product.slug == slug)
    ).scalar_one_or_none()

    if not product:
        raise HTTPException(status_code=404)

    reviews = feedback_repo.list_published_product_feedback(
        product_id=product.id
    )

    return render(request, "reviews.html", {
        "reviews": reviews,
        "product": product,
    })


@router.get("/reviews")
async def reviews_redirect():
    return RedirectResponse(url="/reviews/smartbudget", status_code=307)


@admin_router.get("/admin/products")
async def admin_products_list(
    request: Request,
    db: Session = Depends(get_db),
):
    from app.repositories.products_repository import ProductsRepository

    repo = ProductsRepository(db)
    product_list = repo.list_products()

    lang = get_lang(request)

    return templates.TemplateResponse(
        request,
        "admin_products_list.html",
        {
            "products": product_list,
            "t": lambda key: t(lang, key),
        },
    )


@admin_router.get("/admin/products/new")
async def admin_products_new(request: Request):
    return render(
        request,
        "admin_product_form.html",
        {
            "product": None,
            "active_price": None,
            "allowed_editions": sorted(ALLOWED_EDITIONS),
            "allowed_statuses": sorted(ALLOWED_PRODUCT_STATUSES),
            "form_action": "/admin/products/new",
            "page_title": "Create product",
        },
    )


@admin_router.post("/admin/products/new")
async def admin_products_create(
    request: Request,
    db: Session = Depends(get_db),
    family_slug: str = Form(...),
    name: str = Form(...),
    slug: str = Form(...),
    edition: str = Form(...),
    archive_path: str = Form(default=""),
    price: Decimal = Form(...),
    currency_code: str = Form(...),
    status: str = Form(...),
):
    """
    Creates product and its initial active price.

    Business rules:
    - Product is stored in Product table
    - Product must belong to a product family
    - Price is stored in ProductPrice table
    - New price is created as active
    - Currency code is normalized to uppercase

    Side effects:
    - Inserts one row into products
    - Inserts one row into product_prices

    Invariants / restrictions:
    - price must not be stored in Product model
    - family_slug is required for purchase flow grouping
    - currency_code is stored as uppercase ISO-like code
    """

    product = Product(
        family_slug=family_slug.strip(),
        name=name.strip(),
        slug=slug.strip(),
        edition=edition,
        archive_path=archive_path.strip(),
        status=status,
    )

    try:
        db.add(product)
        db.flush()

        product_price = ProductPrice(
            product_id=product.id,
            currency_code=currency_code.strip().upper(),
            amount=price,
            is_active=True,
        )

        db.add(product_price)
        db.commit()

    except IntegrityError:
        db.rollback()

        return RedirectResponse(
            url="/admin/products/new?error=duplicate_product",
            status_code=303,
        )

    return RedirectResponse(
        url=f"/products/{product.id}/releases",
        status_code=303,
    )


@admin_router.get("/admin/products/{product_id}/edit")
async def admin_products_edit(
    product_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Opens edit form for existing product with active price.

    Business rules:
    - Product must exist
    - Active price is loaded separately from ProductPrice
    - Form must receive both product and current active price

    Side effects:
    - None

    Invariants / restrictions:
    - Returns 404 if product not found
    """

    from sqlalchemy import select
    from app.models.product_price import ProductPrice

    product = db.get(Product, product_id)

    if not product:
        raise HTTPException(status_code=404)

    active_price = db.execute(
        select(ProductPrice).where(
            ProductPrice.product_id == product_id,
            ProductPrice.is_active == True  # noqa: E712
        )
    ).scalar_one_or_none()

    lang = get_lang(request)

    return templates.TemplateResponse(
        request,
        "admin_product_form.html",
        {
            "t": lambda key: t(lang, key),
            "product": product,
            "active_price": active_price,
            "allowed_editions": sorted(ALLOWED_EDITIONS),
            "allowed_statuses": sorted(ALLOWED_PRODUCT_STATUSES),
            "form_action": f"/admin/products/{product_id}/edit",
            "page_title": "Edit product",
        },
    )


@admin_router.post("/admin/products/{product_id}/edit")
async def admin_products_update(
    product_id: int,
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    slug: str = Form(...),
    edition: str = Form(...),
    price: Decimal = Form(...),
    currency_code: str = Form(...),
    status: str = Form(...),
):
    """
    Updates product fields and replaces active price if needed.

    Business rules:
    - Product must exist
    - Product fields are stored in Product
    - Price is stored in ProductPrice
    - Only one active price per product/currency should remain active

    Side effects:
    - Updates Product row
    - May deactivate existing active ProductPrice row
    - May insert new active ProductPrice row

    Invariants / restrictions:
    - Returns 404 if product not found
    - currency_code is normalized to uppercase
    """

    from sqlalchemy import select
    from app.models.product_price import ProductPrice

    product = db.get(Product, product_id)

    if not product:
        raise HTTPException(status_code=404)

    product.name = name.strip()
    product.slug = slug.strip()
    product.edition = edition
    product.status = status

    normalized_currency = currency_code.strip().upper()

    active_price = db.execute(
        select(ProductPrice).where(
            ProductPrice.product_id == product_id,
            ProductPrice.is_active == True,  # noqa: E712
        )
    ).scalar_one_or_none()

    should_replace_price = (
        active_price is None
        or active_price.amount != price
        or active_price.currency_code != normalized_currency
    )

    if should_replace_price:
        if active_price:
            active_price.is_active = False

        new_price = ProductPrice(
            product_id=product.id,
            currency_code=normalized_currency,
            amount=price,
            is_active=True,
        )
        db.add(new_price)

    db.commit()

    return RedirectResponse(
        url="/admin/products",
        status_code=303,
    )


@router.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    return render(request, "admin_login.html", {})


@router.post("/admin/login")
async def admin_login(
    request: Request,
    token: str = Form(...),
):
    """
    Stores admin token in cookie after successful validation.

    Business rules:
    - Login is allowed only when provided token matches settings.ADMIN_TOKEN
    - Valid token is stored in cookie for subsequent admin requests

    Side effects:
    - Sets HTTP cookie in response

    Invariants / restrictions:
    - Invalid token returns 403
    """

    if token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid admin token")

    response = RedirectResponse(
        url="/admin",
        status_code=303,
    )
    response.set_cookie(
        key=ADMIN_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.APP_ENV == "prod",
        max_age=60 * 60 * 8,
    )
    return response


@admin_router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
):
    return render(
        request,
        "admin_dashboard.html",
        {}
    )


@admin_router.post("/admin/logout")
async def admin_logout():
    """
    Clears admin auth cookie and redirects to admin login page.

    Business rules:
    - Admin session is represented by cookie only
    - Logout must always clear the admin cookie

    Side effects:
    - Removes admin auth cookie from browser

    Invariants / restrictions:
    - Safe to call even if cookie is already missing
    """

    response = RedirectResponse(
        url="/admin/login",
        status_code=303,
    )
    response.delete_cookie("admin_token")
    return response


@router.get("/checkout/{slug}")
def checkout_page(
    slug: str,
    request: Request,
    db: Session = Depends(get_db),
    consultation: int | None = Query(default=None),
):
    """
    Render checkout page for a sellable product SKU.

    Business rules:
    - Checkout is product-specific.
    - Product is resolved by slug.
    - Active price must exist before checkout can be shown.
    - Consultation in checkout is treated as add-on usage only.

    Side effects:
    - None. Read-only page rendering.

    Invariants / restrictions:
    - Payment provider is not selected here.
    - User manually selects payment method on the page.
    """

    product, price = ProductsRepository(db).get_product_with_active_price_by_slug(slug)

    if product is None or price is None:
        raise HTTPException(status_code=404, detail="Product not found")

    package = get_product_package(product.slug)

    addon = None

    if consultation == 1:
        addon = ServiceAddonRepository.get_active_addon(
            db,
            family_slug=product.family_slug,
            package_code=package,
            service_type="consultation",
            usage_type="addon",
        )

    total_amount = price.amount

    if addon is not None:
        total_amount += addon.amount

    if addon is not None and addon.currency_code != price.currency_code:
        raise HTTPException(
            status_code=500,
            detail="Currency mismatch between product and addon",
        )

    return render(
        request,
        "checkout.html",
        {
            "product": product,
            "addon": addon,
            "price": price,
            "total_amount": total_amount,
            "consultation": consultation == 1,
            "package": package,
            "lang": get_lang(request),
        },
    )


@router.get("/products/{family_slug}/buy")
def product_buy_page(
    family_slug: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Render product family purchase selection page.

    Business rules:
    - family_slug identifies a product family, for example SmartBudget.
    - The page shows only products currently available for sale.
    - If no products are available for this family, return 404.

    Side effects:
    - None. Read-only page rendering.

    Invariants / restrictions:
    - Does not create sales.
    - Does not start payment processing.
    """

    repository = ProductsRepository(db)
    family_products = repository.list_products_by_family_slug(family_slug)

    if not family_products:
        raise HTTPException(status_code=404, detail="Product family not found")

    lang = get_lang(request)
    product_options = []

    for product, price in family_products:
        package = get_product_package(product.slug)

        consultation_addon = ServiceAddonRepository.get_active_addon(
            db,
            family_slug=product.family_slug,
            package_code=package,
            service_type="consultation",
            usage_type="addon",
        )

        product_options.append(
            {
                "product": product,
                "price": price,
                "consultation_addon": consultation_addon,
            }
        )

    return templates.TemplateResponse(
        request,
        "product_buy.html",
        {
            "product_options": product_options,
            "family_slug": family_slug,
            "lang": lang,
            "t": lambda key: t(lang, key),
        },
    )


@router.get("/consultation/book/{booking_token}")
def consultation_booking_page(
    booking_token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Render consultation booking page after backend token validation.

    Business rules:
    - Booking page is accessible only with a valid backend-owned token.
    - Token validation must happen before Calendly access is shown.
    - Invalid, expired, booked, or cancelled entitlements must not show booking UI.

    Side effects:
    - Does not modify the database.
    - Does not create a Calendly booking.

    Invariants/restrictions:
    - Route stays thin and delegates validation to service layer.
    """

    entitlement = get_valid_consultation_entitlement_by_token(
        db=db,
        booking_token=booking_token,
    )

    lang = get_lang(request)

    masked_token = f"{booking_token[:8]}..."

    return templates.TemplateResponse(
        request=request,
        name="consultation_booking.html",
        context={
            "entitlement": entitlement,
            "calendly_consultation_url": settings.CALENDLY_CONSULTATION_URL,
            "lang": lang,
            "t": lambda key: t(lang, key),
            "masked_token": masked_token,
        },
    )


@admin_router.get("/admin/consultations")
def admin_consultations_page(
    request: Request,
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
):
    """
    Render consultation entitlement admin page.

    Business rules:
    - Admin visibility is read-only.
    - Consultation lifecycle must remain observable operationally.

    Side effects:
    - Executes read queries only.

    Invariants/restrictions:
    - Does not mutate entitlement state.
    """

    page_size = 50
    offset = (page - 1) * page_size

    entitlements_page = get_consultation_entitlements(
        db=db,
        status=status,
        limit=page_size + 1,
        offset=offset,
    )

    has_next = len(entitlements_page) > page_size
    entitlements = entitlements_page[:page_size]

    lang = get_lang(request)
    entitlements_count = len(entitlements)

    return templates.TemplateResponse(
        request=request,
        name="admin_consultation_entitlements.html",
        context={
            "entitlements": entitlements,
            "lang": lang,
            "t": lambda key: t(lang, key),
            "selected_status": status,
            "entitlements_count": entitlements_count,
            "page": page,
            "page_size": page_size,
            "has_next": has_next,
        },
    )


@admin_router.get("/admin/sales")
async def admin_sales_list(
    request: Request,
    status: str | None = Query(default=None),
    customer_email: str | None = Query(default=None),
    item_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
):
    page_size = 50
    offset = (page - 1) * page_size

    sales_page = list_admin_sales(
        db=db,
        status=status,
        customer_email=customer_email,
        item_type=item_type,
        limit=page_size + 1,
        offset=offset,
    )

    has_next = len(sales_page) > page_size
    sales = sales_page[:page_size]

    return render(
        request,
        "admin_sales_list.html",
        {
            "sales": sales,
            "selected_status": status,
            "selected_customer_email": customer_email,
            "selected_item_type": item_type,
            "page": page,
            "page_size": page_size,
            "has_next": has_next,
        },
    )


@admin_router.get(
    "/products/{product_id}/releases/new",
    response_class=HTMLResponse,
)
def admin_product_release_new(
    request: Request,
    product_id: int,
    db: Session = Depends(get_db),
):
    """
        Render the upload release form.
        Business rules:
        - Product release upload is a separate admin workflow.
        - New releases are created as inactive release candidates.
        Side effects:
        - None.
        Invariants/restrictions:
        - Does not upload files.
        - Does not create ProductRelease records.
        - Does not publish releases.
        """
    product = db.get(Product, product_id)

    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    release_service = ProductReleaseService(db)
    releases = release_service.list_releases_by_product_id(product_id)

    latest_release = releases[0] if releases else None

    product_slug = str(product.slug)
    package = get_product_package(product_slug)

    return render(
        request,
        "admin_product_release_form.html",
        {
            "product": product,
            "product_id": product_id,
            "package": package,
            "latest_release": latest_release,
        },
    )


@admin_router.post("/products/{product_id}/releases/new")
def admin_product_release_create(
    product_id: int,
    version: str = Form(...),
    release_notes: str = Form(""),
    release_file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Upload a product release file and create an inactive release candidate.

    Business rules:
    - Release version belongs to ProductRelease, not Product.
    - Uploaded releases are inactive until explicitly published.

    Side effects:
    - Uploads the release file to Cloudflare R2.
    - Creates a ProductRelease record.

    Invariants/restrictions:
    - Product must exist.
    - Release version format is validated by ProductReleaseService.
    """

    product = db.get(Product, product_id)

    if product is None:
        raise HTTPException(
            status_code=404,
            detail="Product not found",
        )

    original_filename = release_file.filename

    if not original_filename:
        raise HTTPException(
            status_code=400,
            detail="Release file must have a filename.",
        )

    max_upload_bytes = settings.PRODUCT_RELEASE_MAX_UPLOAD_BYTES

    try:
        archive_metadata = inspect_release_archive(
            release_file.file,
            max_bytes=max_upload_bytes,
        )
    except ReleaseArchiveTooLargeError:
        display_limit = _format_release_upload_limit(max_upload_bytes)
        raise HTTPException(
            status_code=413,
            detail=f"Release archive exceeds the {display_limit} limit.",
        )

    storage_service = R2StorageService()

    try:
        uploaded_object = storage_service.upload_product_release_file(
            product_slug=str(product.slug),
            version=version.strip(),
            filename=original_filename,
            file_obj=release_file.file,
        )
    except (BotoCoreError, ClientError):
        return RedirectResponse(
            url=f"/products/{product_id}/releases/new?error=r2_upload_failed",
            status_code=303,
        )

    release_service = ProductReleaseService(db)

    release_service.create_release(
        product_id=product_id,
        version=version,
        release_notes=release_notes.strip() or None,
        storage_provider=uploaded_object.storage_provider,
        storage_key=uploaded_object.storage_key,
        original_filename=original_filename,
        file_size=archive_metadata.file_size,
        sha256_hash=archive_metadata.sha256_hash,
    )

    db.commit()

    return RedirectResponse(
        url=f"/products/{product_id}/releases",
        status_code=303,
    )


@admin_router.get("/products/{product_id}/releases")
def admin_product_releases(
    request: Request,
    product_id: int,
    db: Session = Depends(get_db),
):
    product = db.get(Product, product_id)

    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    release_service = ProductReleaseService(db)
    releases = release_service.list_releases_by_product_id(product_id)
    product_slug = str(product.slug)
    package = get_product_package(product_slug)

    return render(
        request,
        "admin_product_releases.html",
        {
            "product": product,
            "product_id": product_id,
            "releases": releases,
            "package": package,
        },
    )


# *** *** *** *** *** *** *** *** *** ***
router.include_router(admin_router)
