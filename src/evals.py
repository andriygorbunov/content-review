"""Regression evals against a golden dataset.

Reads FROZEN items only, so a run is reproducible no matter what happened to
the live thread afterwards.
"""
import json
from datetime import datetime, timezone

from . import db, freeze


def load_golden(path="data/golden.jsonl"):
    """{"source_id": "...", "label": "violating|ok", "slice": "clear|ambiguous|adversarial"}"""
    gold = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            row = json.loads(line)
            gold[str(row["source_id"])] = row
    return gold


def _metrics(results):
    """Binary, positive class = 'violating'."""
    tp = sum(1 for r in results if r["gold"] == "violating" and r["pred"] == "violating")
    fp = sum(1 for r in results if r["gold"] == "ok" and r["pred"] == "violating")
    fn = sum(1 for r in results if r["gold"] == "violating" and r["pred"] == "ok")
    tn = sum(1 for r in results if r["gold"] == "ok" and r["pred"] == "ok")
    # A slice with no predicted positives has NO precision - not zero
    # precision. Reporting 0.0 there reads as catastrophic failure and is the
    # kind of metric bug that survives review because it looks like a number.
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    _p, _r = precision or 0.0, recall or 0.0
    f1 = 2 * _p * _r / (_p + _r) if _p + _r else 0.0
    total = len(results)
    return {
        "n": total, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "f1": round(f1, 4),
        "accuracy": round((tp + tn) / total, 4) if total else 0.0,
    }


def run(conn, snapshot_name, labeler, golden_path="data/golden.jsonl",
        min_precision=None, use_live=False, no_slice_regression=False):
    sid = freeze.get_id(conn, snapshot_name)
    if sid is None:
        raise SystemExit(f"no snapshot named {snapshot_name!r}")

    gold = load_golden(golden_path)
    rows = freeze.live_items(conn) if use_live else freeze.items(conn, sid)

    results = []
    for r in rows:
        g = gold.get(str(r["source_id"]))
        if not g:
            continue                      # only score what's labeled
        pred, reason, conf = labeler.label(r["text"])
        results.append({
            "source_id": r["source_id"],
            "slice": g.get("slice", "clear"),
            "gold": g["label"], "pred": pred,
            "reason": reason, "confidence": conf,
            "correct": g["label"] == pred,
        })

    m = _metrics(results)
    # per-slice: where a model is weak matters more than the headline number
    m["by_slice"] = {}
    for s in sorted({r["slice"] for r in results}):
        m["by_slice"][s] = _metrics([r for r in results if r["slice"] == s])

    passed = True if min_precision is None else (m["precision"] or 0.0) >= min_precision

    # A gate on the headline number alone can pass while the slice that
    # actually matters gets worse. Fail if any slice's precision dropped
    # against the previous run of the same labeler on the same snapshot.
    slice_regressions = []
    if no_slice_regression:
        prev = conn.execute(
            """SELECT metrics_json FROM eval_runs
               WHERE snapshot_id=? AND labeler=? ORDER BY id DESC LIMIT 1""",
            (sid, labeler.name)).fetchone()
        if prev:
            old = json.loads(prev["metrics_json"]).get("by_slice", {})
            for s, sm in m["by_slice"].items():
                prev_s = old.get(s, {})
                was = prev_s.get("precision")
                if was is not None and sm["precision"] is not None and sm["precision"] < was:
                    slice_regressions.append(
                        f"{s} precision: {was} -> {sm['precision']}")
                # precision going n/a -> 0.0 is not a numeric drop, but new
                # false positives are new wrongful actions. Count them.
                if sm["fp"] > prev_s.get("fp", 0):
                    slice_regressions.append(
                        f"{s} false positives: {prev_s.get('fp', 0)} -> {sm['fp']}")
            if slice_regressions:
                passed = False
    m["slice_regressions"] = slice_regressions

    version = db.labeler_version(labeler)
    m["version"] = version
    conn.execute(
        """INSERT INTO eval_runs
             (snapshot_id, labeler, created_at, metrics_json, passed, version)
           VALUES (?,?,?,?,?,?)""",
        (sid, labeler.name, datetime.now(timezone.utc).isoformat(),
         json.dumps(m), int(passed), version),
    )
    conn.commit()
    return m, results, passed


def report(m, results, passed, min_precision=None, source="FROZEN"):
    print(f"\n  reading from: {source}")
    _f = lambda v: "n/a" if v is None else v
    print(f"  n={m['n']}  precision={_f(m['precision'])}  recall={_f(m['recall'])}  "
          f"f1={m['f1']}  acc={m['accuracy']}")
    print(f"  tp={m['tp']} fp={m['fp']} fn={m['fn']} tn={m['tn']}")
    for s, sm in m["by_slice"].items():
        note = "" if sm["precision"] is not None else "   (no predicted positives)"
        print(f"    slice {s:<12} n={sm['n']:<3} precision={_f(sm['precision'])} "
              f"recall={_f(sm['recall'])}{note}")
    # split, never combined: a false positive is a wrongful action against a
    # real user; a false negative is a miss. Different costs, different fixes.
    fps = [r for r in results if not r["correct"] and r["pred"] == "violating"]
    fns = [r for r in results if not r["correct"] and r["pred"] == "ok"]
    for rows, title in ((fps, "FALSE POSITIVES (wrongful action)"),
                        (fns, "FALSE NEGATIVES (left up)")):
        if rows:
            print(f"  {title} ({len(rows)}):")
            for r in rows[:6]:
                print(f"    {r['source_id']}  [{r['slice']}] {r['reason'][:50]}")
    if m.get("slice_regressions"):
        print(f"\n  SLICE REGRESSIONS ({len(m['slice_regressions'])}):")
        for s in m["slice_regressions"]:
            print(f"    {s}")
    if min_precision is not None or m.get("slice_regressions"):
        bar = f"precision >= {min_precision}" if min_precision is not None else "no slice regression"
        print(f"\n  gate: {bar} -> {'PASS' if passed else 'FAIL'}")
    if m.get("version"):
        print(f"  version: {m['version']}")
    return passed
