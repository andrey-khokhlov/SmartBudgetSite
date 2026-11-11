from fastapi import Request


def public_navigation_context(request: Request) -> dict[str, object]:
    """Provide shared header state without echoing capability paths or hosts."""
    path = request.url.path
    section: str | None
    if path == "/":
        section = "about"
    elif path == "/products" or path.startswith(("/products/", "/checkout/")):
        section = "products"
    elif path == "/consultations" or path.startswith("/consultations/checkout/"):
        section = "consultations"
    else:
        section = None

    def language_switch_url(lang: str, query: str | None = None) -> str:
        url = request.url if query is None else request.url.replace(query=query)
        # Query-relative links retain the current path, including protected paths.
        return f"?{url.include_query_params(lang=lang).query}"

    return {
        "public_navigation_section": section,
        "language_switch_url": language_switch_url,
    }
