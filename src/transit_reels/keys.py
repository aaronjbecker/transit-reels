"""API keys for the feeds that need one.

A key never goes in a recipe (recipes get shared and committed). A recipe names the key
(`key = "trafiklab"`) and says how the agency wants it (`key_param` in the URL or
`key_header`); the key itself lives in the environment (TRANSIT_REELS_KEY_TRAFIKLAB) or in a
private file, ~/.config/transit-reels/keys.toml, readable only by you, written by
`transit-reels key set <name>`. Keys are never printed or logged.
"""

from __future__ import annotations

import os
import re
import stat
import sys
import tomllib
import urllib.parse
from pathlib import Path


def key_file() -> Path:
    return Path(os.environ.get("TRANSIT_REELS_KEYS", "~/.config/transit-reels/keys.toml")).expanduser()


def env_name(name: str) -> str:
    return "TRANSIT_REELS_KEY_" + re.sub(r"[^A-Za-z0-9]", "_", name).upper()


def _load() -> dict[str, str]:
    f = key_file()
    if not f.exists():
        return {}
    with open(f, "rb") as fh:
        return {k: str(v) for k, v in tomllib.load(fh).items()}


def get(name: str) -> str | None:
    return os.environ.get(env_name(name)) or _load().get(name)


def _save(keys: dict[str, str]) -> None:
    f = key_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    try:
        f.parent.chmod(stat.S_IRWXU)
    except OSError:
        pass
    # Created private before anything is written to it.
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write("# API keys for transit-reels. Private: do not share or commit this file.\n")
        for k, v in sorted(keys.items()):
            fh.write(f'{k} = "{v.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"\n')
    try:
        f.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def set_key(name: str) -> None:
    """Ask for the key without echoing it (or read it from a pipe), and store it privately."""
    import getpass
    if sys.stdin.isatty():
        value = getpass.getpass(f"Paste the key for '{name}' (it will not be shown): ").strip()
    else:
        value = sys.stdin.readline().strip()
    if not value:
        raise SystemExit("No key given; nothing saved.")
    keys = _load()
    keys[name] = value
    _save(keys)
    print(f"Saved '{name}' to {key_file()} (readable only by you).")


def remove(name: str) -> None:
    keys = _load()
    if keys.pop(name, None) is None:
        raise SystemExit(f"No key named '{name}'.")
    _save(keys)
    print(f"Removed '{name}'.")


def names() -> list[str]:
    stored = set(_load())
    from_env = {k[len("TRANSIT_REELS_KEY_"):].lower() for k in os.environ if k.startswith("TRANSIT_REELS_KEY_")}
    return sorted(stored | from_env)


def apply(url: str, feed: dict, value: str) -> tuple[str, dict[str, str]]:
    """The URL and headers that carry the key the way the agency wants it."""
    if feed.get("key_header"):
        return url, {feed["key_header"]: value}
    param = feed.get("key_param") or "key"
    sep = "&" if urllib.parse.urlparse(url).query else "?"
    return f"{url}{sep}{urllib.parse.quote(param)}={urllib.parse.quote(value)}", {}


def missing_message(feed: dict) -> str:
    name = feed["key"]
    signup = feed.get("signup") or "the agency's developer portal"
    lines = [
        f"This feed needs an API key ('{name}'). They are usually free and take a few minutes:",
        f"  1. Sign up at {signup}",
        f"  2. In a terminal, run:  uv run transit-reels key set {name}",
        f"     It asks for the key without showing it and keeps it in {key_file()},",
        "     readable only by you. Never paste a key into a recipe or a chat.",
    ]
    if not feed.get("mirror"):
        lines.append("Or, with no key: add the feed's Mobility Database mirror as `mirror = ...` "
                     "(`transit-reels find` prints it).")
    return "\n".join(lines)
