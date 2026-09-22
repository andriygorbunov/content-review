# content-review

[![evals](https://github.com/andriygorbunov/content-review/actions/workflows/evals.yml/badge.svg)](https://github.com/andriygorbunov/content-review/actions)

A content review system with an agentic labeler and a **drift-proof eval harness**.

Stdlib-only (SQLite + urllib). No API key needed to run everything except the LLM
labeler. Built to be understood in 5 minutes and demoed in 2.

---

## Why this exists

Live content drifts — posts get edited, comments get deleted, moderation state
changes. If your evals read live data, the same eval gives different numbers over
time and **you can no longer tell a model regression from a data change.**

This repo fixes that by freezing eval inputs into immutable snapshots. Prove it:

```bash
python3 -m src.cli demo-drift --snapshot base
```

```
1) eval against FROZEN     f1=1.0
2) simulating drift: editing live content...
3) eval against FROZEN     f1=1.0     <- identical. this is the point.
4) eval against LIVE       f1=0.667   <- corrupted by drift
```

---

## Quickstart

```bash
python3 -m src.cli init
python3 seed_demo.py                       # offline fake thread, or:
python3 -m src.cli fetch --story-id 42371420 # real public thread (post+comments+replies)

python -m src.cli freeze --name base       # snapshot -> evals become reproducible

# --- Phase 1: human-initiated, human-completed review ---
python3 -m src.cli review-open  --snapshot base          # HUMAN starts; agent assembles
python3 -m src.cli review-show  --id 1
python3 -m src.cli review-label --id 1 --item 3 --label violating --reason harassment
python3 -m src.cli review-complete --id 1                # HUMAN closes

# --- Phase 2: agent labels independently ---
python3 -m src.cli agent-label --snapshot base --labeler keyword
python3 -m src.cli eval --snapshot base --labeler keyword --min-precision 0.8
python3 -m src.cli verify --snapshot base

# --- Phase 3: the improvement loop ---
python3 -m src.cli errors  --snapshot base --labeler keyword    # what to fix first
python3 -m src.cli eval    --snapshot base --labeler keyword-v2 # make a targeted change
python3 -m src.cli compare --snapshot base                      # did it actually move?
python3 -m src.cli sweep   --snapshot base --labeler keyword-v2 # pick operating points
python3 -m src.cli history --snapshot base                      # the whole climb
```

`eval` exits non-zero when it fails the gate, so it drops straight into CI.

> **Note:** on network/FUSE mounts SQLite can throw `disk I/O error`.
> Set `export CR_DB=/tmp/review.db`.

---

## Architecture

```
fetch.py     public thread  -> items          (LIVE, mutable — drifts)
freeze.py    items          -> frozen_items   (IMMUTABLE — evals read only this)
labelers.py  text           -> (label, reason, confidence)
             KeywordLabeler = offline baseline;  LLMLabeler = the agent
evals.py     frozen + golden -> precision/recall/F1, per-slice, CI gate
hillclimb.py errors / sweep / compare -- the loop that turns a score into a gain
cli.py       review workflow: human opens -> agent assembles -> human labels/closes
```

### The improvement loop

Measuring is not improving. An eval tells you where you are; these answer what
to do about it.

| | |
|---|---|
| `errors` | misses bucketed by direction and cause, biggest first. FPs and FNs are **never** combined -- a false positive is a wrongful action against a real user, a false negative is a miss. Different costs, different fixes. |
| `sweep` | precision/recall across confidence cutoffs. You do not get one threshold: auto-remove needs high precision, queue-for-human-review can run far looser because a human catches the errors. |
| `compare` | run vs run, headline **and** per-slice. This is the question `eval_runs` existed for and nothing was asking. |
| `history` | every run with its version hash, so a delta is attributable to a change. |

Worked example, straight out of the demo seed:

```
v1  precision 0.5714   adversarial slice 0.0     <- fails exactly where it matters
    errors: 3 FP (2 spam pattern, 1 harassment), 4 FN (all "no pattern matched")

    -> both buckets are adversarial. FPs are QUOTED violating content;
       FNs are obfuscation (m0ron, "k i l l"). Fix those two specifically.

v2  precision 0.70     adversarial slice 0.75    fp 3 -> 1
    but: ambiguous slice fp 0 -> 2               <- REGRESSION, headline hid it
```

**The headline improved and the change made something worse.** That is the
normal case, it is why the per-slice gate exists, and
`eval --no-slice-regression` exits non-zero on it so CI catches it rather than
a person noticing three weeks later.

**Design decisions worth defending in an interview**

- **Freezing copies content, not references.** A snapshot that pointed at live
  rows would drift with them. `frozen_items` stores the text and its hash.
- **Baseline before model.** `KeywordLabeler` exists so "the LLM beat the
  baseline by X" is sayable. A score with no baseline means nothing.
- **Per-slice metrics.** Headline accuracy hides everything. Slices are
  `clear` / `ambiguous` / `adversarial`; the adversarial slice is where a
  safety system actually fails.
- **Precision-weighted gate.** In enforcement, a false positive means wrongful
  action against a real user — legally and reputationally worse than a miss.
  So the CI gate is on precision, and ambiguity resolves to `ok` (see `policy.md`).
- **Parser fails closed.** Models drift in output format; a bad parse becomes
  `ok`, never a crash and never an unintended enforcement.
- **Pinned model + temperature=0.** A moving model is a moving eval.
- **Precision is `n/a`, not `0.0`, when a slice has no predicted positives.**
  Zero reads as catastrophic failure; the honest answer is that the metric
  does not apply. A ratio with an empty denominator is the kind of bug that
  survives review because it still looks like a number.
- **Every run is stamped with a version hash** of the labeler's patterns,
  prompt and `policy.md`. Without it, "I changed the prompt and precision went
  up" is a claim rather than a measurement.

---

## 8-hour build plan

| Hr | Work | Done when |
|----|------|-----------|
| 1 | `init`, `fetch` a real thread, inspect the tree | ~40 items in `items` |
| 2 | Review workflow: open → show → label → complete | **Phase 1 done** |
| 3 | Hand-label the golden set (aim 80–120; 50% clear / 30% ambiguous / 20% adversarial) | `data/golden.jsonl` |
| 4 | `freeze` + `verify`; confirm snapshot integrity | snapshot listed, 0 tampered |
| 5 | `eval` with keyword baseline; read the per-slice table | baseline numbers recorded |
| 6 | Fill in `LLMLabeler._call()`; run `agent-label` | **Phase 2 agentic labeling done** |
| 7 | Compare LLM vs baseline; tune the gate; wire the GitHub Action | red build on regression |
| 8 | README polish + rehearse the 2-min walkthrough | demo runs clean |

**Stretch (only if hours remain):** LLM-as-judge for reasoning quality, plus
judge/human agreement (Cohen's κ) — an unvalidated judge is just vibes.

---

## The 2-minute walkthrough

> "This is a content review system. A human opens a review, the agent assembles
> the thread — post, comments, replies — the human labels and closes it. That's
> Phase 1. Phase 2 lets the agent label independently and adds a regression suite
> against a golden dataset.
>
> The interesting part is the freezing layer. Content drifts, so if evals read
> live data you can't separate a model regression from a data change. Snapshots
> copy content into an immutable table and evals read only that. Here — I'll
> corrupt the live rows and re-run: frozen score unchanged, live score collapses.
>
> I gate on precision rather than F1 because in enforcement a false positive is
> a wrongful action against a real user, which costs more than a miss.
>
> And the loop on top: `errors` buckets the misses so I know what to attack --
> here both buckets were adversarial, quoted content causing false positives
> and obfuscation causing false negatives. I fixed those two specifically in
> v2. `compare` shows the adversarial slice going 0.0 to 0.75 -- and it also
> shows I introduced two new false positives in the ambiguous slice. The
> headline went up and I still broke something. That is what the per-slice
> gate is for."
