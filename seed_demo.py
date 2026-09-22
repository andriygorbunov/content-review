"""Offline seed: fake thread + golden labels, so the pipeline runs with no network.

Deliberately built so the v1 baseline FAILS on things worth failing on. A golden
set your baseline aces teaches you nothing — there is no hill to climb. The
errors here cluster into real buckets:

  * quoted violating content      -> keyword FPs (the pattern fires on a quote)
  * benign use of a flagged term  -> keyword FPs ("that crypto giveaway scam")
  * obfuscated abuse              -> keyword FNs (m0ron, k i l l)
  * implied threats               -> keyword FNs (no pattern to match)

Use `fetch` for real data; use this to develop and demo the improvement loop.
"""
from src import db, fetch

# (source_id, kind, parent, author, text, gold_label, slice)
ROWS = [
    # ---- clear: the baseline should get all of these -------------------
    ("1",  "post",    None, "alice", "Show HN: I built a tiny database", "ok", "clear"),
    ("2",  "comment", "1",  "bob",   "This is a great idea, congrats!", "ok", "clear"),
    ("3",  "comment", "1",  "carol", "You are an idiot and this is trash", "violating", "clear"),
    ("4",  "comment", "3",  "dave",  "Free money crypto giveaway click here", "violating", "clear"),
    ("5",  "comment", "1",  "erin",  "I disagree with the design, it wont scale", "ok", "clear"),
    ("6",  "comment", "5",  "frank", "Post his home address so we can talk", "violating", "clear"),
    ("7",  "comment", "1",  "gina",  "Nice writeup, the benchmarks are helpful", "ok", "clear"),
    ("8",  "comment", "1",  "hank",  "I will kill you if you ship this", "violating", "clear"),

    # ---- ambiguous: judgement calls, policy resolves to ok --------------
    ("9",  "comment", "1",  "iris",  "This is the worst thing I have read all week", "ok", "ambiguous"),
    ("10", "comment", "1",  "jack",  "Whoever approved this should be fired", "ok", "ambiguous"),
    ("11", "comment", "1",  "kim",   "That design decision is genuinely stupid", "ok", "ambiguous"),

    # ---- adversarial: where a safety system actually fails --------------
    # quoted violating content -- reporting abuse is not abuse
    ("12", "comment", "1",  "lena",  'Someone DMed me "you are an idiot", is that reportable?', "ok", "adversarial"),
    ("13", "comment", "1",  "mo",    'The mod said "click here for free money" was spam, agreed', "ok", "adversarial"),
    # benign use of a flagged term
    ("14", "comment", "1",  "nina",  "That crypto giveaway scam is everywhere lately, avoid it", "ok", "adversarial"),
    # obfuscation -- same abuse, pattern does not match
    ("15", "comment", "1",  "omar",  "you are such a m0ron honestly", "violating", "adversarial"),
    ("16", "comment", "1",  "pia",   "go k i l l yourself", "violating", "adversarial"),
    ("17", "comment", "1",  "quinn", "what a piece of tr4sh you are", "violating", "adversarial"),
    # implied threat -- no keyword exists for this
    ("18", "comment", "1",  "raj",   "I know where you work and I will be there tomorrow", "violating", "adversarial"),
]

conn = db.init()
fetch.save(conn, [{"source_id": i, "kind": k, "parent_source_id": p, "author": a,
                   "text": t, "url": ""} for i, k, p, a, t, _, _ in ROWS])
with open("data/golden.jsonl", "w") as f:
    for sid, _, _, _, _, lab, sl in ROWS:
        f.write('{"source_id": "%s", "label": "%s", "slice": "%s"}\n' % (sid, lab, sl))

n_adv = sum(1 for r in ROWS if r[6] == "adversarial")
print(f"seeded {len(ROWS)} items + {len(ROWS)} golden labels "
      f"({n_adv} adversarial)")
