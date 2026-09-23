#!/usr/bin/env bash
# Demo 3 — the LLM labeler. Run the model ONCE, replay everywhere.
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

hdr "DEMO 3 — LLM labeler"

if ! python3 -c "
from src.labelers import LLMLabeler
import inspect, sys
sys.exit(0 if 'NotImplementedError' not in inspect.getsource(LLMLabeler._call) else 1)
" 2>/dev/null; then
  echo
  echo "  ✗ LLMLabeler._call() is still a stub."
  echo "    Fill it in (src/labelers.py) and set ANTHROPIC_API_KEY, then rerun."
  echo
  exit 1
fi

fresh_db llm

run python3 -m src.cli init
run python3 seed_demo.py
run python3 -m src.cli freeze --name base

say "Baseline first — free, deterministic."
run python3 -m src.cli eval --snapshot base --labeler keyword

say "ONE pass over the model. ~18 calls. Everything after this replays it."
say "Without this the sequence below is ~90 calls and each block can disagree."
run python3 -m src.cli agent-label --snapshot base --labeler llm

run python3 -m src.cli eval --snapshot base --labeler llm
run python3 -m src.cli compare --snapshot base
run python3 -m src.cli errors --snapshot base --labeler llm
run python3 -m src.cli agreement --snapshot base --raters llm,golden --by-slice

say "And the sweep stops being a no-op: a regex emits one constant confidence,"
say "an LLM emits a spread — so this is a real operating-point curve."
run python3 -m src.cli sweep --snapshot base --labeler llm

say "I froze the data and left the model unfrozen. agent-label is the fix."
say "Re-base the CI gates now — 0.65 precision and 0.40 kappa were set for a regex."
done_msg
