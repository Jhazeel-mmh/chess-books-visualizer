"""Copyright notices, and what follows them, for the hosted app.

Mexico's LFDA (arts. 114 Septies and 114 Octies) and the US DMCA (17 U.S.C. § 512) shield a site from
what its users upload if it takes down what a rights holder's notice points to, lets the uploader
answer with a counter-notice, and closes the accounts of repeat infringers. The EU's DSA (art. 16)
also asks for a way to send notices online. So:

- anyone can send a notice with the form at /copyright; it reaches the site's copyright agent;
- the agent, with scripts/admin.py, finds the uploads it names (by title, or by the file's
  fingerprint), disables them, and may block the file so that nobody can upload it again;
- the owner of a disabled book is told why by mail, and can't open it any more. They can send a
  counter-notice: the agent forwards it to whoever sent the notice and, unless that person shows
  within WAIT_DAYS business days that they went to court (or to an authority, or to mediation),
  restores the book;
- each notice that disabled books of an account is a strike against its email until the books are
  restored: at STRIKES strikes the account is closed;
- disabled books nobody answered for, and closed accounts' libraries, are deleted after KEEP_DAYS.

Kept in the accounts' database (<data>/users.db). Takedowns outlive the accounts they were against,
so a new account with the same email keeps its strikes.
"""

from __future__ import annotations

import hashlib
import logging
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from . import billing, config, library, mail, users

log = logging.getLogger(__name__)

STRIKES = 3  # an account is closed when it has this many
KEEP_DAYS = 30  # disabled books with no counter-notice, and closed accounts' libraries, are kept this long
# Business days between forwarding a counter-notice and restoring the book. The LFDA (art. 114 Octies
# III) gives whoever sent the notice up to 15 to start an action; the DMCA asks for 10 to 14.
WAIT_DAYS = 15

# What the sender of a notice, and of a counter-notice, declares. The forms show the same words
# (frontend/src/locales/*.json, "copyright"): keep them alike.
STATEMENTS = {
    "notice": {
        "en": ["I believe in good faith that the use of the material described is not authorized by the rights "
               "holder, its agent, or the law.",
               "The information in this notice is accurate and, under penalty of perjury, I am the rights holder or "
               "authorized to act on their behalf."],
        "es": ["Creo de buena fe que el uso del material descrito no está autorizado por el titular de los derechos, "
               "su representante ni la ley.",
               "La información de este aviso es exacta y, bajo protesta de decir verdad, soy el titular de los derechos "
               "o estoy autorizado para actuar en su nombre."],
    },
    "counter": {
        "en": ["Under penalty of perjury, I believe in good faith that the material was disabled as a result of a "
               "mistake or misidentification, or that I have the right to use it.",
               "I consent to the jurisdiction of the federal court for the district of my address (or, if my address "
               "is outside the United States, of any district where this service may be found), and I will accept "
               "service of process from whoever sent the notice or their agent."],
        "es": ["Bajo protesta de decir verdad, creo de buena fe que el material se deshabilitó por un error o una "
               "identificación equivocada, o que tengo derecho a usarlo.",
               "Acepto la jurisdicción del tribunal federal del distrito de mi domicilio (o, si mi domicilio está fuera "
               "de Estados Unidos, de cualquier distrito donde se encuentre este servicio), y aceptaré las "
               "notificaciones judiciales de quien envió el aviso o de su representante."],
    },
}

_LABELS = {
    "en": {"received": "Received", "from": "From", "phone": "Phone", "address": "Address", "claimant": "On behalf of",
           "work": "Work", "location": "Where", "sha256": "File fingerprint (SHA-256)", "signature": "Signed",
           "declared": "Declared", "name": "Name", "book": "Book", "disabled": "Disabled",
           "reason": "Why"},
    "es": {"received": "Recibido", "from": "De", "phone": "Teléfono", "address": "Domicilio", "claimant": "En nombre de",
           "work": "Obra", "location": "Dónde", "sha256": "Huella del archivo (SHA-256)", "signature": "Firma",
           "declared": "Declaró", "name": "Nombre", "book": "Libro", "disabled": "Deshabilitado",
           "reason": "Motivo"},
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notices (
    id INTEGER PRIMARY KEY,
    received_at TEXT NOT NULL,
    lang TEXT NOT NULL,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL,
    address TEXT NOT NULL,
    claimant TEXT NOT NULL,                -- the rights holder it is sent for
    work TEXT NOT NULL,
    location TEXT NOT NULL,                -- anything else that helps find the uploads
    sha256 TEXT,                           -- the file's fingerprint, if they had the file
    signature TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',    -- new, done or rejected
    note TEXT
);
CREATE TABLE IF NOT EXISTS takedowns (
    id INTEGER PRIMARY KEY,
    notice_id INTEGER NOT NULL REFERENCES notices(id),
    user_id TEXT NOT NULL,
    email TEXT NOT NULL,
    book_id TEXT NOT NULL,
    title TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    disabled_at TEXT NOT NULL,
    restored_at TEXT,
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS takedowns_email ON takedowns(email);
CREATE TABLE IF NOT EXISTS counter_notices (
    id INTEGER PRIMARY KEY,
    takedown_id INTEGER NOT NULL UNIQUE REFERENCES takedowns(id),
    received_at TEXT NOT NULL,
    lang TEXT NOT NULL,
    name TEXT NOT NULL,
    address TEXT NOT NULL,
    phone TEXT NOT NULL,
    reason TEXT NOT NULL,
    signature TEXT NOT NULL,
    forwarded_at TEXT
);
CREATE TABLE IF NOT EXISTS blocked (
    sha256 TEXT PRIMARY KEY,
    notice_id INTEGER REFERENCES notices(id),
    blocked_at TEXT NOT NULL
);
"""


class Refused(Exception):
    """Why something can't be done: a short code for the API, or a sentence for scripts/admin.py."""

    def __init__(self, why: str):
        super().__init__(why)
        self.why = why


@dataclass
class Upload:
    """A book in some account's library, as the copyright agent sees it (never its contents)."""
    user_id: str
    email: str
    book_id: str
    title: str
    filename: str
    imported_at: str
    declared_at: str | None
    sha256: str | None
    disabled: bool


_ready: set[str] = set()


@contextmanager
def _db():
    with users.connect() as conn:
        path = str(library.DATA_DIR / "users.db")
        if path not in _ready:
            conn.executescript(_SCHEMA)
            _ready.add(path)
        yield conn


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- What arrives through the site ---

def submit_notice(notice: dict, lang: str) -> int:
    """Keeps a notice sent with the form (its fields are already checked); its number."""
    with _db() as conn:
        return conn.execute(
            "INSERT INTO notices (received_at, lang, name, email, phone, address, claimant, work, location, sha256, signature) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_now().isoformat(), _lang(lang), notice["name"], notice["email"].lower(), notice.get("phone") or "",
             notice["address"], notice["claimant"], notice["work"], notice.get("location") or "",
             notice.get("sha256") or None, notice["signature"])).lastrowid


def counter_notice(user_id: str, book_id: str, counter: dict, lang: str) -> int:
    """Keeps the counter-notice the owner of a disabled book sent; its number."""
    why = library.get_book(user_id, book_id).get("disabled")
    if not why:
        raise Refused("not_disabled")
    with _db() as conn:
        takedown = conn.execute("SELECT id FROM takedowns WHERE id = ? AND user_id = ? AND book_id = ? AND restored_at IS NULL",
                                (why.get("takedown"), user_id, book_id)).fetchone()
        if takedown is None:
            raise Refused("not_disabled")
        if conn.execute("SELECT 1 FROM counter_notices WHERE takedown_id = ?", (takedown["id"],)).fetchone():
            raise Refused("sent")
        now = _now().isoformat()
        counter_id = conn.execute(
            "INSERT INTO counter_notices (takedown_id, received_at, lang, name, address, phone, reason, signature) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (takedown["id"], now, _lang(lang), counter["name"], counter["address"], counter["phone"], counter["reason"],
             counter["signature"])).lastrowid
    library.set_disabled(user_id, book_id, {**why, "counter_at": now})
    return counter_id


def tell_agent(kind: str, item_id: int) -> None:
    """Sends a notice ("notice") or counter-notice ("counter") that just arrived to the copyright agent."""
    if kind == "notice":
        text, reply_to = describe_notice(item_id), notice(item_id)["email"]
    else:
        text, reply_to = describe_counter(item_id, "en"), _counter(item_id)["owner_email"]
    if not config.COPYRIGHT_EMAIL:
        log.warning("no CBV_COPYRIGHT_EMAIL, so %s #%s only goes to the log:\n%s", kind, item_id, text)
        return
    mail.send(config.COPYRIGHT_EMAIL, kind, "en", reply_to=reply_to, id=item_id, text=text)


def is_blocked(sha256: str) -> bool:
    """Whether a file (by its fingerprint) was blocked after a notice: nobody can upload it."""
    with _db() as conn:
        return conn.execute("SELECT 1 FROM blocked WHERE sha256 = ?", (sha256,)).fetchone() is not None


# --- What the copyright agent does (scripts/admin.py) ---

def notices(everything: bool = False) -> list[dict]:
    """The notices not dealt with yet (or all of them), oldest first."""
    with _db() as conn:
        where = "" if everything else "WHERE status = 'new'"
        return [dict(row) for row in conn.execute(f"SELECT * FROM notices {where} ORDER BY id")]


def notice(notice_id: int) -> dict:
    with _db() as conn:
        row = conn.execute("SELECT * FROM notices WHERE id = ?", (notice_id,)).fetchone()
        if row is None:
            raise Refused(f"there is no notice #{notice_id}")
        takedowns = conn.execute("SELECT * FROM takedowns WHERE notice_id = ? ORDER BY id", (notice_id,)).fetchall()
        blocked = conn.execute("SELECT sha256 FROM blocked WHERE notice_id = ?", (notice_id,)).fetchall()
    return {**dict(row), "takedowns": [dict(t) for t in takedowns], "blocked": [b["sha256"] for b in blocked]}


def describe_notice(notice_id: int) -> str:
    n, label = notice(notice_id), _LABELS["en"]
    return "\n".join([
        f"{label['received']}: {n['received_at']}",
        f"{label['from']}: {n['name']} <{n['email']}>",
        f"{label['phone']}: {n['phone'] or '-'}",
        f"{label['address']}: {n['address']}",
        f"{label['claimant']}: {n['claimant']}",
        f"{label['work']}: {n['work']}",
        f"{label['location']}: {n['location'] or '-'}",
        f"{label['sha256']}: {n['sha256'] or '-'}",
        f"{label['signature']}: {n['signature']}",
        f"{label['declared']} ({n['lang']}):",
        *(f"- {s}" for s in STATEMENTS["notice"][n["lang"]]),
    ])


def reject(notice_id: int, note: str) -> None:
    """Marks a notice that won't be acted on (incomplete, or not about this site), and tells whoever
    sent it why (``note``), as the copyright policy promises."""
    n = notice(notice_id)
    with _db() as conn:
        conn.execute("UPDATE notices SET status = 'rejected', note = ? WHERE id = ?", (note, notice_id))
    mail.send(n["email"], "rejected", n["lang"], reply_to=config.COPYRIGHT_EMAIL, notice=notice_id, work=n["work"],
              why=note, link=f"{config.PUBLIC_URL}/copyright")


def find(sha256: str | None = None, title: str | None = None) -> list[Upload]:
    """The uploads, in every account, of a file (by its fingerprint) or whose title or file name
    has these words."""
    words = _plain(title or "").split()
    found = []
    for user_id, email in users.emails().items():
        for meta in library.list_books(user_id):
            fingerprint = meta.get("sha256")
            if sha256:
                fingerprint = fingerprint or _fingerprint(user_id, meta["id"])
                if fingerprint != sha256.lower():
                    continue
            if words and not all(w in _plain(f"{meta['title']} {meta['filename']}") for w in words):
                continue
            found.append(Upload(user_id, email, meta["id"], meta["title"], meta["filename"], meta["imported_at"],
                                meta.get("declared_at"), fingerprint, "disabled" in meta))
    return sorted(found, key=lambda u: (u.email, u.imported_at))


def disable(notice_id: int, books: list[tuple[str, str]], now: datetime | None = None) -> list[str]:
    """Disables the books a notice names (as account id, book id), tells their owners, and counts a
    strike against each owner: an account that reaches STRIKES is closed. What was done, line by line."""
    n, now = notice(notice_id), now or _now()
    report, todo = [], []
    for user_id, book_id in books:
        try:
            meta = library.get_book(user_id, book_id)
        except library.NotFound:
            raise Refused(f"account {user_id} has no book {book_id}") from None
        owner = users.get(user_id)
        if owner is None:
            raise Refused(f"there is no account {user_id}")
        if "disabled" in meta:
            report.append(f"{owner.email}: “{meta['title']}” was disabled already")
        else:
            todo.append((owner, meta))
    done = []
    with _db() as conn:
        for owner, meta in todo:
            takedown_id = conn.execute(
                "INSERT INTO takedowns (notice_id, user_id, email, book_id, title, sha256, disabled_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (notice_id, owner.id, owner.email, meta["id"], meta["title"],
                 meta.get("sha256") or _fingerprint(owner.id, meta["id"]), now.isoformat())).lastrowid
            done.append((owner, meta, takedown_id))
        conn.execute("UPDATE notices SET status = 'done' WHERE id = ?", (notice_id,))
    for owner, meta, takedown_id in done:
        library.set_disabled(owner.id, meta["id"], {"at": now.isoformat(), "takedown": takedown_id,
                                                    "claimant": n["claimant"], "work": n["work"]})
        count = strikes(owner.email)
        _tell_owner(owner, "takedown", title=meta["title"], date=now.date().isoformat(), claimant=n["claimant"],
                    work=n["work"], days=KEEP_DAYS, strikes=count, limit=STRIKES,
                    link=f"{config.PUBLIC_URL}/copyright/counter/{meta['id']}")
        report.append(f"{owner.email}: “{meta['title']}” disabled (takedown #{takedown_id}); strike {count} of {STRIKES}")
        if count >= STRIKES and users.closed(owner.id) is None:
            report += _close(owner, "strikes")
            _tell_owner(owner, "closed", limit=STRIKES, days=KEEP_DAYS)
            report.append(f"{owner.email}: account closed ({count} strikes)")
    return report


def strikes(email: str) -> int:
    """The notices that disabled books of this email's accounts, not restored since."""
    with _db() as conn:
        return conn.execute("SELECT COUNT(DISTINCT notice_id) FROM takedowns WHERE email = ? AND restored_at IS NULL",
                            (email.lower(),)).fetchone()[0]


def takedowns(email: str) -> list[dict]:
    with _db() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT takedowns.*, counter_notices.id AS counter_id FROM takedowns "
            "LEFT JOIN counter_notices ON counter_notices.takedown_id = takedowns.id WHERE email = ? ORDER BY takedowns.id",
            (email.lower(),))]


def block(sha256: str, notice_id: int | None = None) -> None:
    """Blocks a file (by its fingerprint): nobody can upload it any more. The copies already in
    libraries stay as they are (``disable`` them)."""
    sha256 = sha256.lower()
    if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
        raise Refused(f"{sha256} is not a SHA-256 fingerprint")
    if notice_id is not None:
        notice(notice_id)
    with _db() as conn:
        conn.execute("INSERT OR REPLACE INTO blocked VALUES (?, ?, ?)", (sha256, notice_id, _now().isoformat()))


def unblock(sha256: str) -> None:
    with _db() as conn:
        if conn.execute("DELETE FROM blocked WHERE sha256 = ?", (sha256.lower(),)).rowcount == 0:
            raise Refused(f"{sha256} is not blocked")


def counters(everything: bool = False) -> list[dict]:
    """The counter-notices whose book is still disabled (or all of them), oldest first."""
    where = "" if everything else "WHERE takedowns.restored_at IS NULL AND takedowns.deleted_at IS NULL"
    with _db() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT counter_notices.*, takedowns.notice_id, takedowns.email AS owner_email, takedowns.title, "
            "takedowns.restored_at FROM counter_notices JOIN takedowns ON takedowns.id = counter_notices.takedown_id "
            f"{where} ORDER BY counter_notices.id")]


def describe_counter(counter_id: int, lang: str) -> str:
    c, label = _counter(counter_id), _LABELS[_lang(lang)]
    return "\n".join([
        f"{label['received']}: {c['received_at']}",
        f"{label['book']}: “{c['title']}”",
        f"{label['disabled']}: {c['disabled_at'][:10]}",
        f"{label['name']}: {c['name']}",
        f"{label['address']}: {c['address']}",
        f"{label['phone']}: {c['phone']}",
        f"{label['reason']}: {c['reason'] or '-'}",
        f"{label['signature']}: {c['signature']}",
        f"{label['declared']}:",
        *(f"- {s}" for s in STATEMENTS["counter"][c["lang"]]),
    ])


def forward(counter_id: int, now: datetime | None = None) -> str:
    """Sends a counter-notice to whoever sent the notice, in their language; whom it went to."""
    c = _counter(counter_id)
    if c["forwarded_at"]:
        raise Refused(f"counter-notice #{counter_id} was forwarded already, on {c['forwarded_at'][:10]}")
    n = notice(c["notice_id"])
    mail.send(n["email"], "forwarded", n["lang"], reply_to=config.COPYRIGHT_EMAIL, notice=n["id"], work=n["work"],
              text=describe_counter(counter_id, n["lang"]), wait=WAIT_DAYS)
    with _db() as conn:
        conn.execute("UPDATE counter_notices SET forwarded_at = ? WHERE id = ?", ((now or _now()).isoformat(), counter_id))
    return n["email"]


def restore(takedown_id: int, force: bool = False, now: datetime | None = None) -> list[str]:
    """Lets the owner open a disabled book again and withdraws its strike: after a counter-notice
    once WAIT_DAYS business days passed since it was forwarded (or, with ``force``, at once, e.g.
    when the notice was withdrawn). An account closed for its strikes opens again if they drop
    below STRIKES."""
    now = now or _now()
    with _db() as conn:
        t = conn.execute("SELECT * FROM takedowns WHERE id = ?", (takedown_id,)).fetchone()
        counter = conn.execute("SELECT * FROM counter_notices WHERE takedown_id = ?", (takedown_id,)).fetchone()
    if t is None:
        raise Refused(f"there is no takedown #{takedown_id}")
    if t["restored_at"]:
        raise Refused(f"takedown #{takedown_id} was restored already")
    if t["deleted_at"]:
        raise Refused(f"the book of takedown #{takedown_id} was deleted")
    if counter and not force:
        if not counter["forwarded_at"]:
            raise Refused(f"forward counter-notice #{counter['id']} first (or restore now with --now)")
        waited = _business_days(datetime.fromisoformat(counter["forwarded_at"]), now)
        if waited < WAIT_DAYS:
            raise Refused(f"only {waited} business days since counter-notice #{counter['id']} was forwarded: "
                          f"wait for {WAIT_DAYS} (or restore now with --now)")
    with _db() as conn:
        conn.execute("UPDATE takedowns SET restored_at = ? WHERE id = ?", (now.isoformat(), takedown_id))
    report = []
    owner = users.get(t["user_id"])
    try:
        library.set_disabled(t["user_id"], t["book_id"], None)
        if owner:
            _tell_owner(owner, "restored", title=t["title"])
        report.append(f"{t['email']}: “{t['title']}” restored")
    except library.NotFound:
        report.append(f"{t['email']}: “{t['title']}” was deleted by its owner; the strike is withdrawn")
    if owner and (users.closed(owner.id) or ("", ""))[1] == "strikes" and strikes(owner.email) < STRIKES:
        users.reopen(owner.id)
        report.append(f"{owner.email}: account open again")
    return report


def close(email: str, reason: str) -> list[str]:
    """Closes an account for a reason of the agent's (told to its owner)."""
    owner = users.find(email)
    if owner is None:
        raise Refused(f"there is no account for {email}")
    report = _close(owner, reason)
    _tell_owner(owner, "closed_other", reason=reason, days=KEEP_DAYS)
    return report


def _close(owner: users.User, reason: str) -> list[str]:
    """Closes an account and cancels its subscription to Plus, so it isn't charged again. What
    the agent still has to do by hand."""
    users.close(owner.id, reason)
    try:
        billing.end(owner.id)
    except billing.Unavailable as e:
        log.error("Plus of %s wasn't cancelled: %s", owner.email, e)
        return [f"{owner.email}: cancel their Plus subscription in Paddle's dashboard (Paddle said: {e})"]
    return []


def purge(now: datetime | None = None) -> list[str]:
    """Deletes the books disabled more than KEEP_DAYS ago with no counter-notice, and the libraries
    of accounts closed more than KEEP_DAYS ago (their email stays, so it can't sign up again)."""
    now = now or _now()
    before = (now - timedelta(days=KEEP_DAYS)).isoformat()
    report = []
    with _db() as conn:
        stale = conn.execute(
            "SELECT * FROM takedowns WHERE restored_at IS NULL AND deleted_at IS NULL AND disabled_at < ? "
            "AND id NOT IN (SELECT takedown_id FROM counter_notices)", (before,)).fetchall()
    for t in stale:
        try:
            if (library.get_book(t["user_id"], t["book_id"]).get("disabled") or {}).get("takedown") == t["id"]:
                library.delete_book(t["user_id"], t["book_id"])
        except library.NotFound:
            pass
        with _db() as conn:
            conn.execute("UPDATE takedowns SET deleted_at = ? WHERE id = ?", (now.isoformat(), t["id"]))
        report.append(f"{t['email']}: deleted “{t['title']}” (takedown #{t['id']})")
    for owner in users.closed_before(before):
        library.delete_user(owner.id)
        users.forget_password(owner.id)
        report.append(f"{owner.email}: deleted the library of the closed account")
    return report


def _counter(counter_id: int) -> dict:
    with _db() as conn:
        row = conn.execute(
            "SELECT counter_notices.*, takedowns.notice_id, takedowns.email AS owner_email, takedowns.title, "
            "takedowns.disabled_at FROM counter_notices JOIN takedowns ON takedowns.id = counter_notices.takedown_id "
            "WHERE counter_notices.id = ?", (counter_id,)).fetchone()
    if row is None:
        raise Refused(f"there is no counter-notice #{counter_id}")
    return dict(row)


def _tell_owner(owner: users.User, kind: str, **fields) -> None:
    mail.send(owner.email, kind, owner.lang, reply_to=config.COPYRIGHT_EMAIL, **fields)


def _fingerprint(user_id: str, book_id: str) -> str:
    """The SHA-256 of a book's file (books imported before it was kept in meta.json)."""
    source = next(library.book_dir(user_id, book_id).glob("book.*"))
    digest = hashlib.sha256()
    with source.open("rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _plain(text: str) -> str:
    """Lowercase, without accents: how titles are compared."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


def _lang(lang: str) -> str:
    return lang if lang in users.LANGS else "en"


def _business_days(since: datetime, until: datetime) -> int:
    day, days = since.date(), 0
    while day < until.date():
        day += timedelta(days=1)
        days += day.weekday() < 5 and not _holiday(day)
    return days


def _holiday(day: date) -> bool:
    """Mexico's official days of rest (Ley Federal del Trabajo, art. 74)."""
    def monday(month: int, nth: int) -> int:  # the day of the month of its nth Monday
        first = date(day.year, month, 1)
        return 1 + (7 - first.weekday()) % 7 + 7 * (nth - 1)

    fixed = {(1, 1), (5, 1), (9, 16), (12, 25)}
    mondays = {(2, monday(2, 1)), (3, monday(3, 3)), (11, monday(11, 3))}
    inauguration = {(10, 1)} if (day.year - 2024) % 6 == 0 else set()  # a new president takes office
    return (day.month, day.day) in fixed | mondays | inauguration
