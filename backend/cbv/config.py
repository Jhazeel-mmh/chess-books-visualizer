"""Settings, from the environment.

Without CBV_HOSTED=1 the app is a local app with one reader and no sign-in (the default). With
it, the app serves many people: each signs in and sees only their own books.
"""

from __future__ import annotations

import os

HOSTED = os.environ.get("CBV_HOSTED") == "1"
# The site's address: for the links in emails, and to tell the site's own pages from other sites.
PUBLIC_URL = os.environ.get("CBV_PUBLIC_URL", "http://localhost:5173").rstrip("/")
# Session cookies travel only over HTTPS; CBV_COOKIE_SECURE=0 tries the hosted mode over plain HTTP.
COOKIE_SECURE = os.environ.get("CBV_COOKIE_SECURE", "1") != "0"
# Outgoing mail (confirming an address, resetting a password). Without a host it goes to the log.
SMTP_HOST = os.environ.get("CBV_SMTP_HOST")
SMTP_PORT = int(os.environ.get("CBV_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("CBV_SMTP_USER")
SMTP_PASSWORD = os.environ.get("CBV_SMTP_PASSWORD")
MAIL_FROM = os.environ.get("CBV_MAIL_FROM", "Chess Books Visualizer <no-reply@localhost>")
# Where copyright notices and counter-notices are sent as they arrive (the site's copyright
# agent). Without it they only go to the log; scripts/admin.py lists them either way.
COPYRIGHT_EMAIL = os.environ.get("CBV_COPYRIGHT_EMAIL")
# Who runs a hosted site, as its terms, privacy notice and copyright policy name them.
OPERATOR = os.environ.get("CBV_OPERATOR")  # a person's or a company's legal name
OPERATOR_ADDRESS = os.environ.get("CBV_OPERATOR_ADDRESS")  # their postal address
CONTACT_EMAIL = os.environ.get("CBV_CONTACT_EMAIL")  # privacy requests, and anything else
# The copyright agent as registered with the US Copyright Office: name, postal address, phone.
COPYRIGHT_AGENT = os.environ.get("CBV_COPYRIGHT_AGENT")


def _limit(name: str, hosted: int) -> int:
    """A limit from the environment. Unset, a hosted site's default; the local app has none (0)."""
    value = os.environ.get(name)
    return int(value) if value else hosted if HOSTED else 0


# What one account may keep and do. 0 is no limit.
MAX_UPLOAD_MB = _limit("CBV_MAX_UPLOAD_MB", 100)  # one book file
MAX_BOOKS = _limit("CBV_MAX_BOOKS", 3)
MAX_STORAGE_MB = _limit("CBV_MAX_STORAGE_MB", 300)  # the book files of a library, all together
# The same for an account on the paid plan (Plus).
PLUS_MAX_BOOKS = _limit("CBV_PLUS_MAX_BOOKS", 300)
PLUS_MAX_STORAGE_MB = _limit("CBV_PLUS_MAX_STORAGE_MB", 5000)
# Daily-trainer sessions a free account may start, once and for all (not each week): a taste of
# what Plus gives. Counted only while Plus is on sale (below).
FREE_TRAINER_SESSIONS = _limit("CBV_FREE_TRAINER_SESSIONS", 7)

# Plus is sold through Paddle (paddle.com), the merchant of record: Paddle sells it to the reader,
# charges the taxes of their country and invoices them. Without all four settings nothing is sold
# and every account is on the free plan. CBV_PADDLE_SANDBOX=1 uses Paddle's test environment.
PADDLE_API_KEY = os.environ.get("CBV_PADDLE_API_KEY")
PADDLE_CLIENT_TOKEN = os.environ.get("CBV_PADDLE_CLIENT_TOKEN")  # public: the browser opens the checkout with it
PADDLE_PRICE = os.environ.get("CBV_PADDLE_PRICE")  # Plus's price (pri_…), set up in Paddle
PADDLE_WEBHOOK_SECRET = os.environ.get("CBV_PADDLE_WEBHOOK_SECRET")  # of the notification destination …/api/billing/webhook
PADDLE_SANDBOX = os.environ.get("CBV_PADDLE_SANDBOX") == "1"
SELLING = HOSTED and bool(PADDLE_API_KEY and PADDLE_CLIENT_TOKEN and PADDLE_PRICE and PADDLE_WEBHOOK_SECRET)

# Google AdSense, for free accounts, only on pages that show nothing of a book (the library, the
# trainer's start and summary). Without both settings there are no ads.
ADSENSE_CLIENT = os.environ.get("CBV_ADSENSE_CLIENT")  # ca-pub-…
ADSENSE_SLOT = os.environ.get("CBV_ADSENSE_SLOT")  # a display ad unit's id
ADS = HOSTED and bool(ADSENSE_CLIENT and ADSENSE_SLOT)
# Each book is analysed in a process of its own, killed past these.
ANALYSIS_MINUTES = _limit("CBV_ANALYSIS_MINUTES", 20)
ANALYSIS_MEMORY_MB = _limit("CBV_ANALYSIS_MEMORY_MB", 4096)  # address space: the readers reserve ~1.5 GB before reading
# How many books are analysed at once (each reader's one at a time, when hosted).
WORKERS = int(os.environ.get("CBV_WORKERS", "2"))
