"""HTTP API used by the frontend (run with ``uvicorn cbv.main:app``).

Every book route works on the library of the reader making the request: the local reader's, or,
when the app is hosted (CBV_HOSTED=1), the signed-in account's.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import BackgroundTasks, Cookie, Depends, FastAPI, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from starlette.concurrency import run_in_threadpool

from . import billing, config, copyright, library, licenses, mail, ratelimit, users
from .ratelimit import Limit

log = logging.getLogger(__name__)

SESSION_COOKIE = "cbv_session"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if config.HOSTED and not config.SMTP_HOST:
        log.warning("CBV_HOSTED is on but CBV_SMTP_HOST isn't set: sign-up and reset mails only go to the log")
    if config.HOSTED and not config.COPYRIGHT_EMAIL:
        log.warning("CBV_HOSTED is on but CBV_COPYRIGHT_EMAIL isn't set: copyright notices only go to the log")
    if config.HOSTED and not (config.OPERATOR and config.OPERATOR_ADDRESS and config.CONTACT_EMAIL and config.COPYRIGHT_AGENT):
        log.warning("CBV_HOSTED is on but CBV_OPERATOR, CBV_OPERATOR_ADDRESS, CBV_CONTACT_EMAIL or CBV_COPYRIGHT_AGENT "
                    "isn't set: the legal pages show blanks where they go")
    paddle = (config.PADDLE_API_KEY, config.PADDLE_CLIENT_TOKEN, config.PADDLE_PRICE, config.PADDLE_WEBHOOK_SECRET)
    if config.HOSTED and any(paddle) and not all(paddle):
        log.warning("Plus isn't on sale: CBV_PADDLE_API_KEY, CBV_PADDLE_CLIENT_TOKEN, CBV_PADDLE_PRICE and "
                    "CBV_PADDLE_WEBHOOK_SECRET are all needed")
    if config.HOSTED and bool(config.ADSENSE_CLIENT) != bool(config.ADSENSE_SLOT):
        log.warning("No ads: CBV_ADSENSE_CLIENT and CBV_ADSENSE_SLOT are both needed")
    library.resume_unfinished()
    yield


app = FastAPI(title="Chess Books Visualizer", lifespan=lifespan)

# How often a hosted site lets each client try (see ratelimit.py).
LOGINS = Limit(20, 600)  # per client
WRONG_PASSWORDS = Limit(10, 900)  # per account, from anywhere
SIGNUPS = Limit(10, 3600)  # per client
MAILS = Limit(5, 3600)  # per email address: confirmations, resets, "you already have an account"
MAIL_REQUESTS = Limit(10, 3600)  # per client
PASSWORD_CHECKS = Limit(10, 3600)  # per account (deleting it)
UPLOADS = Limit(30, 3600)  # per account
NOTICES = Limit(5, 3600)  # per client
# The largest request body besides a book upload (a trainer record is at most 10 MB).
MAX_BODY = 16 * 2**20
# The zoom the app shows PDF pages at: a hosted site renders (and keeps) only that one.
PAGE_ZOOM = 2.0


class BodyLimit:
    """A hosted site reads no request body larger than it takes: a book upload up to
    config.MAX_UPLOAD_MB (and a little for the form around it), anything else up to MAX_BODY. It
    stops a body as it arrives, before it all lands on disk or in memory."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        upload = scope["type"] == "http" and scope["method"] == "POST" and scope["path"] == "/api/books"
        if scope["type"] != "http" or not config.HOSTED or (upload and not config.MAX_UPLOAD_MB):
            return await self.app(scope, receive, send)
        limit = config.MAX_UPLOAD_MB * 2**20 + 2**20 if upload else MAX_BODY
        length = dict(scope["headers"]).get(b"content-length")
        if length and length.isdigit() and int(length) > limit:
            return await JSONResponse({"detail": "too_big"}, status_code=413)(scope, receive, send)
        received = 0

        async def limited():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > limit:
                raise HTTPException(status_code=413, detail="too_big")
            return message

        await self.app(scope, limited, send)


app.add_middleware(BodyLimit)


@app.exception_handler(ratelimit.TooMany)
def too_many(_request: Request, e: ratelimit.TooMany) -> JSONResponse:
    return JSONResponse({"detail": "too_many"}, status_code=429, headers={"Retry-After": str(e.retry_after)})


def _address(email: str) -> str:
    """An email address as an account keeps it, to count the tries for it."""
    return (email or "").strip().lower()[:254]


def _client(request: Request) -> str:
    """Who a request comes from (behind a proxy, uvicorn --proxy-headers gives the real address)."""
    return ratelimit.client(request.client.host if request.client else None)


@app.middleware("http")
async def own_pages_only(request: Request, call_next):
    """A hosted site changes things only for requests from its own pages: another site can't make a
    signed-in browser upload, change or delete anything (the SameSite cookie stops most already)."""
    if config.HOSTED and request.method not in ("GET", "HEAD", "OPTIONS"):
        site = urlsplit(config.PUBLIC_URL)
        origin = request.headers.get("origin")
        if (origin and origin != f"{site.scheme}://{site.netloc}") or request.headers.get("sec-fetch-site") == "cross-site":
            return PlainTextResponse("requests from other sites are refused", status_code=403)
    return await call_next(request)


def current_user(cbv_session: Annotated[str | None, Cookie()] = None) -> str:
    """Whose library a request reads: the local reader's, or the signed-in account's."""
    if not config.HOSTED:
        return library.LOCAL
    user = users.session_user(cbv_session)
    if user is None:
        raise HTTPException(status_code=401)
    return user.id


Reader = Annotated[str, Depends(current_user)]


def current_account(cbv_session: Annotated[str | None, Cookie()] = None) -> users.User:
    """The signed-in account of a hosted site."""
    user = users.session_user(cbv_session) if config.HOSTED else None
    if user is None:
        raise HTTPException(status_code=401)
    return user


Account = Annotated[users.User, Depends(current_account)]


def _found(fn, *args):
    try:
        return fn(*args)
    except library.NotFound:
        raise HTTPException(status_code=404)
    except library.Disabled:
        # 451, Unavailable For Legal Reasons: disabled after a copyright notice.
        raise HTTPException(status_code=451, detail="disabled")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/licenses")
def server_licenses() -> list[dict]:
    return licenses.server_packages()


# --- Accounts (hosted app only) ---

class SignUp(BaseModel):
    email: str
    password: str
    lang: str = "en"
    terms: bool = False  # accepts the terms of use, having been shown the privacy notice


class SignIn(BaseModel):
    email: str
    password: str


class Email(BaseModel):
    email: str


class Link(BaseModel):
    token: str


class NewPassword(BaseModel):
    token: str
    password: str


class Password(BaseModel):
    password: str


def _hosted() -> None:
    if not config.HOSTED:
        raise HTTPException(status_code=404)


Hosted = Depends(_hosted)


def _signed_in(token: str) -> Response:
    response = Response(status_code=204)
    response.set_cookie(SESSION_COOKIE, token, max_age=users.SESSION_DAYS * 86400, path="/",
                        httponly=True, secure=config.COOKIE_SECURE, samesite="lax")
    return response


def _signed_out() -> Response:
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, secure=config.COOKIE_SECURE, samesite="lax")
    return response


def _send(message: users.Mail | None) -> None:
    if message is not None:
        mail.send(message.to, message.kind, message.lang, link=message.link)


def _refused(e: users.AuthError, status: int = 400):
    return HTTPException(status_code=status, detail=e.code)


@app.get("/api/legal", dependencies=[Hosted])
def legal() -> dict:
    """What a hosted site's terms, privacy notice and copyright policy fill their blanks with: who
    runs it, and the numbers its rules go by. Unset settings are null (the pages show a blank)."""
    return {
        "site": config.PUBLIC_URL, "operator": config.OPERATOR, "address": config.OPERATOR_ADDRESS,
        "contact": config.CONTACT_EMAIL, "copyright_email": config.COPYRIGHT_EMAIL, "copyright_agent": config.COPYRIGHT_AGENT,
        "strikes": copyright.STRIKES, "keep_days": copyright.KEEP_DAYS, "wait_days": copyright.WAIT_DAYS,
        "session_days": users.SESSION_DAYS, "unverified_days": users.UNVERIFIED_DAYS, "render_days": library.RENDER_DAYS,
    }


@app.get("/api/auth/me")
def me(cbv_session: Annotated[str | None, Cookie()] = None) -> dict:
    """Whether the app is hosted, and who is signed in (nobody: the local app has no accounts)."""
    if not config.HOSTED:
        return {"hosted": False, "user": None}
    user = users.session_user(cbv_session)
    return {"hosted": True, "user": {"email": user.email} if user else None}


@app.post("/api/auth/signup", status_code=204, dependencies=[Hosted])
def signup(body: SignUp, request: Request, background: BackgroundTasks) -> Response:
    if not body.terms:
        raise HTTPException(status_code=400, detail="terms")
    ratelimit.take("signup", _client(request), SIGNUPS)
    ratelimit.take("mail", _address(body.email), MAILS)
    try:
        background.add_task(_send, users.signup(body.email, body.password, body.lang))
    except users.AuthError as e:
        raise _refused(e)
    return Response(status_code=204)


@app.post("/api/auth/resend", status_code=204, dependencies=[Hosted])
def resend(body: Email, request: Request, background: BackgroundTasks) -> Response:
    ratelimit.take("mail-request", _client(request), MAIL_REQUESTS)
    ratelimit.take("mail", _address(body.email), MAILS)
    background.add_task(_send, users.resend(body.email))
    return Response(status_code=204)


@app.post("/api/auth/verify", status_code=204, dependencies=[Hosted])
def verify(body: Link) -> Response:
    try:
        return _signed_in(users.verify(body.token))
    except users.AuthError as e:
        raise _refused(e)


@app.post("/api/auth/login", status_code=204, dependencies=[Hosted])
def login(body: SignIn, request: Request) -> Response:
    ratelimit.take("login", _client(request), LOGINS)
    email = _address(body.email)
    ratelimit.check("wrong-password", email, WRONG_PASSWORDS)
    try:
        return _signed_in(users.login(body.email, body.password))
    except users.AuthError as e:
        if e.code == "credentials":
            ratelimit.count("wrong-password", email)
        raise _refused(e, 403 if e.code in ("unverified", "closed") else 401)


@app.post("/api/auth/forgot", status_code=204, dependencies=[Hosted])
def forgot(body: Email, request: Request, background: BackgroundTasks) -> Response:
    ratelimit.take("mail-request", _client(request), MAIL_REQUESTS)
    ratelimit.take("mail", _address(body.email), MAILS)
    background.add_task(_send, users.forgot(body.email))
    return Response(status_code=204)


@app.post("/api/auth/reset", status_code=204, dependencies=[Hosted])
def reset(body: NewPassword) -> Response:
    try:
        return _signed_in(users.reset(body.token, body.password))
    except users.AuthError as e:
        raise _refused(e)


@app.post("/api/auth/logout", status_code=204, dependencies=[Hosted])
def logout(cbv_session: Annotated[str | None, Cookie()] = None) -> Response:
    users.logout(cbv_session)
    return _signed_out()


@app.post("/api/auth/delete-account", status_code=204, dependencies=[Hosted])
def delete_account(body: Password, user: Account) -> Response:
    ratelimit.take("password", user.id, PASSWORD_CHECKS)
    try:
        # A subscription to Plus ends with the account: Paddle must hear of it first.
        users.delete(user, body.password, before=billing.end)
    except users.AuthError as e:
        raise _refused(e, 403)
    except billing.Unavailable as e:
        log.error("Plus of %s couldn't be cancelled: %s", user.email, e)
        raise HTTPException(status_code=502, detail="billing")
    return _signed_out()


# --- Plans: free, and Plus (hosted app only; see billing.py) ---

@app.get("/api/plans", dependencies=[Hosted])
def plans() -> dict:
    """What each plan gives, and Plus's price (null: not on sale, or Paddle didn't say). With
    Paddle's client-side token: the page opens the checkout links Paddle sends (its ?_ptxn=…)."""
    return {
        "selling": config.SELLING, "price": billing.price(), "ads": config.ADS, "upload_mb": config.MAX_UPLOAD_MB,
        "paddle": {"token": config.PADDLE_CLIENT_TOKEN, "sandbox": config.PADDLE_SANDBOX} if config.SELLING else None,
        "free": {"books": config.MAX_BOOKS, "storage_mb": config.MAX_STORAGE_MB,
                 "trainer_sessions": config.FREE_TRAINER_SESSIONS if config.SELLING else 0},
        "plus": {"books": config.PLUS_MAX_BOOKS, "storage_mb": config.PLUS_MAX_STORAGE_MB},
    }


@app.get("/api/plan", dependencies=[Hosted])
def account_plan(user: Account) -> dict:
    """The signed-in account's plan: what it may still do, the ads it sees, and how to buy Plus."""
    plan = billing.plan(user.id)
    return {
        "plus": plan.plus, "status": plan.status, "until": plan.until, "cancel_at": plan.cancel_at,
        "selling": config.SELLING, "manage": config.SELLING and plan.customer is not None,
        "checkout": billing.checkout(user),
        "ads": {"client": config.ADSENSE_CLIENT, "slot": config.ADSENSE_SLOT} if config.ADS and not plan.plus else None,
        "trainer_left": billing.trainer_left(user.id),
    }


@app.post("/api/billing/portal", dependencies=[Hosted])
def billing_portal(user: Reader) -> dict:
    """Links into Paddle's customer portal: invoices, the card, cancelling."""
    try:
        links = billing.portal(user)
    except billing.Unavailable as e:
        log.error("Paddle's customer portal: %s", e)
        raise HTTPException(status_code=502, detail="billing")
    if links is None:
        raise HTTPException(status_code=404)
    return links


@app.post("/api/billing/webhook", dependencies=[Hosted])
async def billing_webhook(request: Request) -> Response:
    """What Paddle tells of each subscription, signed with the notification destination's secret."""
    if not config.SELLING:
        raise HTTPException(status_code=404)
    body = await request.body()
    if not billing.verify(body, request.headers.get("paddle-signature")):
        raise HTTPException(status_code=401)
    try:
        event = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400)
    await run_in_threadpool(billing.apply, event)
    return Response(status_code=200)


@app.get("/ads.txt", response_class=PlainTextResponse)
def ads_txt() -> str:
    """Who may sell the site's ad space (Google's ads.txt; Caddy passes /ads.txt to the app)."""
    if not config.ADS:
        raise HTTPException(status_code=404)
    publisher = config.ADSENSE_CLIENT.removeprefix("ca-")
    return f"google.com, {publisher}, DIRECT, f08c47fec0942fa0\n"


# --- Books ---

@app.get("/api/books")
def list_books(user: Reader) -> list[dict]:
    return library.list_books(user)


@app.post("/api/books")
def upload_book(user: Reader, file: UploadFile, rights: Annotated[bool, Form()] = False) -> dict:
    if config.HOSTED:
        # Whoever uploads a book to the site says it is theirs to use (when is kept with it).
        if not rights:
            raise HTTPException(status_code=400, detail="rights")
        ratelimit.take("upload", user, UPLOADS)
    try:
        with library.receive(file.file) as upload:
            # A file blocked after a copyright notice can't come back.
            if config.HOSTED and copyright.is_blocked(upload.sha256):
                raise HTTPException(status_code=451, detail="blocked")
            return library.import_book(user, file.filename or "book", upload, declared=config.HOSTED,
                                       limits=billing.limits(user))
    except library.Refused as e:
        raise HTTPException(status_code=e.status, detail=e.why)


@app.get("/api/usage", dependencies=[Hosted])
def usage(user: Reader) -> dict:
    """How much of what an account may keep it uses (0: no limit)."""
    books, used = library.usage(user)
    max_books, max_mb = billing.limits(user)
    return {"books": books, "bytes": used, "max_books": max_books,
            "max_bytes": max_mb * 2**20, "max_upload": config.MAX_UPLOAD_MB * 2**20}


@app.get("/api/books/{book_id}")
def get_book(user: Reader, book_id: str) -> dict:
    return _found(library.get_book, user, book_id)


@app.delete("/api/books/{book_id}", status_code=204)
def delete_book(user: Reader, book_id: str) -> None:
    _found(library.delete_book, user, book_id)


@app.post("/api/books/{book_id}/analyze", status_code=202)
def reanalyze(user: Reader, book_id: str) -> dict:
    _found(library.start_analysis, user, book_id)
    return library.get_book(user, book_id)


@app.get("/api/books/{book_id}/analysis")
def get_analysis(user: Reader, book_id: str) -> dict:
    return _found(library.analysis, user, book_id)


@app.get("/api/books/{book_id}/layout")
def get_layout(user: Reader, book_id: str) -> dict:
    return _found(library.layout, user, book_id)


@app.get("/api/books/{book_id}/pages/{page}.png")
def get_page_image(user: Reader, book_id: str, page: int, zoom: float = Query(PAGE_ZOOM, ge=0.5, le=4.0)) -> FileResponse:
    # Rounded so that the cache does not fill up with near-identical renders.
    zoom = round(zoom * 2) / 2
    if config.HOSTED and zoom != PAGE_ZOOM:
        raise HTTPException(status_code=422, detail="zoom")
    path = _found(library.page_image, user, book_id, page, zoom)
    # Private: a reader's pages are kept by their own browser, never by a shared cache.
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/books/{book_id}/pages/{page}/marks")
def get_page_marks(user: Reader, book_id: str, page: int) -> list:
    return _found(library.page_marks, user, book_id, page)


@app.get("/api/books/{book_id}/epub/{path:path}")
def get_epub_file(user: Reader, book_id: str, path: str) -> Response:
    data, media_type = _found(library.epub_file, user, book_id, path)
    # Book files come from outside: never let them run scripts in the app's origin.
    return Response(data, media_type=media_type,
                    headers={"Content-Security-Policy": "script-src 'none'", "Cache-Control": "private"})


class DiagramFix(BaseModel):
    key: str
    placement: str
    turn: str | None = None


@app.put("/api/books/{book_id}/diagrams", status_code=202)
def correct_diagram(user: Reader, book_id: str, fix: DiagramFix) -> dict:
    if fix.turn not in (None, "w", "b"):
        raise HTTPException(status_code=422, detail="turn must be w or b")
    try:
        return _found(library.correct_diagram, user, book_id, fix.key, fix.placement, fix.turn)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.get("/api/books/{book_id}/move-fixes")
def get_move_fixes(user: Reader, book_id: str) -> list:
    return _found(library.move_fixes, user, book_id)


@app.put("/api/books/{book_id}/move-fixes", status_code=202)
def put_move_fixes(user: Reader, book_id: str, fixes: list[dict]) -> dict:
    try:
        return _found(library.save_move_fixes, user, book_id, fixes)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.get("/api/books/{book_id}/user/{name}")
def get_user_data(user: Reader, book_id: str, name: str) -> dict:
    if name not in library.USER_DATA:
        raise HTTPException(status_code=404)
    return _found(library.user_data, user, book_id, name)


@app.put("/api/books/{book_id}/user/{name}", status_code=204)
def put_user_data(user: Reader, book_id: str, name: str, data: dict) -> Response:
    try:
        _found(library.save_user_data, user, book_id, name, data)
    except ValueError as e:
        raise HTTPException(status_code=413, detail=str(e))
    return Response(status_code=204)


@app.get("/api/trainer")
def get_trainer(user: Reader) -> dict:
    return library.trainer_record(user)


@app.put("/api/trainer", status_code=204)
def put_trainer(user: Reader, record: dict) -> None:
    try:
        library.save_trainer_record(user, record)
    except ValueError as e:
        raise HTTPException(status_code=413, detail=str(e))


@app.get("/api/trainer/books")
def get_trainer_books(user: Reader) -> list:
    return library.trainer_books(user)


@app.post("/api/trainer/session")
def new_trainer_session(user: Reader, test: bool = False) -> dict:
    # A free account has a few sessions to try the trainer (when Plus is on sale): 402, Payment Required.
    if billing.trainer_left(user) == 0:
        raise HTTPException(status_code=402, detail="plus")
    session = library.trainer_session(user, test=test)
    if session["blocks"]:
        billing.trainer_started(user)
    return session


@app.get("/api/books/{book_id}/games/{game_id}.pgn", response_class=PlainTextResponse)
def get_pgn(user: Reader, book_id: str, game_id: str) -> str:
    return _found(library.game_pgn, user, book_id, game_id)


# --- Copyright (hosted app only; see copyright.py) ---

class _Form(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class Notice(_Form):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: str = Field("", max_length=50)
    address: str = Field(min_length=1, max_length=500)
    claimant: str = Field(min_length=1, max_length=200)
    work: str = Field(min_length=1, max_length=2000)
    location: str = Field("", max_length=2000)
    sha256: str | None = Field(None, pattern=r"^[0-9a-f]{64}$")
    signature: str = Field(min_length=1, max_length=200)
    # The two statements of copyright.STATEMENTS["notice"]: a notice must make both.
    good_faith: Literal[True]
    accurate: Literal[True]
    lang: str = "en"


class CounterNotice(_Form):
    name: str = Field(min_length=1, max_length=200)
    address: str = Field(min_length=1, max_length=500)
    phone: str = Field(min_length=1, max_length=50)
    reason: str = Field("", max_length=2000)
    signature: str = Field(min_length=1, max_length=200)
    # copyright.STATEMENTS["counter"]
    good_faith: Literal[True]
    jurisdiction: Literal[True]
    lang: str = "en"


@app.post("/api/copyright-notices", status_code=201, dependencies=[Hosted])
def copyright_notice(body: Notice, request: Request, background: BackgroundTasks) -> dict:
    """A rights holder's notice about books uploaded here (anyone may send one)."""
    ratelimit.take("notice", _client(request), NOTICES)
    notice_id = copyright.submit_notice(body.model_dump(), body.lang)
    background.add_task(copyright.tell_agent, "notice", notice_id)
    return {"id": notice_id}


@app.post("/api/books/{book_id}/counter-notice", status_code=204, dependencies=[Hosted])
def counter_notice(user: Reader, book_id: str, body: CounterNotice, background: BackgroundTasks) -> Response:
    """The answer of a disabled book's owner to the notice that disabled it."""
    try:
        counter_id = _found(copyright.counter_notice, user, book_id, body.model_dump(), body.lang)
    except copyright.Refused as e:
        raise HTTPException(status_code=409, detail=e.why)
    background.add_task(copyright.tell_agent, "counter", counter_id)
    return Response(status_code=204)
