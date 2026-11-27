import json
import logging
import os
import re
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import text

from app.services.catalog_service import CatalogService
from app.services import policies
from app.services.storefront_access import ensure_storefront_enabled
from app.services.tenant_context import company_by_slug, host_company, platform_host

PLATFORM_TITLE = "Tenali | Inventory, billing, accounts and your online shop"
PLATFORM_DESCRIPTION = (
    "Manage stock, purchases, sales, accounts and your own online shop together, "
    "with AI help beside your everyday business work."
)
PRIVATE_PATHS = ("/portal", "/platform", "/account", "/login", "/register", "/cart", "/checkout", "/social-login")
logger = logging.getLogger(__name__)


@dataclass
class SeoPage:
    title: str = PLATFORM_TITLE
    description: str = PLATFORM_DESCRIPTION
    canonical: str | None = None
    image: str | None = None
    kind: str = "website"
    indexable: bool = False
    status: int = 200
    body: str = ""
    structured_data: list[dict] = field(default_factory=list)

    def metadata(self):
        return {key: value for key, value in vars(self).items() if key != "body"}


def public_origin(request: Request) -> str:
    configured = os.getenv("TENALI_PUBLIC_ORIGIN", "").rstrip("/")
    base = os.getenv("TENALI_BASE_DOMAIN", "").strip(".")
    return configured or ("https://" + base if base else str(request.base_url).rstrip("/"))


def absolute_image(value: str | None, origin: str) -> str | None:
    if not value:
        return None
    if re.fullmatch(r"/api/(?:company/assets/[0-9a-f-]+|public-images/[0-9a-f-]+/[0-9a-f-]+)", value, re.IGNORECASE):
        return origin + value
    try:
        parsed = urlsplit(value)
    except ValueError:
        logger.warning("Omitting a malformed public image URL from search metadata")
        return None
    if parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username and not parsed.password:
        return value
    if not parsed.scheme and not parsed.netloc and not parsed.query and not parsed.fragment and ".." not in parsed.path.split("/"):
        normalized = value.lstrip("/").removeprefix("assets/")
        if normalized:
            return origin + "/api/catalog-assets/" + quote(normalized, safe="/")
    return None


def plain(value: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", value or "")).strip()


def context(db, request: Request, path: str):
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        raise HTTPException(422, "Use a site-relative page path")
    tenant = host_company(db, request)
    if not tenant and not platform_host(request):
        raise HTTPException(404, "This domain is not configured for a workspace")
    match = re.match(r"^/c/([a-z0-9-]+)(?=/|$)", path)
    if match:
        selected = company_by_slug(db, match[1])
        if not selected or (tenant and str(tenant["id"]) != str(selected["id"])):
            raise HTTPException(404, "Storefront not found")
        tenant = selected
        path = path[match.end():] or "/"
    if not tenant:
        return None, public_origin(request), path
    domain = db.execute(text("""select hostname from tenant_domains
        where company_id=:company and verified_at is not null and hosting_status='active'
        order by created_at,id limit 1"""), {"company": str(tenant["id"])}).scalar_one_or_none()
    base = "https://" + domain if domain else public_origin(request) + "/c/" + tenant["tenant_slug"]
    return str(tenant["id"]), base, path


def scope_catalog(db, company_id: str):
    db.info["tenant_context"] = {"company_id": company_id, "role": "public", "user_id": None}
    connection = db.connection()
    connection.execute(text("select set_config('app.tenant_id',:company,true),set_config('app.actor_user_id','',true)"),
                       {"company": company_id})
    connection.exec_driver_sql("SET LOCAL ROLE tenali_runtime")


def storefront_copy(value: str, company: dict) -> str:
    replacements = {"nickname": company.get("nickname") or company["company_name"],
                    "company_name": company["company_name"], "brand_name": company["company_name"]}
    return re.sub(r"\{([a-z_]+)\}", lambda match: replacements.get(match[1], match[0]), value)


def policy_page(db, request, company_id, base, path):
    parts = path.strip("/").split("/")
    scope = parts[1] if len(parts) > 1 else ("tenant" if company_id else "platform")
    if scope not in {"platform", "tenant"} or len(parts) > 3 or (scope == "tenant" and not company_id):
        return unavailable(404, "Policy not found")
    policy_company = company_id if scope == "tenant" else None
    policy_base = base if policy_company else public_origin(request)
    canonical = policy_base + "/policies/" + scope
    try:
        if len(parts) == 3:
            content = policies.published_document(db, policy_company, parts[2])["content"]
            return SeoPage(title=f'{content["title"]} | {content["business_name"]}',
                           description=f'{content["title"]} for {content["business_name"]}.',
                           canonical=canonical + "/" + parts[2], indexable=True,
                           body=f'<main><h1>{escape(content["title"])}</h1><p>{escape(content["business_name"])}</p>'
                                f'<p>{escape(content["address"])}</p><p>{escape(content["contact_email"])}</p>'
                                f'<div style="white-space:pre-wrap">{escape(content["body"])}</div></main>')
        items = policies.published_list(db, policy_company)["items"]
    except HTTPException as error:
        if error.status_code != 404:
            raise
        return unavailable(404, "Policy not found")
    links = "".join(f'<li><a href="{escape(canonical)}/{item["kind"]}">{escape(item["title"])}</a></li>' for item in items)
    return SeoPage(title="Public policies | Tenali", canonical=canonical, indexable=True,
                   body=f"<main><h1>Published business policies</h1><ul>{links}</ul></main>")


def unavailable(status: int, message: str) -> SeoPage:
    return SeoPage(title=f"{message} | Tenali", description=message, status=status,
                   body=f"<main><h1>{escape(message)}</h1></main>")


def build_page(db, request: Request, url: str) -> SeoPage:
    try:
        parsed = urlsplit(url)
    except ValueError as error:
        raise HTTPException(422, "Use a valid site-relative page path") from error
    if parsed.scheme or parsed.netloc:
        raise HTTPException(422, "Use a site-relative page path")
    company_id, base, path = context(db, request, parsed.path)
    path = path.rstrip("/") or "/"
    query = parse_qs(parsed.query, keep_blank_values=True)
    if any(path == item or path.startswith(item + "/") for item in PRIVATE_PATHS):
        return SeoPage(title="Sign in to Tenali", description="Sign in to your Tenali account.",
                       body="<main><h1>Sign in to Tenali</h1><p>Enable JavaScript to use the application.</p></main>")
    if path == "/policies" or path.startswith("/policies/"):
        page = policy_page(db, request, company_id, base, path)
        if parsed.query:
            page.indexable = False
        return page
    if not company_id:
        if path not in {"/", "/index.html"}:
            return unavailable(404, "Page not found")
        return SeoPage(
            canonical=base + "/", image=base + "/tenali-workspace-preview.jpg", indexable=not bool(parsed.query),
            body=(
                "<main><h1>Your stock, bills and accounts. Your shop. All connected.</h1>"
                f"<p>{escape(PLATFORM_DESCRIPTION)}</p>"
                "<h2>The work you do every day, in one place</h2>"
                "<p>Add products, track stock across stores, record purchase bills, make sales bills "
                "and see who has paid. Record money borrowed or lent and keep track of repayments.</p>"
                "<h2>Your own online shop, connected to your business</h2>"
                "<p>Share products through WhatsApp list enquiries. Connect Razorpay for payments, "
                "Shiprocket or your own delivery, and a domain you own.</p>"
                "<h2>AI help beside your work</h2><p>Prepare drafts and product upload workbooks. "
                "Review the details before saving. AI and online services need setup and access.</p>"
                '<p><a href="/register">Set up your business</a> · <a href="/login">Sign in</a></p>'
                '<p><a href="/#demo">Watch the step-by-step guide</a> · '
                '<a href="/policies/platform">Published platform policies</a></p></main>'
            ),
            structured_data=[{"@context": "https://schema.org", "@type": "Organization", "name": "Tenali",
                              "url": base + "/", "logo": base + "/tenali-logo.png"}],
        )
    try:
        scope_catalog(db, company_id)
        ensure_storefront_enabled(db, company_id)
        catalog = CatalogService(db)
        product = None
        if path.startswith("/products/"):
            product_id = path.removeprefix("/products/")
            try:
                UUID(product_id)
            except ValueError:
                return unavailable(404, "Product not found")
            data = catalog.product_detail(product_id, company_id)
            product = data["product"]
        elif path in {"/", "/index.html", "/brand", "/brand.html"}:
            data = catalog.list(company_id, brand=query.get("brand", [None])[0],
                                category=query.get("category", [None])[0], search=query.get("q", [None])[0])
            if (query.get("brand") and not data["selected_brand"]) or (
                query.get("category", ["all"])[0] != "all" and not data["selected_category"]
            ):
                return unavailable(404, "Collection not found")
        else:
            return unavailable(404, "Page not found")
    except HTTPException as error:
        if error.status_code not in {403, 404}:
            raise
        if error.status_code == 403 and path in {"/", "/index.html"}:
            return unavailable(200, "This storefront is currently unavailable")
        return unavailable(404, "Storefront or product unavailable")
    company = data["company"]
    name = company.get("nickname") or company["company_name"]
    origin = base.split("/c/")[0]
    page = SeoPage(title=f"{name} | Online shop", description=f"Browse products from {name}.",
                   canonical=base + "/", image=absolute_image(company.get("logo_url"), origin), indexable=True)
    crumbs = [{"@type": "ListItem", "position": 1, "name": name, "item": base + "/"}]
    if product:
        page.title = f"{product['name']} | {name}"
        page.description = plain(product.get("description"))[:300] or f"View {product['name']} from {name}."
        page.canonical = base + "/products/" + str(product["id"])
        product_image = absolute_image(product.get("image_url") or next(iter(product.get("gallery", [])), None), origin)
        page.image = product_image or page.image
        page.kind = "product"
        page.body = (f'<main><nav><a href="{escape(base)}/">{escape(name)}</a></nav>'
                     f"<h1>{escape(product['name'])}</h1><p>{escape(plain(product.get('description')))}</p>")
        if product_image:
            page.body += f'<img src="{escape(product_image)}" alt="{escape(product["name"])}" width="600" height="600" style="max-width:100%;height:auto;object-fit:contain">'
        if product.get("selling_price_display"):
            page.body += f'<p>Price (INR): {escape(product["selling_price_display"])}</p>'
        page.body += "</main>"
        schema = {"@context": "https://schema.org", "@type": "Product", "name": product["name"],
                  "description": page.description, "url": page.canonical}
        if product_image:
            schema["image"] = [product_image]
        if product.get("brand_name"):
            schema["brand"] = {"@type": "Brand", "name": product["brand_name"]}
        # A catalogue price is not necessarily a checkout offer. Do not promise availability or payment.
        page.structured_data.append(schema)
        crumbs.append({"@type": "ListItem", "position": 2, "name": product["name"], "item": page.canonical})
    else:
        selection = data["selected_category"] or data["selected_brand"]
        if path in {"/brand", "/brand.html"}:
            filters = {key: query[key][0] for key in ("brand", "category") if key in query and query[key][0] != "all"}
            page.canonical = base + "/brand" + ("?" + urlencode(filters) if filters else "")
            heading = (selection.get("category_title") or selection["name"]) if selection else "Products"
            page.title = f"{heading} | {name}"
            page.description = plain((selection or {}).get("category_description") or (selection or {}).get("description"))[:300] or f"Browse {heading.lower()} from {name}."
            crumbs.append({"@type": "ListItem", "position": 2, "name": heading, "item": page.canonical})
        else:
            home = (company.get("storefront_content") or {}).get("home") or {}
            page.title = storefront_copy(home.get("browser_title") or f"{name} | Online shop", company)
            page.description = plain(storefront_copy(home.get("hero_description") or page.description, company))[:300]
            heading = storefront_copy(" ".join(filter(None, [home.get("hero_heading_first"), home.get("hero_heading_second")])) or name, company)
            page.structured_data.append({"@context": "https://schema.org", "@type": "Organization",
                                         "name": company["company_name"], "url": base + "/"})
        page.body = f"<main><h1>{escape(heading)}</h1><p>{escape(page.description)}</p><ul>"
        for item in data["categories"]:
            if not item["category_slug"]:
                continue
            href = base + "/brand?" + urlencode({"category": item["category_slug"]})
            page.body += f'<li><a href="{escape(href)}">{escape(item["category_title"])}</a></li>'
        for item in data["brands"]:
            if not item["code"]:
                continue
            href = base + "/brand?" + urlencode({"brand": item["code"]})
            page.body += f'<li><a href="{escape(href)}">{escape(item["name"])}</a></li>'
        for item in data["products"]:
            page.body += f'<li><a href="{escape(base)}/products/{item["id"]}">{escape(item["name"])}</a></li>'
        page.body += (f'</ul><a href="{escape(base)}/brand">Browse all products</a> · '
                      f'<a href="{escape(base)}/policies/tenant">Published store policies</a></main>')
    page.structured_data.append({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": crumbs})
    if parsed.query:
        page.indexable = not any(key not in {"brand", "category"} for key in query)
    return page


def render_document(page: SeoPage, template: str, url: str | None = None) -> str:
    robots = "index,follow" if page.indexable else "noindex,follow"
    tags = [
        f"<title>{escape(page.title)}</title>",
        f'<meta name="description" content="{escape(page.description)}">',
        f'<meta name="robots" content="{robots}">',
        f'<meta property="og:title" content="{escape(page.title)}">',
        f'<meta property="og:description" content="{escape(page.description)}">',
        f'<meta property="og:type" content="{page.kind}">',
        f'<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:title" content="{escape(page.title)}">',
        f'<meta name="twitter:description" content="{escape(page.description)}">',
    ]
    if page.canonical:
        tags.extend([f'<link rel="canonical" href="{escape(page.canonical)}">',
                     f'<meta property="og:url" content="{escape(page.canonical)}">'])
    if page.image:
        tags.extend([f'<meta property="og:image" content="{escape(page.image)}">',
                     f'<meta name="twitter:image" content="{escape(page.image)}">'])
    for data in page.structured_data:
        encoded = json.dumps(data, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        tags.append(f'<script type="application/ld+json" data-tenali-seo>{encoded}</script>')
    template = re.sub(r"<title>.*?</title>", "", template, flags=re.DOTALL)
    template = re.sub(r'<meta\b[^>]*(?:name|property)=["\'](?:description|robots|og:[^"\']+|twitter:[^"\']+)["\'][^>]*>', "", template, flags=re.IGNORECASE)
    template = template.replace("</head>", "\n".join(tags) + "\n</head>")
    if url is not None:
        template = template.replace("<html", f'<html data-tenali-seo-path="{escape(url)}"', 1)
    return template.replace('<div id="root"></div>', f'<div id="root">{page.body}</div>')


def web_template() -> str:
    root = Path(os.getenv("TENALI_WEB_ROOT") or Path(__file__).resolve().parents[3] / "web" / "dist")
    path = root / "index.html"
    if not path.is_file():
        raise HTTPException(503, "Build the frontend and configure TENALI_WEB_ROOT before serving public pages")
    template = path.read_text(encoding="utf-8")
    if '<div id="root"></div>' not in template:
        raise HTTPException(503, "The frontend entry does not contain the expected application root")
    return template


def sitemap(db, request: Request, url: str) -> str:
    parsed = urlsplit(url)
    company_id, base, path = context(db, request, parsed.path.removesuffix("/sitemap.xml") or "/")
    if path != "/":
        raise HTTPException(404, "Sitemap not found")
    published = policies.published_list(db, company_id)["items"]
    if not company_id:
        urls = [base + "/", base + "/policies/platform"]
        urls.extend(base + "/policies/platform/" + item["kind"] for item in published)
    else:
        scope_catalog(db, company_id)
        ensure_storefront_enabled(db, company_id)
        page_value = parse_qs(parsed.query).get("page", [None])[0]
        count = db.execute(text("""select count(*) from products
            where company_id=:company and is_active and catalog_visible"""), {"company": company_id}).scalar_one()
        if page_value is None and count > 1000:
            entries = "".join(f"<sitemap><loc>{escape(base)}/sitemap.xml?page={number}</loc></sitemap>"
                              for number in range(1, (count + 999) // 1000 + 1))
            return f'<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</sitemapindex>'
        if page_value is not None and (not page_value.isascii() or not page_value.isdigit() or len(page_value) > 8 or int(page_value) < 1):
            raise HTTPException(422, "Invalid sitemap page")
        page = int(page_value or "1")
        if page > max(1, (count + 999) // 1000):
            raise HTTPException(404, "Sitemap page not found")
        rows = db.execute(text("""select id from products where company_id=:company and is_active and catalog_visible
            order by id limit 1000 offset :offset"""), {"company": company_id, "offset": (page - 1) * 1000}).scalars()
        urls = ([base + "/", base + "/brand", base + "/policies/tenant"] if page == 1 else []) + [base + "/products/" + str(item) for item in rows]
        if page == 1:
            urls.extend(base + "/policies/tenant/" + item["kind"] for item in published)
    entries = "".join(f"<url><loc>{escape(url)}</loc></url>" for url in urls)
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>'
