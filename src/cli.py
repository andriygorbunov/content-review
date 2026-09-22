"""CLI. Run:  python -m src.cli <command> --help"""
import argparse
import sys
from datetime import datetime, timezone

from . import db, fetch, freeze, evals, hillclimb, labelers


# ---------------------------------------------------------------- Phase 1
def cmd_init(a, conn):
    db.init()
    print("initialized", db.DB_PATH)


def cmd_fetch(a, conn):
    items = fetch.fetch_thread(a.story_id, max_items=a.max_items)
    n = fetch.save(conn, items)
    print(f"fetched {n} items (1 post + {n-1} comments/replies) from story {a.story_id}")


def cmd_freeze(a, conn):
    sid, n = freeze.create(conn, a.name, note=a.note or "")
    print(f"snapshot {a.name!r} (id={sid}) froze {n} items — evals now reproducible")


def cmd_snapshots(a, conn):
    for r in conn.execute("SELECT * FROM snapshots ORDER BY id").fetchall():
        n = conn.execute("SELECT COUNT(*) c FROM frozen_items WHERE snapshot_id=?",
                         (r["id"],)).fetchone()["c"]
        print(f"  {r['id']:>3}  {r['name']:<20} {n:>4} items  {r['created_at'][:19]}")


def cmd_review_open(a, conn):
    """HUMAN initiates. The agent then assembles the review packet."""
    sid = freeze.get_id(conn, a.snapshot)
    if sid is None:
        sys.exit(f"no snapshot {a.snapshot!r}")
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO reviews (snapshot_id, status, opened_by, opened_at) VALUES (?,?,?,?)",
        (sid, "open", a.by, now))
    conn.commit()
    rid = cur.lastrowid
    n = len(freeze.items(conn, sid))
    print(f"review {rid} opened by {a.by} on snapshot {a.snapshot!r} — "
          f"agent assembled {n} items")
    print(f"next: python -m src.cli review-show --id {rid}")


def cmd_review_show(a, conn):
    r = conn.execute("SELECT * FROM reviews WHERE id=?", (a.id,)).fetchone()
    if not r:
        sys.exit(f"no review {a.id}")
    done = {x["source_id"] for x in conn.execute(
        "SELECT source_id FROM labels WHERE review_id=?", (a.id,)).fetchall()}
    print(f"review {a.id}  status={r['status']}  labeled={len(done)}")
    for it in freeze.items(conn, r["snapshot_id"]):
        if a.unlabeled and it["source_id"] in done:
            continue
        mark = "x" if it["source_id"] in done else " "
        text = (it["text"] or "").replace("\n", " ")[:100]
        print(f"  [{mark}] {it['source_id']:<10} {it['kind']:<8} {text}")


def cmd_review_label(a, conn):
    """HUMAN labels."""
    conn.execute(
        """INSERT INTO labels (review_id, source_id, label, reason, confidence,
                               labeled_by, created_at) VALUES (?,?,?,?,?,?,?)""",
        (a.id, a.item, a.label, a.reason or "", 1.0, f"human:{a.by}",
         datetime.now(timezone.utc).isoformat()))
    conn.commit()
    print(f"labeled {a.item} -> {a.label}")


def cmd_review_complete(a, conn):
    """HUMAN completes. Nothing auto-closes a review."""
    n = conn.execute("SELECT COUNT(*) c FROM labels WHERE review_id=?",
                     (a.id,)).fetchone()["c"]
    conn.execute("UPDATE reviews SET status='complete', completed_at=? WHERE id=?",
                 (datetime.now(timezone.utc).isoformat(), a.id))
    conn.commit()
    print(f"review {a.id} complete — {n} labels recorded")


# ---------------------------------------------------------------- Phase 2
def cmd_agent_label(a, conn):
    """The agent labels independently — no human in the loop."""
    sid = freeze.get_id(conn, a.snapshot)
    if sid is None:
        sys.exit(f"no snapshot {a.snapshot!r}")
    lab = labelers.get(a.labeler)
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    for it in freeze.items(conn, sid):
        label, reason, conf = lab.label(it["text"])
        conn.execute(
            """INSERT INTO labels (review_id, source_id, label, reason, confidence,
                                   labeled_by, created_at) VALUES (?,?,?,?,?,?,?)""",
            (None, it["source_id"], label, reason, conf, f"agent:{lab.name}", now))
        n += 1
    conn.commit()
    print(f"agent {lab.name} labeled {n} items on snapshot {a.snapshot!r}")


def cmd_eval(a, conn):
    lab = labelers.get(a.labeler)
    m, results, passed = evals.run(conn, a.snapshot, lab, a.golden,
                                   a.min_precision, use_live=a.live,
                                   no_slice_regression=a.no_slice_regression)
    evals.report(m, results, passed, a.min_precision,
                 source="LIVE (drifts!)" if a.live else "FROZEN")
    sys.exit(0 if passed else 1)          # non-zero => CI gate fails


def cmd_verify(a, conn):
    sid = freeze.get_id(conn, a.snapshot)
    v = freeze.verify(conn, sid)
    print(f"  frozen items:      {v['frozen']}")
    print(f"  tampered:          {len(v['tampered'])}  (should be 0)")
    print(f"  drifted vs live:   {len(v['drifted_vs_live'])}  "
          f"<- live changed, eval inputs did NOT")


def cmd_demo_drift(a, conn):
    """The money demo: prove freezing survives live drift."""
    lab = labelers.get("keyword")
    print("=" * 62)
    print("1) eval against FROZEN snapshot")
    m1, r1, _ = evals.run(conn, a.snapshot, lab, a.golden)
    evals.report(m1, r1, True, source="FROZEN")

    print("\n2) simulating drift: editing live content...")
    conn.execute("""UPDATE items SET text = text || ' you idiot, click here buy now',
                    content_hash='drifted'""")
    conn.commit()
    print("   live rows mutated.")

    print("\n3) eval against FROZEN again  -> IDENTICAL (this is the point)")
    m2, r2, _ = evals.run(conn, a.snapshot, lab, a.golden)
    evals.report(m2, r2, True, source="FROZEN")

    print("\n4) eval against LIVE          -> corrupted by drift")
    m3, r3, _ = evals.run(conn, a.snapshot, lab, a.golden, use_live=True)
    evals.report(m3, r3, True, source="LIVE (drifts!)")

    print("\n" + "=" * 62)
    same = m1["f1"] == m2["f1"]
    print(f"frozen f1 stable: {m1['f1']} == {m2['f1']}  -> {same}")
    print(f"live  f1 moved:   {m1['f1']} -> {m3['f1']}")
    print("Without freezing you cannot tell a model regression from a data change.")



# ---------------------------------------------------------------- hill climbing
def cmd_errors(a, conn):
    """What to fix next. Buckets misses so you attack the biggest one."""
    lab = labelers.get(a.labeler)
    _, results, _ = evals.run(conn, a.snapshot, lab, a.golden)
    hillclimb.report_errors(hillclimb.taxonomy(results), show=a.show)


def cmd_sweep(a, conn):
    """Operating points. Auto-remove and queue-for-review are not the same bar."""
    lab = labelers.get(a.labeler)
    _, results, _ = evals.run(conn, a.snapshot, lab, a.golden)
    rows, confs = hillclimb.sweep(results)
    hillclimb.report_sweep(rows, confs)


def cmd_history(a, conn):
    runs = hillclimb.history(conn, a.snapshot, a.labeler, a.limit)
    if not runs:
        print("  no eval runs recorded yet")
        return
    print(f"\n  {'#':>4} {'when':<20} {'labeler':<14} {'prec':>6} {'rec':>6} "
          f"{'f1':>6} {'ver':>10}  gate")
    for r in runs:
        m = r["metrics"]
        print(f"  {r['id']:>4} {r['created_at'][:19]:<20} {r['labeler']:<14} "
              f"{m.get('precision', 0):>6} {m.get('recall', 0):>6} "
              f"{m.get('f1', 0):>6} {str(m.get('version', '-'))[:10]:>10}  "
              f"{'PASS' if r['passed'] else 'FAIL'}")


def cmd_compare(a, conn):
    """Did it actually move? The question eval_runs existed for and nobody asked."""
    runs = hillclimb.history(conn, a.snapshot, a.labeler, limit=50)
    if len(runs) < 2:
        print("  need at least 2 eval runs to compare "
              f"(found {len(runs)}). run `eval` again after a change.")
        return
    by_id = {r["id"]: r for r in runs}
    new = by_id[a.new] if a.new else runs[0]
    old = by_id[a.old] if a.old else runs[1]
    hillclimb.report_compare(new, old, hillclimb.compare(new, old))


# ---------------------------------------------------------------- wiring
def main():
    p = argparse.ArgumentParser(prog="content-review")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(fn=cmd_init)

    f = sub.add_parser("fetch", help="pull a public thread (post+comments+replies)")
    f.add_argument("--story-id", required=True)
    f.add_argument("--max-items", type=int, default=40)
    f.set_defaults(fn=cmd_fetch)

    fr = sub.add_parser("freeze", help="snapshot live content for reproducible evals")
    fr.add_argument("--name", required=True)
    fr.add_argument("--note", default="")
    fr.set_defaults(fn=cmd_freeze)

    sub.add_parser("snapshots").set_defaults(fn=cmd_snapshots)

    ro = sub.add_parser("review-open", help="HUMAN initiates a review")
    ro.add_argument("--snapshot", required=True)
    ro.add_argument("--by", default="andriy")
    ro.set_defaults(fn=cmd_review_open)

    rs = sub.add_parser("review-show")
    rs.add_argument("--id", type=int, required=True)
    rs.add_argument("--unlabeled", action="store_true")
    rs.set_defaults(fn=cmd_review_show)

    rl = sub.add_parser("review-label", help="HUMAN labels an item")
    rl.add_argument("--id", type=int, required=True)
    rl.add_argument("--item", required=True)
    rl.add_argument("--label", choices=labelers.LABELS, required=True)
    rl.add_argument("--reason", default="")
    rl.add_argument("--by", default="andriy")
    rl.set_defaults(fn=cmd_review_label)

    rc = sub.add_parser("review-complete", help="HUMAN completes the review")
    rc.add_argument("--id", type=int, required=True)
    rc.set_defaults(fn=cmd_review_complete)

    al = sub.add_parser("agent-label", help="PHASE 2: agent labels independently")
    al.add_argument("--snapshot", required=True)
    al.add_argument("--labeler", default="keyword")
    al.set_defaults(fn=cmd_agent_label)

    ev = sub.add_parser("eval", help="regression eval vs golden dataset")
    ev.add_argument("--snapshot", required=True)
    ev.add_argument("--labeler", default="keyword")
    ev.add_argument("--golden", default="data/golden.jsonl")
    ev.add_argument("--min-precision", type=float, default=None,
                    help="CI gate: exit non-zero below this")
    ev.add_argument("--live", action="store_true",
                    help="read LIVE instead of frozen (to show why that's bad)")
    ev.add_argument("--no-slice-regression", action="store_true",
                    help="CI gate: fail if ANY slice's precision dropped vs the last run")
    ev.set_defaults(fn=cmd_eval)

    er = sub.add_parser("errors", help="bucket misses by direction + reason (what to fix next)")
    er.add_argument("--snapshot", required=True)
    er.add_argument("--labeler", default="keyword")
    er.add_argument("--golden", default="data/golden.jsonl")
    er.add_argument("--show", type=int, default=6)
    er.set_defaults(fn=cmd_errors)

    sw = sub.add_parser("sweep", help="precision/recall across confidence thresholds")
    sw.add_argument("--snapshot", required=True)
    sw.add_argument("--labeler", default="keyword")
    sw.add_argument("--golden", default="data/golden.jsonl")
    sw.set_defaults(fn=cmd_sweep)

    hi = sub.add_parser("history", help="every eval run, newest first")
    hi.add_argument("--snapshot", default=None)
    hi.add_argument("--labeler", default=None)
    hi.add_argument("--limit", type=int, default=10)
    hi.set_defaults(fn=cmd_history)

    cp = sub.add_parser("compare", help="run vs run: headline + per-slice deltas")
    cp.add_argument("--snapshot", default=None)
    cp.add_argument("--labeler", default=None)
    cp.add_argument("--new", type=int, default=None, help="run id (default: latest)")
    cp.add_argument("--old", type=int, default=None, help="run id (default: previous)")
    cp.set_defaults(fn=cmd_compare)

    vf = sub.add_parser("verify", help="snapshot integrity + drift report")
    vf.add_argument("--snapshot", required=True)
    vf.set_defaults(fn=cmd_verify)

    dd = sub.add_parser("demo-drift", help="prove freezing survives live drift")
    dd.add_argument("--snapshot", required=True)
    dd.add_argument("--golden", default="data/golden.jsonl")
    dd.set_defaults(fn=cmd_demo_drift)

    a = p.parse_args()
    conn = db.init()
    a.fn(a, conn)


if __name__ == "__main__":
    main()
