#!/usr/bin/env bash
# Demo 1 — drift moves the live number, not the frozen one.
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

hdr "DEMO 1 — data drift"
fresh_db drift

run python3 -m src.cli init
run python3 seed_demo.py
run python3 -m src.cli freeze --name base

say "Five steps: frozen baseline, live matches it, drift, frozen holds, live fails the gate."
run python3 -m src.cli demo-drift --snapshot base

say "And the integrity view: 18 rows drifted in live, zero tampered in the snapshot."
run python3 -m src.cli verify --snapshot base

say "The frozen number is 0.5714 — mediocre, and that is the point."
say "Freezing does not protect the score. It protects the ATTRIBUTION."
done_msg
