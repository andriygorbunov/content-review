#!/usr/bin/env bash
# Demo 2 — the improvement loop, and whether the scorer has signal.
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

hdr "DEMO 2 — hill climbing + kappa"
fresh_db climb

run python3 -m src.cli init
run python3 seed_demo.py
run python3 -m src.cli freeze --name base

say "1. What is broken? Bucketed by direction and cause, biggest first."
run python3 -m src.cli errors --snapshot base --labeler keyword

say "Both buckets are adversarial: quoted content causing FPs, obfuscation causing FNs."
say "v2 targets exactly those two — strips quoted spans, normalises leetspeak."

say "2. Record the baseline, then the targeted fix."
run python3 -m src.cli eval --snapshot base --labeler keyword
run python3 -m src.cli eval --snapshot base --labeler keyword-v2

say "3. Did it actually move?"
run python3 -m src.cli compare --snapshot base

say "Headline up 0.5714 -> 0.70, adversarial 0.0 -> 0.75 ... and ambiguous gained TWO"
say "false positives. The headline improved and the change broke something else."
say "That is the normal case, and it is why the per-slice gate exists."

say "4. Is the scorer tracking the human, or just the base rate?"
run python3 -m src.cli agreement --snapshot base --raters keyword,golden --by-slice
run python3 -m src.cli agreement --snapshot base --raters keyword-v2,golden --by-slice

say "v1: 61% raw agreement, kappa 0.20. Most of that agreement was free."
say "v2: 77% raw agreement, kappa 0.56. The scorer gained real signal, not luck."

say "5. So: shipped, or not?"
say "NOT yet. v1 was fp=3 fn=4; v2 is fp=3 fn=1. Total false positives did not"
say "move -- v2 relocated them, adversarial 3->1, ambiguous 0->2. The whole"
say "headline gain is recall. Precision rose because tp went 4->7, not because"
say "wrongful actions fell. One loop does not finish the job; it tells you the next one."
done_msg
