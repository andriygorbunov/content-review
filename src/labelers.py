"""Labelers. A labeler maps text -> (label, reason, confidence).

Two implementations on purpose:
  * KeywordLabeler — deterministic, offline, free. Your BASELINE. Evals are only
    meaningful relative to something; "the LLM beat the keyword baseline by X"
    is a real claim, "the LLM got 0.82" is not.
  * LLMLabeler     — the agentic one (Phase 2). Plug in your API key.
"""
import os
import re

from . import config

LABELS = ("violating", "ok")


class KeywordLabeler:
    """Deliberately dumb baseline. Also serves as a fallback so the whole
    pipeline runs with zero credentials."""
    name = "keyword-v1"

    PATTERNS = [
        (r"\b(kill|murder|attack)\s+(you|them|him|her)\b", "threat"),
        (r"\b(idiot|moron|scum|trash)\b", "harassment"),
        (r"\b(buy now|free money|crypto giveaway|click here)\b", "spam"),
        (r"\b(dox|home address|social security)\b", "privacy"),
    ]

    def label(self, text):
        t = (text or "").lower()
        for pattern, category in self.PATTERNS:
            if re.search(pattern, t):
                return "violating", f"matched {category} pattern", 0.6
        return "ok", "no pattern matched", 0.5


class KeywordLabelerV2:
    """v1 after one turn of the crank.

    Error analysis on v1 gave two buckets worth fixing:
      * FPs on QUOTED violating content -- reporting abuse is not abuse
      * FNs on OBFUSCATION -- m0ron, tr4sh, "k i l l" are the same abuse

    So: strip quoted spans before matching, and normalise leetspeak and
    inserted spacing. Both are targeted at a measured bucket, not guesses.

    It also gets WORSE somewhere, which is the honest part -- normalising
    aggressively makes the matcher fire on text it used to leave alone. That is
    what the per-slice gate is for, and why a headline improvement is not
    proof of an improvement.
    """
    name = "keyword-v2"

    LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "@": "a", "$": "s"})

    PATTERNS = KeywordLabeler.PATTERNS + [
        (r"\bi know where you (work|live)\b", "threat"),
        (r"\b(stupid|worst)\b", "harassment"),          # <- the regression
    ]

    @staticmethod
    def _normalise(text):
        t = (text or "").lower()
        t = re.sub(r'"[^"]*"', " ", t)                  # drop quoted spans
        t = t.translate(KeywordLabelerV2.LEET)
        t = re.sub(r"\b(?:\w\s){2,}\w\b",               # k i l l -> kill
                   lambda m: m.group(0).replace(" ", ""), t)
        return t

    def label(self, text):
        t = self._normalise(text)
        for pattern, category in self.PATTERNS:
            if re.search(pattern, t):
                return "violating", f"matched {category} pattern", 0.7
        return "ok", "no pattern matched", 0.5


class LLMLabeler:
    """Phase 2: the agent labels independently.

    TODO (~1h): pip install anthropic, then fill in _call().
    Keep temperature=0 and pin the model — a moving model is a moving eval.

    Credentials come from config.require(), which reads the process
    environment first and then a gitignored .env. The key is resolved lazily
    in _call() rather than at construction, so the rest of the pipeline —
    evals, hillclimb, agreement — runs with no credentials at all.
    """
    def __init__(self, model=None, policy_path="policy.md"):
        self.model = model or config.get("CR_LLM_MODEL", "claude-sonnet-5")
        self.name = f"llm:{self.model}"
        self.policy = (open(policy_path).read()
                       if os.path.exists(policy_path) else "")

    PROMPT = """You are a content policy reviewer. Apply ONLY the policy below.

POLICY:
{policy}

CONTENT:
{text}

Respond with exactly three lines:
LABEL: violating|ok
REASON: <one sentence citing the policy rule>
CONFIDENCE: <0.0-1.0>"""

    def _call(self, prompt):
        # api_key = config.require("ANTHROPIC_API_KEY")   # env, then .env
        #
        # --- fill this in ---
        # from anthropic import Anthropic
        # msg = Anthropic(api_key=api_key).messages.create(
        #     model=self.model, max_tokens=200, temperature=0,
        #     messages=[{"role": "user", "content": prompt}])
        # return msg.content[0].text
        raise NotImplementedError("Plug in your LLM client here")

    def label(self, text):
        raw = self._call(self.PROMPT.format(policy=self.policy, text=text or ""))
        return self._parse(raw)

    @staticmethod
    def _parse(raw):
        """Parsing is part of the product: models drift in format, so fail
        closed to 'ok' rather than crashing the pipeline."""
        label, reason, conf = "ok", "unparsed", 0.0
        for line in (raw or "").splitlines():
            low = line.lower()
            if low.startswith("label:"):
                v = line.split(":", 1)[1].strip().lower()
                label = v if v in LABELS else "ok"
            elif low.startswith("reason:"):
                reason = line.split(":", 1)[1].strip()
            elif low.startswith("confidence:"):
                try:
                    conf = float(line.split(":", 1)[1].strip())
                except ValueError:
                    conf = 0.0
        return label, reason, conf


def get(name):
    if name in ("keyword", "keyword-v1"):
        return KeywordLabeler()
    if name in ("keyword-v2", "v2"):
        return KeywordLabelerV2()
    if name == "llm":
        return LLMLabeler()
    raise SystemExit(f"unknown labeler: {name} "
                     "(use: keyword | keyword-v2 | llm)")
