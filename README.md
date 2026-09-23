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
export CR_DB=/tmp/ci_check.db && rm -f $CR_DB  # resets DB
python3 -m src.cli init
python3 seed_demo.py                       # offline fake thread, or:
python3 -m src.cli fetch --story-id 42371420 # real public thread (post+comments+replies)

python3 -m src.cli freeze --name base       # snapshot -> evals become reproducible

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

# --- Phase 4: is the scorer tracking the human, or the base rate? ---
python3 -m src.cli agreement --snapshot base --raters keyword,golden --by-slice
python3 -m src.cli agreement --snapshot base --raters keyword-v2,golden --by-slice
python3 -m src.cli agreement --snapshot base --raters keyword,keyword-v2,golden  # Fleiss
```

`eval` exits non-zero when it fails the gate, so it drops straight into CI.

> **Note:** on network/FUSE mounts SQLite can throw `disk I/O error`.
> Set `export CR_DB=/tmp/review.db`.

---

## Demo Flow

Two demos. **Run each in its own database** — `demo-drift` records LIVE eval runs, and
`compare` picks the two most recent runs for the snapshot, so sharing a DB makes the
hill-climbing comparison pick up a drifted live run instead of the v1 baseline. It produces a
plausible-looking number that is wrong, which is the worst kind.

---

**Runnable scripts** — one per demo, so you are not copy-pasting live:

```bash
./demo/0_human_loop.sh      # human review + agent-vs-human kappa
./demo/1_drift.sh           # frozen holds, live fails the gate
./demo/2_hillclimb.sh       # errors -> fix -> compare -> kappa
./demo/3_llm.sh             # requires LLMLabeler._call() to be filled in

NOPAUSE=1 ./demo/2_hillclimb.sh   # no keypresses, for a quick sanity run
```

Each script echoes the command, waits for you to hit return, then runs it — so you can talk
over each step. Each one also creates its own database, which is why they can be run in any
order. The commands below are the same ones, if you would rather drive manually.

### Demo 0 — the human in the loop, and whether the agent tracks them

Demos 1–3 score labelers against `data/golden.jsonl`. This one scores an agent against **a
person**, on the items that person actually reviewed.

```bash
export CR_DB=/tmp/demo_review.db && rm -f $CR_DB
python3 -m src.cli init
python3 seed_demo.py
python3 -m src.cli freeze --name base

python3 -m src.cli review-open  --snapshot base --by andriy     # HUMAN initiates
python3 -m src.cli review-show  --id 1                          # agent assembled the thread

python3 -m src.cli review-label --id 1 --item 3  --label violating --reason harassment
python3 -m src.cli review-label --id 1 --item 2  --label ok --reason benign
python3 -m src.cli review-label --id 1 --item 11 --label ok --reason "harsh, not abusive"
python3 -m src.cli review-label --id 1 --item 12 --label ok --reason "reporting abuse is not abuse"
python3 -m src.cli review-label --id 1 --item 15 --label violating --reason "obfuscated slur"
python3 -m src.cli review-label --id 1 --item 18 --label violating --reason "implied threat"

python3 -m src.cli review-complete --id 1                       # HUMAN closes

# Phase 2: the agent labels the same snapshot, independently
python3 -m src.cli agent-label --snapshot base --labeler keyword-v2

# did the agent track the human?
python3 -m src.cli agreement --snapshot base --raters keyword-v2,human:andriy
python3 -m src.cli agreement --snapshot base --raters keyword,human:andriy
```

```
review 1 opened by andriy on snapshot 'base' — agent assembled 18 items
review 1 complete — 6 labels recorded

keyword-v2 vs human:andriy   n=6  kappa=0.6667 (substantial)  observed=0.8333
keyword    vs human:andriy   n=6  kappa=0.0000 (slight)       observed=0.5000
```

**v1 scores exactly zero against the human.** Observed agreement 50%, expected 50% — on the six
items a person actually judged, it carried no signal at all. v2 reaches 0.6667. That is the same
climb as Demo 2, measured against a human instead of a file.

⚠️ **n=6.** A kappa on six items is indicative, not conclusive. Say that before anyone asks.

**Three things to land, and they are the ones that map to the role:**

1. **A human opens the review; the agent assembles.** The agent gathers the post, its comments
   and replies into one queue item. It does not decide. That ordering *is* the product — the tool
   removes the assembly work, not the judgement.
2. **Humans and agents write to the same table**, distinguished only by `labeled_by`
   (`human:andriy` vs `agent:keyword-v2`). That symmetry is why `agreement --raters
   keyword-v2,human:andriy` needs no special-casing: **a human is a rater like any other**, which
   is the premise the whole kappa argument rests on. Items nobody reviewed come back `None` and
   are skipped, so partial coverage is free.
3. **This is how the golden set stays honest at scale.** In *this* repo `golden.jsonl` was
   hand-labelled during the build, not produced by these commands — but the loop is the same:
   the cases the agent gets wrong are the cases worth routing to a human, and those answers
   become new golden entries. The eval gets harder as the labeler improves rather than staying
   a fixed bar that gets easier to clear.

> If only two demos fit, run this one and Demo 2. Demo 0 shows the product and that the agent
> tracks a person; Demo 2 shows you can prove an improvement and catch what it broke.

---

### Demo 1 — drift moves the live number, not the frozen one

```bash
export CR_DB=/tmp/demo_drift.db && rm -f $CR_DB
python3 -m src.cli init
python3 seed_demo.py
python3 -m src.cli freeze --name base

python3 -m src.cli demo-drift --snapshot base
python3 -m src.cli verify     --snapshot base
```

Expected:

```
  Gate floor 0.5 = the precision we shipped with.
  1. FROZEN  precision=0.5714  gate>=0.5 -> PASS   baseline
  2. LIVE    precision=0.5714  gate>=0.5 -> PASS   <- IDENTICAL: snapshot is a faithful copy
  3. introducing drift: editing live content...
  4. FROZEN  precision=0.5714  gate>=0.5 -> PASS   <- UNCHANGED. this is the point.
  5. LIVE    precision=0.4444  gate>=0.5 -> FAIL   <- the gate would fail the build

  frozen items: 18   tampered: 0   drifted vs live: 18
```

The frozen number is **0.5714**, which is mediocre. That is deliberate:

> Freezing does not protect the score. It protects the **attribution**. A frozen eval can fail,
> and should. What freezing buys is that when the number moves you know it was the model,
> because the data could not have.

---

### Demo 2 — the improvement loop, and whether the scorer has signal

```bash
export CR_DB=/tmp/demo_climb.db && rm -f $CR_DB
python3 -m src.cli init
python3 seed_demo.py
python3 -m src.cli freeze --name base

# 1. what is broken, bucketed, biggest first
python3 -m src.cli errors --snapshot base --labeler keyword

# 2. record the baseline, then the targeted fix
python3 -m src.cli eval --snapshot base --labeler keyword
python3 -m src.cli eval --snapshot base --labeler keyword-v2

# 3. did it actually move?
python3 -m src.cli compare --snapshot base

# 4. is the scorer tracking the human, or the base rate?
python3 -m src.cli agreement --snapshot base --raters keyword,golden    --by-slice
python3 -m src.cli agreement --snapshot base --raters keyword-v2,golden --by-slice
```

Expected:

```
errors (v1)     3 FP  (2 spam pattern, 1 harassment) — all adversarial
                4 FN  (all "no pattern matched")     — all adversarial

compare         precision    0.5714 -> 0.70    up
                adversarial  0.0    -> 0.75    up     fp 3 -> 1
                ambiguous    n/a    -> 0.0             fp 0 -> 2   <- REGRESSION
                clear        1.0    -> 1.0     =

kappa           v1  0.2025 (slight)    observed 0.6111
                v2  0.5610 (moderate)  observed 0.7778
```

**The three things to land:**

1. **The fix follows from the errors.** Both v1 buckets are adversarial — quoted content causing
   false positives, obfuscation causing false negatives. v2 strips quoted spans and normalises
   leetspeak. Targeted at a measured bucket, not a guess.
2. **The headline improved and the change broke something.** Adversarial went 0.0 → 0.75 while
   `ambiguous` picked up two new false positives. That is the normal case, it is why the
   per-slice gate exists, and `eval --no-slice-regression` exits non-zero on it.
   The blunt version: v1 was `fp=3 fn=4`, v2 is `fp=3 fn=1`. **Total false positives did not
   move** — v2 relocated them. The entire headline gain is recall (tp 4 → 7). So v2 does not
   ship; the next loop starts at `errors --labeler keyword-v2`, ambiguous bucket.
3. **Raw agreement is a liar.** v1 agrees with the human 61% of the time and has a kappa of
   0.20 — the marginals are skewed, so most of that agreement is free. Quote kappa, or quote
   both, never raw agreement alone.

Optional, if the conversation goes there:

```bash
python3 -m src.cli sweep   --snapshot base --labeler keyword-v2   # operating points
python3 -m src.cli history --snapshot base                        # the whole climb
python3 -m src.cli agreement --snapshot base --raters keyword,keyword-v2,golden   # Fleiss
```

---

### Demo 3 — the LLM labeler

`LLMLabeler` is a network call: it costs money, takes seconds per item, and gives a
slightly different answer each time. Run it **once** and replay.

```bash
export CR_DB=/tmp/demo_llm.db && rm -f $CR_DB
python3 -m src.cli init
python3 seed_demo.py
python3 -m src.cli freeze --name base

python3 -m src.cli eval --snapshot base --labeler keyword          # baseline, free

# ONE pass over the model. Everything after this replays it.
python3 -m src.cli agent-label --snapshot base --labeler llm

python3 -m src.cli eval      --snapshot base --labeler llm
python3 -m src.cli compare   --snapshot base
python3 -m src.cli errors    --snapshot base --labeler llm
python3 -m src.cli agreement --snapshot base --raters llm,golden --by-slice
python3 -m src.cli sweep     --snapshot base --labeler llm
```

Without `agent-label` first, that sequence is **~90 model calls** and each block can
disagree with the last. With it, it is 18 calls and every block reports the same numbers.
`--fresh` on any command forces re-invocation when you actually want it.

> **The point worth making out loud:** the snapshot pins the *inputs* so a rerun is
> byte-identical. Until `agent-label` is the single pass, nothing pins the *outputs* — and
> with a model you don't control, that is the same reproducibility problem the freezing
> layer exists to solve, one layer up. **I froze the data and left the model unfrozen.**

**What changes versus the keyword labelers:** `sweep` stops being a no-op. A regex emits one
constant confidence, so there is exactly one operating point and the command says so. An LLM
emits a spread, so the sweep produces a real precision/recall curve — which turns
*"auto-remove and queue-for-review are different bars"* from a claim into a table.

Re-base the CI gates afterwards. `--min-precision 0.65` and `--min-kappa 0.40` were set
against a regex; don't assume a model clears a floor built for `keyword-v2`.

---

## Architecture

```
fetch.py     public thread  -> items          (LIVE, mutable — drifts)
freeze.py    items          -> frozen_items   (IMMUTABLE — evals read only this)
labelers.py  text           -> (label, reason, confidence)
             KeywordLabeler = offline baseline;  LLMLabeler = the agent
evals.py     frozen + golden -> precision/recall/F1, per-slice, CI gate
hillclimb.py errors / sweep / compare -- the loop that turns a score into a gain
agreement.py Cohen's / Fleiss' kappa -- is the scorer tracking the human, or
             just the base rate? Chance-corrected agreement, per slice.
cli.py       review workflow: human opens -> agent assembles -> human labels/closes
```

### Validating the scorer: chance-corrected agreement

Precision tells you how often a flag was right. It does **not** tell you whether
the labeler is tracking the human or tracking the base rate. On a slice where
95% of items are `ok`, answering `ok` every time scores 95% raw agreement and
carries no signal at all.

`agreement` corrects for the agreement you'd expect from the marginals alone:
**Cohen's kappa** for two raters, **Fleiss' kappa** for three or more. `golden`
is treated as a rater like any other, so you can score labeler-vs-human or
labeler-vs-labeler with the same command.

Straight out of the demo seed:

```
keyword    vs golden   kappa 0.2025   observed 0.6111   <- paradox: 61% agreement, no signal
keyword-v2 vs golden   kappa 0.5610   observed 0.7778

  by slice (v1)                        by slice (v2)
    clear        kappa  1.0000           clear        kappa 1.0000
    ambiguous    kappa  n/a              ambiguous    kappa 0.0000
    adversarial  kappa -0.9600           adversarial  kappa 0.4167
```

Three things worth reading off that table:

- **The headline paradox.** v1 agrees with the human 61% of the time and has a
  kappa of 0.20. Raw agreement is inflated by skewed marginals. Quote kappa, or
  quote both — never raw agreement alone.
- **`ambiguous` kappa is `n/a`, not `0.0`.** Every golden label on that slice is
  `ok` and v1 said `ok` throughout, so expected agreement is 1.0 and the
  denominator vanishes. Same principle as precision being `n/a` on a slice with
  no predicted positives: an inapplicable ratio reported as a number is a bug
  that survives review because it still looks like a number.
- **`adversarial` at -0.96 is worse than chance.** A coin flip would have done
  better. That is the slice a safety system is actually judged on, and the
  headline F1 hides it completely.

**Landis & Koch bands** (`poor / slight / fair / moderate / substantial /
almost perfect`) are printed for readability. They are 1977 convention, weakly
justified — quote the number, not the adjective.

**Further reading:** Cohen (1960) · Fleiss (1971) · Landis & Koch (1977) ·
Feinstein & Cicchetti (1990), *"High agreement but low kappa"* — the paradox,
named. Cross-check any number against `sklearn.metrics.cohen_kappa_score`.

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
- **Golden coverage is asserted, not assumed.** Scoring loops over the rows that
  exist and skips labels with no matching row, so deleting content silently
  shrinks the denominator. In moderation the deleted content is
  disproportionately the *violating* content — so the eval set drifts toward
  easy cases and the metrics improve while nothing improved. `eval` now fails
  when labelled items are missing from the snapshot; `--allow-partial` makes
  scoring a subset a decision rather than a default.
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
