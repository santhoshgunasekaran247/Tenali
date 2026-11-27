from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app.core.database import SessionLocal
from app.services.seo import build_page, context, render_document, sitemap, unavailable, web_template

router = APIRouter()
HEADERS = {"Cache-Control": "no-store", "Vary": "Host", "X-Content-Type-Options": "nosniff"}


@router.get("/api/seo/metadata", include_in_schema=False)
def metadata(request: Request, path: str = Query(max_length=4000)):
    with SessionLocal() as db:
        try:
            page = build_page(db, request, path)
        except HTTPException as error:
            if error.status_code != 404:
                raise
            page = unavailable(404, "Page not found")
    return JSONResponse(page.metadata(), status_code=page.status, headers=HEADERS)


@router.api_route("/seo/pages/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
def document(request: Request, path: str):
    url = "/" + path
    if request.url.query:
        url += "?" + request.url.query
    with SessionLocal() as db:
        try:
            if path == "robots.txt":
                _, base, _ = context(db, request, "/")
                body = ("User-agent: *\nDisallow: /api/\nDisallow: /seo/\n"
                        f"Sitemap: {base}/sitemap.xml\n")
                return Response(body, media_type="text/plain", headers=HEADERS)
            if path == "sitemap.xml" or path.endswith("/sitemap.xml"):
                return Response(sitemap(db, request, url), media_type="application/xml", headers=HEADERS)
            page = build_page(db, request, url)
        except HTTPException as error:
            if error.status_code not in {403, 404}:
                raise
            page = unavailable(404, "Page not found")
    headers = {**HEADERS, "X-Robots-Tag": "index, follow" if page.indexable else "noindex, follow"}
    return HTMLResponse(render_document(page, web_template(), url), status_code=page.status, headers=headers)
