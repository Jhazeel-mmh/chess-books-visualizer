"""The copyright agent's tool for the hosted app: notices, takedowns, counter-notices and strikes.

Run it on the server with the app's settings (CBV_DATA_DIR, CBV_PUBLIC_URL, CBV_SMTP_*,
CBV_MAIL_FROM, CBV_COPYRIGHT_EMAIL), so that it reads the same accounts and sends the same mail:

    python scripts/admin.py notices [--all]          the notices not dealt with yet (or all)
    python scripts/admin.py notice N                 one notice, and what was done about it
    python scripts/admin.py find --notice N          the uploads of the file a notice sent the fingerprint of
    python scripts/admin.py find --hash SHA256 | --title "words"
    python scripts/admin.py disable N BOOK...        disables every copy of these books (ids from find)
                                [--account EMAIL]    ...or only the copy in this account
    python scripts/admin.py reject N "why"           a notice that won't be acted on (mails its sender why)
    python scripts/admin.py block SHA256 [--notice N]  nobody can upload this file again
    python scripts/admin.py unblock SHA256
    python scripts/admin.py counters [--all]         counter-notices of books still disabled
    python scripts/admin.py counter C                one counter-notice
    python scripts/admin.py forward C                sends it to whoever sent the notice
    python scripts/admin.py restore T [--now]        gives a disabled book back (T: its takedown)
    python scripts/admin.py account EMAIL            an account's books, takedowns and strikes
    python scripts/admin.py close EMAIL "why"
    python scripts/admin.py purge                    deletes what waited its time for nothing, and
                                                     page images nobody looked at in a week (daily)

See backend/cbv/copyright.py for the whole process. Nothing here shows what is in a book: only
titles, file names and fingerprints.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from cbv import copyright, library, users  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copyright notices of the hosted app.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("notices", "counters"):
        commands.add_parser(name).add_argument("--all", action="store_true")
    commands.add_parser("notice").add_argument("notice", type=int)
    find = commands.add_parser("find").add_mutually_exclusive_group(required=True)
    find.add_argument("--notice", type=int)
    find.add_argument("--hash")
    find.add_argument("--title")
    disable = commands.add_parser("disable")
    disable.add_argument("notice", type=int)
    disable.add_argument("books", nargs="+")
    disable.add_argument("--account")
    reject = commands.add_parser("reject")
    reject.add_argument("notice", type=int)
    reject.add_argument("why")
    block = commands.add_parser("block")
    block.add_argument("hash")
    block.add_argument("--notice", type=int)
    commands.add_parser("unblock").add_argument("hash")
    commands.add_parser("counter").add_argument("counter", type=int)
    commands.add_parser("forward").add_argument("counter", type=int)
    restore = commands.add_parser("restore")
    restore.add_argument("takedown", type=int)
    restore.add_argument("--now", action="store_true", help="don't wait for the counter-notice's time")
    commands.add_parser("account").add_argument("email")
    close = commands.add_parser("close")
    close.add_argument("email")
    close.add_argument("why")
    commands.add_parser("purge")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    try:
        globals()[f"_{args.command}"](args)
    except copyright.Refused as e:
        print(f"Not done: {e.why}", file=sys.stderr)
        return 1
    return 0


def _notices(args) -> None:
    rows = copyright.notices(args.all)
    if not rows:
        print("No notices." if args.all else "No new notices.")
    for n in rows:
        print(f"#{n['id']}  {n['received_at'][:10]}  {n['status']:<8}  {n['claimant']}: {_line(n['work'])}"
              + ("  [has a fingerprint]" if n["sha256"] else ""))


def _notice(args) -> None:
    n = copyright.notice(args.notice)
    print(copyright.describe_notice(args.notice))
    print(f"\nStatus: {n['status']}" + (f" ({n['note']})" if n["note"] else ""))
    for t in n["takedowns"]:
        state = "restored" if t["restored_at"] else "deleted" if t["deleted_at"] else "disabled"
        print(f"Takedown #{t['id']}: {t['email']} “{t['title']}” {state}")
    for sha in n["blocked"]:
        print(f"Blocked: {sha}")
    if n["status"] == "new":
        how = f"--notice {n['id']}" if n["sha256"] else '--title "…"'
        print(f"\nNext: python scripts/admin.py find {how}")


def _find(args) -> None:
    sha256 = args.hash
    if args.notice is not None:
        sha256 = copyright.notice(args.notice)["sha256"]
        if not sha256:
            raise copyright.Refused(f"notice #{args.notice} has no fingerprint: find by --title")
    uploads = copyright.find(sha256=sha256, title=args.title)
    if not uploads:
        print("No uploads found.")
    for u in uploads:
        print(f"{u.book_id}  {u.email}  “{u.title}” ({u.filename})  imported {u.imported_at[:10]}"
              f"  {'declared' if u.declared_at else 'not declared'}{'  DISABLED' if u.disabled else ''}")


def _disable(args) -> None:
    owner = users.find(args.account) if args.account else None
    if args.account and owner is None:
        raise copyright.Refused(f"there is no account for {args.account}")
    books = []
    for book_id in args.books:
        found = [(u.user_id, u.book_id) for u in copyright.find() if u.book_id == book_id and (owner is None or u.user_id == owner.id)]
        if not found:
            raise copyright.Refused(f"no library has the book {book_id}")
        books += found
    for line in copyright.disable(args.notice, books):
        print(line)


def _reject(args) -> None:
    copyright.reject(args.notice, args.why)
    print(f"Notice #{args.notice} rejected.")


def _block(args) -> None:
    copyright.block(args.hash, args.notice)
    print("Blocked: nobody can upload this file any more. Copies already uploaded stay until you disable them.")


def _unblock(args) -> None:
    copyright.unblock(args.hash)
    print("Unblocked.")


def _counters(args) -> None:
    rows = copyright.counters(args.all)
    if not rows:
        print("No counter-notices waiting." if not args.all else "No counter-notices.")
    for c in rows:
        state = "restored" if c["restored_at"] else f"forwarded {c['forwarded_at'][:10]}" if c["forwarded_at"] else "not forwarded"
        print(f"#{c['id']}  {c['received_at'][:10]}  {c['owner_email']} “{c['title']}”  takedown #{c['takedown_id']}"
              f" (notice #{c['notice_id']})  {state}")


def _counter(args) -> None:
    print(copyright.describe_counter(args.counter, "en"))


def _forward(args) -> None:
    to = copyright.forward(args.counter)
    print(f"Sent to {to}. Restore the book after {copyright.WAIT_DAYS} business days unless they answer that "
          "they went to court.")


def _restore(args) -> None:
    for line in copyright.restore(args.takedown, force=args.now):
        print(line)


def _account(args) -> None:
    owner = users.find(args.email)
    if owner is None:
        print(f"No account for {args.email}.")
    else:
        closed = users.closed(owner.id)
        print(f"{owner.email}  account {owner.id}" + (f"  CLOSED {closed[0][:10]} ({closed[1]})" if closed else ""))
        for meta in library.list_books(owner.id):
            print(f"  {meta['id']}  “{meta['title']}” ({meta['filename']})  imported {meta['imported_at'][:10]}"
                  f"{'  DISABLED' if 'disabled' in meta else ''}")
    print(f"Strikes: {copyright.strikes(args.email)} of {copyright.STRIKES}")
    for t in copyright.takedowns(args.email):
        state = "restored" if t["restored_at"] else "deleted" if t["deleted_at"] else "disabled"
        print(f"  takedown #{t['id']} (notice #{t['notice_id']}) {t['disabled_at'][:10]} “{t['title']}” {state}"
              + (f", counter-notice #{t['counter_id']}" if t["counter_id"] else ""))


def _close(args) -> None:
    for line in copyright.close(args.email, args.why):
        print(line)
    print(f"Closed. Its library is deleted by purge after {copyright.KEEP_DAYS} days.")


def _purge(args) -> None:
    users.tidy()
    lines = copyright.purge()
    if renders := library.forget_renders():
        lines.append(f"Deleted {renders} page images nobody looked at in {library.RENDER_DAYS} days.")
    print("\n".join(lines) if lines else "Nothing to delete.")


def _line(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= 70 else text[:69] + "…"


if __name__ == "__main__":
    sys.exit(main())
