"""Accounts of the hosted app: sign-up with a confirmed email, sessions, password resets.

Kept in SQLite (<data>/users.db). Passwords are stored as Argon2id hashes. Sessions and the
one-time links sent by mail are stored only as SHA-256 hashes of their tokens, so a copy of the
database lets nobody in. Nothing here tells whether an email has an account: signing up with one
that has, or asking to reset the password of one that hasn't, answers the same.

An account can also be closed by the site (after repeated copyright notices, see copyright.py):
nobody can sign in to it any more, and its email can't sign up again.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from . import config, library

SESSION_DAYS = 30
VERIFY_HOURS = 48
UNVERIFIED_DAYS = 7  # an account whose email nobody confirmed is forgotten after this
RESET_HOURS = 1
MIN_PASSWORD = 8
MAX_PASSWORD = 256
LANGS = {"es", "en"}

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_hasher = PasswordHasher()
# Checked when there is no account, so a wrong email takes as long as a wrong password.
_NOBODY = _hasher.hash(secrets.token_hex(16))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,
    lang TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    closed_at TEXT,
    closed_reason TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tokens (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL,
    expires_at REAL NOT NULL
);
"""


@dataclass
class User:
    id: str
    email: str
    lang: str


@dataclass
class Mail:
    """A message to send: "verify", "exists" or "reset", with its link."""
    to: str
    kind: str
    lang: str
    link: str


class AuthError(Exception):
    """Why a request was refused: "email", "password", "credentials", "unverified", "closed" or "link"."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


_ready: set[str] = set()


@contextmanager
def connect():
    path = library.DATA_DIR / "users.db"
    fresh = str(path) not in _ready
    if fresh:
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        if fresh:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(_SCHEMA)
            _ready.add(str(path))
        with conn:
            yield conn
    finally:
        conn.close()


def signup(email: str, password: str, lang: str) -> Mail | None:
    """A new account, waiting for its email to be confirmed; or, for an email that already has
    one, a message to its owner saying so (none if the site closed that account)."""
    email = _email(email)
    _check(password)
    lang = lang if lang in LANGS else "en"
    hashed = _hasher.hash(password)  # also when the account exists: both answers take as long
    with connect() as conn:
        _tidy(conn)
        row = conn.execute("SELECT id, lang, closed_at FROM users WHERE email = ?", (email,)).fetchone()
        if row and row["closed_at"]:
            return None
        if row:
            return Mail(email, "exists", row["lang"], _link("reset", _token(conn, row["id"], "reset", RESET_HOURS)))
        user_id = uuid.uuid4().hex
        conn.execute("INSERT INTO users (id, email, password, lang, created_at) VALUES (?, ?, ?, ?, ?)",
                     (user_id, email, hashed, lang, datetime.now(timezone.utc).isoformat()))
        return Mail(email, "verify", lang, _link("verify", _token(conn, user_id, "verify", VERIFY_HOURS)))


def resend(email: str) -> Mail | None:
    """A new confirmation link, if the email has an account not confirmed yet."""
    return _mail_for(email, "verify", "verify", VERIFY_HOURS, "AND NOT verified")


def forgot(email: str) -> Mail | None:
    """A link to choose a new password, if the email has an account."""
    return _mail_for(email, "reset", "reset", RESET_HOURS)


def verify(token: str) -> str:
    """Confirms the email a sign-up link was sent to, and starts a session (its token)."""
    with connect() as conn:
        user_id = _spend(conn, token, "verify")
        conn.execute("UPDATE users SET verified = 1 WHERE id = ?", (user_id,))
        return _session(conn, user_id)


def login(email: str, password: str) -> str:
    """A new session (its token) for the right email and password."""
    try:
        email = _email(email)
    except AuthError:
        raise AuthError("credentials") from None
    with connect() as conn:
        _tidy(conn)
        row = conn.execute("SELECT id, password, verified, closed_at FROM users WHERE email = ?", (email,)).fetchone()
        if not _matches(row["password"] if row else None, password):
            raise AuthError("credentials")
        if row["closed_at"]:
            raise AuthError("closed")
        if not row["verified"]:
            raise AuthError("unverified")
        if _hasher.check_needs_rehash(row["password"]):
            conn.execute("UPDATE users SET password = ? WHERE id = ?", (_hasher.hash(password), row["id"]))
        return _session(conn, row["id"])


def reset(token: str, password: str) -> str:
    """Sets the new password of a reset link, ends every session of the account, and starts one."""
    _check(password)
    hashed = _hasher.hash(password)
    with connect() as conn:
        user_id = _spend(conn, token, "reset")
        # The link reached the account's mailbox, so that confirms the address too.
        conn.execute("UPDATE users SET password = ?, verified = 1 WHERE id = ?", (hashed, user_id))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM tokens WHERE user_id = ? AND purpose = 'reset'", (user_id,))
        return _session(conn, user_id)


def session_user(token: str | None) -> User | None:
    if not token:
        return None
    with connect() as conn:
        row = conn.execute(
            "SELECT users.id, email, lang FROM sessions JOIN users ON users.id = sessions.user_id "
            "WHERE token = ? AND expires_at > ? AND verified AND closed_at IS NULL", (_hash(token), time.time())).fetchone()
    return User(row["id"], row["email"], row["lang"]) if row else None


def logout(token: str | None) -> None:
    if token:
        with connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (_hash(token),))


def delete(user: User, password: str, before: Callable[[str], None] | None = None) -> None:
    """Closes an account (its password confirms it): the account, its sessions, and its library.
    ``before`` runs once the password is right, before anything is deleted, and can stop it."""
    with connect() as conn:
        row = conn.execute("SELECT password FROM users WHERE id = ?", (user.id,)).fetchone()
        if row is None or not _matches(row["password"], password):
            raise AuthError("credentials")
        if before is not None:
            before(user.id)
        conn.execute("DELETE FROM users WHERE id = ?", (user.id,))  # sessions and links go with it
    library.delete_user(user.id)


def find(email: str) -> User | None:
    """The account of an email (also a closed one)."""
    try:
        email = _email(email)
    except AuthError:
        return None
    with connect() as conn:
        row = conn.execute("SELECT id, email, lang FROM users WHERE email = ?", (email,)).fetchone()
    return User(row["id"], row["email"], row["lang"]) if row else None


def get(user_id: str) -> User | None:
    with connect() as conn:
        row = conn.execute("SELECT id, email, lang FROM users WHERE id = ?", (user_id,)).fetchone()
    return User(row["id"], row["email"], row["lang"]) if row else None


def emails() -> dict[str, str]:
    """The email of every account, by account id."""
    with connect() as conn:
        return {row["id"]: row["email"] for row in conn.execute("SELECT id, email FROM users")}


def closed(user_id: str) -> tuple[str, str] | None:
    """When and why the site closed an account, if it did."""
    with connect() as conn:
        row = conn.execute("SELECT closed_at, closed_reason FROM users WHERE id = ?", (user_id,)).fetchone()
    return (row["closed_at"], row["closed_reason"]) if row and row["closed_at"] else None


def close(user_id: str, reason: str) -> None:
    """Closes an account for the site: its sessions and links end, and nobody can sign in to it.
    Its library stays for now (copyright.purge deletes it later)."""
    with connect() as conn:
        conn.execute("UPDATE users SET closed_at = ?, closed_reason = ? WHERE id = ?",
                     (datetime.now(timezone.utc).isoformat(), reason, user_id))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM tokens WHERE user_id = ?", (user_id,))


def closed_before(when: str) -> list[User]:
    """The accounts closed before a time (ISO 8601) whose library wasn't deleted yet."""
    with connect() as conn:
        rows = conn.execute("SELECT id, email, lang FROM users WHERE closed_at < ? AND password != ''", (when,)).fetchall()
    return [User(row["id"], row["email"], row["lang"]) for row in rows]


def reopen(user_id: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE users SET closed_at = NULL, closed_reason = NULL WHERE id = ?", (user_id,))


def forget_password(user_id: str) -> None:
    """A closed account whose library was deleted keeps only its email (so it can't sign up again)."""
    with connect() as conn:
        conn.execute("UPDATE users SET password = '' WHERE id = ?", (user_id,))


def _mail_for(email: str, kind: str, purpose: str, hours: float, where: str = "") -> Mail | None:
    try:
        email = _email(email)
    except AuthError:
        return None
    with connect() as conn:
        row = conn.execute(f"SELECT id, lang FROM users WHERE email = ? AND closed_at IS NULL {where}", (email,)).fetchone()
        if row is None:
            return None
        return Mail(email, kind, row["lang"], _link(purpose, _token(conn, row["id"], purpose, hours)))


def _email(email: str) -> str:
    email = (email or "").strip().lower()
    if len(email) > 254 or not _EMAIL.match(email):
        raise AuthError("email")
    return email


def _check(password: str) -> None:
    if not MIN_PASSWORD <= len(password or "") <= MAX_PASSWORD:
        raise AuthError("password")


def _matches(hashed: str | None, password: str) -> bool:
    if len(password or "") > MAX_PASSWORD:
        return False
    try:
        return _hasher.verify(hashed or _NOBODY, password or "") and hashed is not None
    except (VerificationError, InvalidHashError):
        return False


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _token(conn, user_id: str, purpose: str, hours: float) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO tokens VALUES (?, ?, ?, ?)", (_hash(token), user_id, purpose, time.time() + hours * 3600))
    return token


def _spend(conn, token: str, purpose: str) -> str:
    """The account a one-time link is for; the link can't be used again."""
    key = _hash(token or "")
    row = conn.execute("SELECT user_id FROM tokens WHERE token = ? AND purpose = ? AND expires_at > ?",
                       (key, purpose, time.time())).fetchone()
    if row is None:
        raise AuthError("link")
    conn.execute("DELETE FROM tokens WHERE token = ?", (key,))
    return row["user_id"]


def _session(conn, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions VALUES (?, ?, ?)", (_hash(token), user_id, time.time() + SESSION_DAYS * 86400))
    return token


def _link(page: str, token: str) -> str:
    return f"{config.PUBLIC_URL}/{page}?token={token}"


def tidy() -> None:
    """Forgets expired sessions and links, and accounts nobody confirmed (purge runs it daily)."""
    with connect() as conn:
        _tidy(conn)


def _tidy(conn) -> None:
    now = time.time()
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
    conn.execute("DELETE FROM tokens WHERE expires_at < ?", (now,))
    # Nobody could sign in to these, so they have nothing but the email.
    unconfirmed = datetime.fromtimestamp(now - UNVERIFIED_DAYS * 86400, timezone.utc).isoformat()
    conn.execute("DELETE FROM users WHERE NOT verified AND closed_at IS NULL AND created_at < ?", (unconfirmed,))
