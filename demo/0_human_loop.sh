#!/usr/bin/env bash
# Demo 0 — the human in the loop, and whether the agent tracks them.
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

hdr "DEMO 0 — human in the loop"
fresh_db review

run python3 -m src.cli init
run python3 seed_demo.py
run python3 -m src.cli freeze --name base

say "A HUMAN opens the review. The agent assembles the thread — it does not decide."
run python3 -m src.cli review-open --snapshot base --by andriy
run python3 -m src.cli review-show --id 1

say "The human judges six items: two clear, two ambiguous, two adversarial."
run python3 -m src.cli review-label --id 1 --item 3  --label violating --reason harassment
run python3 -m src.cli review-label --id 1 --item 2  --label ok --reason benign
run python3 -m src.cli review-label --id 1 --item 11 --label ok --reason "harsh, not abusive"
run python3 -m src.cli review-label --id 1 --item 12 --label ok --reason "reporting abuse is not abuse"
run python3 -m src.cli review-label --id 1 --item 15 --label violating --reason "obfuscated slur"
run python3 -m src.cli review-label --id 1 --item 18 --label violating --reason "implied threat"
run python3 -m src.cli review-complete --id 1

say "Phase 2: the agent labels the SAME snapshot, independently."
run python3 -m src.cli agent-label --snapshot base --labeler keyword-v2

say "Did the agent track the human? Humans and agents are both raters."
run python3 -m src.cli agreement --snapshot base --raters keyword-v2,human:andriy
run python3 -m src.cli agreement --snapshot base --raters keyword,human:andriy

say "v1 scores ZERO against the human — 50% agreement on a balanced set is a coin flip."
say "v2 reaches 0.67. Same climb as Demo 2, measured against a person not a file."
done_msg
