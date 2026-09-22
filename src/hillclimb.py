"""The improvement loop.

Measuring is not improving. `evals.py` tells you where you are; this module is
how you get somewhere better and *prove* you did:

    errors   -> which mistakes, bucketed, biggest first   (what to attack)
    sweep    -> precision/recall across confidence cutoffs (pick an operating point)
    compare  -> this run vs the last, headline and per-slice (did it actually move?)

Without `compare`, runs pile up in eval_runs and nobody ever answers the only
question that matters: is it better than yesterday.
"""
import json
from collections import Counter

from . import freeze


# ── error taxonomy ──────────────────────────────────────────────────
# Headline metrics say how much you're wrong. These say *how* you're wrong,
# which is the only version you can act on.

def taxonomy(results):
    """Bucket misses by (direction, stated reason, slice), biggest first.

    Direction matters more than count: in enforcement a false positive is a
    wrongful action against a real user, a false negative is a miss. Different
    costs, different fixes, never the same bucket.
    """
    fp, fn = [], []
    for r in results:
        if r["correct"]:
            continue
        (fp if r["pred"] == "violating" else fn).append(r)

    def buckets(rows):
        c = Counter((r["reason"], r["slice"]) for r in rows)
        return [{"reason": k[0], "slice": k[1], "n": n}
                for k, n in c.most_common()]

    return {
        "fp": {"n": len(fp), "buckets": buckets(fp), "rows": fp},
        "fn": {"n": len(fn), "buckets": buckets(fn), "rows": fn},
    }


def report_errors(tax, show=6):
    total = tax["fp"]["n"] + tax["fn"]["n"]
    print(f"\n  ERROR TAXONOMY  ({total} misses)")
    for kind, label, cost in (
        ("fp", "FALSE POSITIVES", "wrongful action against a real user"),
        ("fn", "FALSE NEGATIVES", "violating content left up"),
    ):
        d = tax[kind]
        print(f"\n  {label}: {d['n']}   ({cost})")
        if not d["n"]:
            print("    none")
            continue
        for b in d["buckets"][:show]:
            bar = "#" * min(b["n"], 30)
            print(f"    {b['n']:>3}  {bar:<30}  [{b['slice']}] {b['reason'][:44]}")
        if d["buckets"]:
            top = d["buckets"][0]
            print(f"    -> biggest bucket: {top['n']}/{d['n']} "
                  f"({top['n']/d['n']*100:.0f}%) — fix this one first")


# ── confidence threshold sweep ──────────────────────────────────────
# You do not get one threshold. Auto-remove needs high precision; queue-for-
# human-review can run much looser because a human catches the errors. This
# is how you find those operating points instead of guessing them.

def sweep(results, thresholds=None):
    if thresholds is None:
        thresholds = [round(x / 20, 2) for x in range(0, 21)]

    confs = {r["confidence"] for r in results if r["pred"] == "violating"}
    rows = []
    for t in thresholds:
        tp = fp = fn = 0
        for r in results:
            pred = "violating" if (r["pred"] == "violating"
                                   and r["confidence"] >= t) else "ok"
            if r["gold"] == "violating" and pred == "violating":
                tp += 1
            elif r["gold"] == "ok" and pred == "violating":
                fp += 1
            elif r["gold"] == "violating" and pred == "ok":
                fn += 1
        p = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * rc / (p + rc) if p + rc else 0.0
        rows.append({"t": t, "precision": round(p, 4),
                     "recall": round(rc, 4), "f1": round(f1, 4),
                     "flagged": tp + fp})
    return rows, sorted(confs)


def report_sweep(rows, distinct_confs, targets=(0.95, 0.90, 0.80)):
    print("\n  CONFIDENCE SWEEP")
    if len(distinct_confs) <= 2:
        print(f"    labeler emits only {len(distinct_confs)} distinct confidence "
              f"value(s): {distinct_confs}")
        print("    -> sweep is uninformative here. A baseline with constant "
              "confidence has")
        print("       exactly one operating point. This becomes meaningful with "
              "the LLM labeler.")
    print(f"\n    {'thresh':>7} {'prec':>7} {'recall':>7} {'f1':>7} {'flagged':>8}")
    for r in rows:
        if r["flagged"] == 0 and r["t"] > 0:
            continue
        print(f"    {r['t']:>7} {r['precision']:>7} {r['recall']:>7} "
              f"{r['f1']:>7} {r['flagged']:>8}")

    print("\n    operating points — lowest threshold still hitting each precision bar:")
    for want in targets:
        ok = [r for r in rows if r["precision"] >= want and r["flagged"] > 0]
        if ok:
            b = min(ok, key=lambda r: r["t"])
            print(f"      precision>={want}:  t={b['t']}  recall={b['recall']}  "
                  f"flags {b['flagged']} items")
        else:
            print(f"      precision>={want}:  unreachable at any threshold")


# ── run-over-run comparison ─────────────────────────────────────────

def history(conn, snapshot_name=None, labeler=None, limit=10):
    sql = ("SELECT r.id, r.labeler, r.created_at, r.metrics_json, r.passed, "
           "s.name AS snapshot FROM eval_runs r "
           "LEFT JOIN snapshots s ON s.id = r.snapshot_id WHERE 1=1")
    args = []
    if snapshot_name:
        sql += " AND s.name = ?"; args.append(snapshot_name)
    if labeler:
        sql += " AND r.labeler = ?"; args.append(labeler)
    sql += " ORDER BY r.id DESC LIMIT ?"; args.append(limit)
    out = []
    for row in conn.execute(sql, args):
        d = dict(row)
        d["metrics"] = json.loads(d.pop("metrics_json"))
        out.append(d)
    return out


def _arrow(delta, tol=1e-9):
    if delta is None:
        return "  ? "
    if delta > tol:
        return "up  "
    if delta < -tol:
        return "DOWN"
    return "  = "


def _delta(a, b):
    """None means 'not applicable' (no predicted positives), not zero.
    Subtracting it would invent a number that doesn't exist."""
    if a is None or b is None:
        return None
    return round(a - b, 4)


def compare(new, old):
    """Deltas for headline and every slice present in either run."""
    out = {"headline": {}, "by_slice": {}, "regressions": []}
    for k in ("precision", "recall", "f1", "n"):
        a, b = new["metrics"].get(k), old["metrics"].get(k)
        out["headline"][k] = {"new": a, "old": b, "delta": _delta(a, b)}

    slices = set(new["metrics"].get("by_slice", {})) | set(old["metrics"].get("by_slice", {}))
    for s in sorted(slices):
        a = new["metrics"].get("by_slice", {}).get(s, {})
        b = old["metrics"].get("by_slice", {}).get(s, {})
        d = {}
        for k in ("precision", "recall"):
            av, bv = a.get(k), b.get(k)
            d[k] = {"new": av, "old": bv, "delta": _delta(av, bv)}
            if av is not None and bv is not None and av < bv:
                out["regressions"].append(f"{s}.{k}: {bv} -> {av}")
        # A slice that had NO predicted positives and now has wrong ones is a
        # regression even though precision went from n/a to a number. Count
        # false positives, not the ratio - the ratio hides it.
        fp_new, fp_old = a.get("fp", 0), b.get("fp", 0)
        if fp_new > fp_old:
            out["regressions"].append(
                f"{s}.false_positives: {fp_old} -> {fp_new}  (new wrongful actions)")
        d["fp"] = {"new": fp_new, "old": fp_old, "delta": fp_new - fp_old}
        out["by_slice"][s] = d
    return out


def report_compare(new, old, cmp):
    print(f"\n  COMPARE  run #{new['id']} ({new['labeler']}) "
          f"vs run #{old['id']} ({old['labeler']})")
    print(f"    {old['created_at'][:19]}  ->  {new['created_at'][:19]}")
    f = lambda v: "n/a" if v is None else f"{v}"
    dz = lambda v: "     -" if v is None else f"{v:+9.4f}"
    h = cmp["headline"]
    print(f"\n    {'metric':<12}{'old':>8}{'new':>8}{'delta':>10}")
    for k in ("precision", "recall", "f1"):
        v = h[k]
        print(f"    {k:<12}{f(v['old']):>8}{f(v['new']):>8}{dz(v['delta']):>10}  "
              f"{_arrow(v['delta'])}")

    print(f"\n    per-slice precision          (fp = false positives)")
    for s, d in cmp["by_slice"].items():
        v, fpv = d["precision"], d["fp"]
        print(f"      {s:<14}{f(v['old']):>8}{f(v['new']):>8}{dz(v['delta']):>10}  "
              f"{_arrow(v['delta'])}   fp {fpv['old']}->{fpv['new']}")

    if cmp["regressions"]:
        print(f"\n    ⚠ REGRESSIONS ({len(cmp['regressions'])}):")
        for r in cmp["regressions"]:
            print(f"      {r}")
        print("    a headline that improves while a slice regresses is the "
              "failure per-slice")
        print("    metrics exist to catch. adversarial is the one that matters.")
    else:
        print("\n    no slice regressions")
