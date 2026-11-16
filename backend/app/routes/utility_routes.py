import traceback
import os
import socket
import ipaddress
from urllib.parse import urlsplit
import urllib3
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.auth import get_user_from_session
from app.config import APP_ENV

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/status", response_class=HTMLResponse)
def status(request: Request):
    user = get_user_from_session(request)
    return templates.TemplateResponse(
        "status.html",
        {"request": request, "user": user, "env": APP_ENV, "python": "3.11", "service": "backend"},
    )


# Operators must explicitly approve which external resource hosts can be fetched.
# An empty allowlist safely disables external fetching until configured.
def permitted_resource_hosts():
    return {host.strip().lower() for host in os.getenv("RESOURCE_IMPORT_ALLOWED_HOSTS", "").split(",") if host.strip()}


def fetch_external_resource(url: str) -> str:
    """Fetch a small preview only from explicitly approved public HTTPS hosts.

    Pin the connection to the verified IP so a DNS rebinding between checking
    and connecting cannot redirect the request onto an internal service.
    """
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError("Invalid URL")
    if (parsed.scheme != "https" or not host or parsed.username is not None
            or parsed.password is not None or port not in (None, 443)
            or host.lower() not in permitted_resource_hosts()):
        raise ValueError("Only approved HTTPS resource hosts are allowed")
    try:
        address_records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise ValueError("Resource hostname could not be resolved")
    addresses = {record[4][0] for record in address_records}
    if not addresses or any(not ipaddress.ip_address(addr).is_global for addr in addresses):
        raise ValueError("Resource host does not resolve exclusively to public addresses")

    # urllib3 connects to the validated IP, with TLS certificate verification
    # and SNI still matching the approved hostname.
    conn = urllib3.HTTPSConnectionPool(
        sorted(addresses)[0], port=443, maxsize=1, block=True,
        server_hostname=host, assert_hostname=host,
        timeout=urllib3.Timeout(connect=3.0, read=5.0), retries=False,
    )
    response = None
    try:
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        response = conn.request(
            "GET", path, headers={"Host": host, "Accept": "text/plain, text/html"},
            redirect=False, preload_content=False,
        )
        if not 200 <= response.status < 300:
            raise ValueError("Resource request was rejected or redirected")
        content_type = response.headers.get("Content-Type", "").lower()
        if not (content_type.startswith("text/plain") or content_type.startswith("text/html")):
            raise ValueError("Only text resources can be previewed")
        return response.read(2000, decode_content=True).decode("utf-8", errors="replace")
    finally:
        if response is not None:
            response.close()
        conn.close()


@router.get("/resources/import", response_class=HTMLResponse)
def import_resource_get(request: Request, url: str = ""):
    user = get_user_from_session(request)
    body = ""
    error = ""
    if url:
        try:
            body = fetch_external_resource(url)
        except (ValueError, urllib3.exceptions.HTTPError) as exc:
            # Never expose backend addresses or internal exception details.
            error = "Resource import failed: URL is not permitted or unavailable"
    return templates.TemplateResponse(
        "resource_import.html",
        {"request": request, "user": user, "body": body, "url": url, "error": error},
    )


@router.post("/resources/import", response_class=HTMLResponse)
def import_resource_post(request: Request, url: str = Form(...)):
    return import_resource_get(request, url)


@router.get("/error", response_class=HTMLResponse)
def trigger_error(request: Request):
    try:
        x = 1 / 0
        return {"x": x}
    except Exception:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "details": traceback.format_exc()},
            status_code=500,
        )
