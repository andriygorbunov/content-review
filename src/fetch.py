"""Fetch public post + comments + replies.

Source: Hacker News Firebase API — public, no auth, no key, and it gives a real
nested reply tree. Swap in another source by implementing fetch_thread().
"""
import json
import urllib.request
from datetime import datetime, timezone

from . import db

API = "https://hacker-news.firebaseio.com/v0/item/{}.json"


def _get(item_id):
    with urllib.request.urlopen(API.format(item_id), timeout=10) as r:
        return json.loads(r.read().decode())


def fetch_thread(story_id, max_items=40, max_depth=3):
    """Return a flat list of normalized items: the post plus its comment tree."""
    out = []
    root = _get(story_id)
    if not root:
        return out

    out.append({
        "source_id": str(root["id"]),
        "kind": "post",
        "parent_source_id": None,
        "author": root.get("by"),
        "text": " ".join(filter(None, [root.get("title"), root.get("text")])),
        "url": root.get("url") or f"https://news.ycombinator.com/item?id={root['id']}",
    })

    # BFS the reply tree so we get breadth before depth under the cap
    queue = [(kid, 1) for kid in root.get("kids", [])]
    while queue and len(out) < max_items:
        kid_id, depth = queue.pop(0)
        if depth > max_depth:
            continue
        node = _get(kid_id)
        if not node or node.get("deleted") or node.get("dead"):
            continue
        out.append({
            "source_id": str(node["id"]),
            "kind": "comment",
            "parent_source_id": str(node.get("parent")),
            "author": node.get("by"),
            "text": node.get("text") or "",
            "url": f"https://news.ycombinator.com/item?id={node['id']}",
        })
        queue.extend((k, depth + 1) for k in node.get("kids", []))
    return out


def save(conn, items, source="hn"):
    """Upsert into the LIVE table. Re-running this is what causes drift."""
    now = datetime.now(timezone.utc).isoformat()
    for it in items:
        conn.execute(
            """INSERT INTO items
               (source, source_id, kind, parent_source_id, author, text, url,
                fetched_at, content_hash)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source, source_id) DO UPDATE SET
                 text=excluded.text, fetched_at=excluded.fetched_at,
                 content_hash=excluded.content_hash""",
            (source, it["source_id"], it["kind"], it["parent_source_id"],
             it["author"], it["text"], it["url"], now,
             db.content_hash(it["text"])),
        )
    conn.commit()
    return len(items)
