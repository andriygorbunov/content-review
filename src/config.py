"""Configuration and secrets.

Secrets are never committed. Resolution order, first hit wins:

  1. process environment            (CI, `export ANTHROPIC_API_KEY=...`)
  2. .env in the repo root          (local dev — gitignored)

`.env.example` documents the shape; copy it to `.env` and fill it in.

Stdlib only — no python-dotenv, consistent with the rest of the project.
"""
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"

_cache = None


def _parse_env_file(path):
    """Minimal KEY=VALUE parser. Ignores blanks and # comments.

    Strips one layer of matching quotes so both of these work:
        ANTHROPIC_API_KEY=sk-ant-...
        ANTHROPIC_API_KEY="sk-ant-..."
    """
    out = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def _file_env():
    global _cache
    if _cache is None:
        _cache = _parse_env_file(ENV_FILE)
    return _cache


def get(name, default=None):
    """Environment first, then .env. Returns `default` if neither has it."""
    return os.environ.get(name) or _file_env().get(name) or default


def require(name):
    """Same as get(), but fails loudly with a fix instruction.

    A missing credential should say what to do about it, not raise KeyError
    three frames down inside an HTTP client.
    """
    value = get(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set.\n"
            f"  Either:  export {name}=...\n"
            f"  Or:      cp .env.example .env   and fill it in\n"
            f"  ({ENV_FILE} is gitignored and will not be committed.)"
        )
    return value
