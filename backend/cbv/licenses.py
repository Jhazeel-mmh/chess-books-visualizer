"""The libraries the server runs on, with their licenses, for the app's Licenses page.

They are found from the server's requirements in pyproject.toml, followed through each installed
library's own, so the list is what really runs, not what someone remembered to write down.
"""

from __future__ import annotations

import re
import tomllib
from importlib import metadata
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
_REQUIREMENT = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[([^\]]*)\])?")
_EXTRA = re.compile(r"""extra\s*==\s*['"]([^'"]+)['"]""")


def server_packages() -> list[dict]:
    found: dict[str, dict] = {}
    followed: set[tuple[str, frozenset[str]]] = set()
    queue = [_parse(r) for r in tomllib.loads(PYPROJECT.read_text())["project"]["dependencies"]]
    while queue:
        name, extras = queue.pop()
        key = name.lower().replace("_", "-")
        if (key, frozenset(extras)) in followed:
            continue
        followed.add((key, frozenset(extras)))
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue  # only needed on another platform or Python
        found.setdefault(key, {
            "name": dist.metadata["Name"],
            "version": dist.version,
            "license": _license(dist.metadata),
            "home": _home(dist.metadata),
        })
        queue += _requires(dist, extras)
    return sorted(found.values(), key=lambda p: p["name"].lower())


def _parse(requirement: str) -> tuple[str, set[str]]:
    m = _REQUIREMENT.match(requirement)
    return m.group(1), {e.strip() for e in (m.group(2) or "").split(",") if e.strip()}


def _requires(dist, extras: set[str]) -> list[tuple[str, set[str]]]:
    out = []
    for r in dist.requires or []:
        # A requirement only for an extra counts when that extra was asked for ("uvicorn[standard]").
        extra = _EXTRA.search(r)
        if extra is None or extra.group(1) in extras:
            out.append(_parse(r))
    return out


def _license(meta) -> str | None:
    if meta.get("License-Expression"):
        return meta["License-Expression"]
    text = (meta.get("License") or "").strip()
    if text and len(text) < 80 and "\n" not in text:
        return text
    classifiers = [c.split(" :: ")[-1] for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    return " / ".join(classifiers) or None


def _home(meta) -> str | None:
    urls = dict(u.split(", ", 1) for u in meta.get_all("Project-URL") or [] if ", " in u)
    for label in ("Source", "Source Code", "Repository", "Homepage", "homepage", "Home"):
        if label in urls:
            return urls[label]
    return meta.get("Home-page") or next(iter(urls.values()), None)
