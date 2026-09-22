"""Inter-rater agreement — Cohen's kappa and Fleiss' kappa.

WHY THIS EXISTS
  An eval tells you how often the labeler matched the golden set. It does not
  tell you whether that match is better than chance. On a skewed slice — say
  95% of items are `ok` — a labeler that answers `ok` every single time scores
  95% "agreement" while carrying no signal whatsoever.

  Kappa corrects observed agreement for the agreement you would expect from the
  marginals alone. It is the standard answer to "is this automated scorer
  actually tracking the human, or is it tracking the base rate?"

  Cohen's kappa   two raters   (labeler vs golden, or labeler A vs labeler B)
  Fleiss' kappa   three+       (several labelers scored against each other)

THE PARADOX YOU WILL SEE IN YOUR OWN DATA — this is the point of the module
  High observed agreement can produce a LOW or UNDEFINED kappa when the
  marginals are lopsided, because expected-by-chance agreement is also high.
  Run `agreement --by-slice` and look at `ambiguous`: every golden label there
  is `ok`, so if the labeler also says `ok` throughout, observed agreement is
  1.0, expected agreement is 1.0, and kappa is 0/0.

  We return None for that, not 0.0 — same reason precision is `n/a` rather than
  zero on a slice with no predicted positives. A ratio with an empty
  denominator is not a bad score, it is an inapplicable one, and reporting it
  as a number is the kind of bug that survives review because it still looks
  like a number.

  Report kappa and observed agreement TOGETHER. Either one alone misleads.

FLEISS IS NOT COHEN GENERALISED — this looks like a bug and isn't
  The natural assumption is that Fleiss' kappa collapses back to Cohen's when
  you give it two raters. It does not. Fleiss reduces to **Scott's pi**, which
  computes expected agreement from the two raters' POOLED marginal
  distribution; Cohen multiplies each rater's OWN marginals. Those are
  different quantities whenever the raters use the categories at even slightly
  different rates, so the same two-rater data yields two different numbers:

      Cohen's  kappa=0.2500  expected=0.5000   (per-rater marginals, multiplied)
      Fleiss'  kappa=0.2381  expected=0.5078   (pooled marginals = Scott's pi)
      observed agreement identical in both: 0.6250

  Neither is wrong. They encode different assumptions about what "chance"
  means — Cohen lets each rater have their own bias, Scott's assumes both draw
  from one shared distribution. Pick one per report and say which.

INTERPRETATION
  The Landis & Koch (1977) bands below are convention, not statistics. They are
  widely quoted and weakly justified; a kappa of 0.62 is "substantial" only
  because someone drew a line there in 1977. Quote the number, mention the band
  if it helps a reader, and never argue from the band alone.

FURTHER READING
  Cohen (1960) "A Coefficient of Agreement for Nominal Scales"
  Fleiss (1971) "Measuring Nominal Scale Agreement Among Many Raters"
  Landis & Koch (1977) "The Measurement of Observer Agreement for Categorical Data"
  Feinstein & Cicchetti (1990) "High agreement but low kappa" — the paradox, named
  scikit-learn: sklearn.metrics.cohen_kappa_score  (cross-check your numbers)
"""
from collections import Counter

# Landis & Koch (1977): <0 poor · 0-.20 slight · .21-.40 fair · .41-.60 moderate
# · .61-.80 substantial · .81-1.0 almost perfect. Convention, not law.
BANDS = [
    (0.00, "slight"), (0.21, "fair"), (0.41, "moderate"),
    (0.61, "substantial"), (0.81, "almost perfect"),
]


def band(k):
    """Human-readable band for a kappa. None in, None out."""
    if k is None:
        return "n/a"
    if k < 0:
        return "worse than chance"
    label = "poor"
    for floor, name in BANDS:
        if k >= floor:
            label = name
    return label


def cohens_kappa(a, b):
    """Two aligned label sequences -> (kappa, observed, expected, n).

    kappa is None when expected agreement is 1.0 (the denominator vanishes):
    both raters used a single category throughout, so there is no variance to
    agree about. That is the paradox case, not a failure.
    """
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    n = len(pairs)
    if n == 0:
        return None, None, None, 0

    observed = sum(1 for x, y in pairs if x == y) / n

    ma, mb = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    cats = set(ma) | set(mb)
    expected = sum((ma[c] / n) * (mb[c] / n) for c in cats)

    if abs(1.0 - expected) < 1e-12:
        return None, observed, expected, n          # undefined, not zero
    return (observed - expected) / (1.0 - expected), observed, expected, n


def fleiss_kappa(ratings):
    """ratings: list of per-item Counters mapping category -> number of raters.

    Every item must carry the same rater count; items that don't are skipped.
    Returns (kappa, observed, expected, n_items, n_raters).
    """
    rows = [r for r in ratings if sum(r.values()) > 1]
    if not rows:
        return None, None, None, 0, 0

    counts = Counter(sum(r.values()) for r in rows)
    n_raters = counts.most_common(1)[0][0]
    rows = [r for r in rows if sum(r.values()) == n_raters]
    n_items = len(rows)
    if n_items == 0:
        return None, None, None, 0, 0

    cats = sorted({c for r in rows for c in r})

    # P_i: proportion of agreeing rater PAIRS on item i
    p_i = [
        (sum(r.get(c, 0) ** 2 for c in cats) - n_raters) / (n_raters * (n_raters - 1))
        for r in rows
    ]
    observed = sum(p_i) / n_items

    # p_j: overall share of assignments to each category
    total = n_items * n_raters
    p_j = {c: sum(r.get(c, 0) for r in rows) / total for c in cats}
    expected = sum(v ** 2 for v in p_j.values())

    if abs(1.0 - expected) < 1e-12:
        return None, observed, expected, n_items, n_raters
    return (observed - expected) / (1.0 - expected), observed, expected, n_items, n_raters


# ------------------------------------------------------------------ reporting
def _fmt(v):
    return "n/a" if v is None else f"{v:.4f}"


def report_cohen(name_a, name_b, stats, by_slice=None, min_kappa=None):
    k, obs, exp, n = stats
    print(f"\n  Cohen's kappa — {name_a} vs {name_b}")
    print(f"  n={n}  kappa={_fmt(k)} ({band(k)})  observed={_fmt(obs)}  expected={_fmt(exp)}")
    if k is None and obs is not None:
        print("    kappa undefined: expected agreement is 1.0 — both raters used a")
        print("    single category, so there is no variance to agree about.")
    elif k is not None and obs is not None and obs - k > 0.30:
        print(f"    NOTE: observed {obs:.2f} but kappa {k:.2f}. Skewed marginals are")
        print("    inflating raw agreement — this is the 'high agreement, low kappa'")
        print("    paradox. The raw number is not the one to quote.")

    if by_slice:
        print("\n  by slice:")
        for s, st in by_slice.items():
            sk, so, _se, sn = st
            print(f"    {s:<12} n={sn:<3} kappa={_fmt(sk):<8} observed={_fmt(so):<8} {band(sk)}")

    passed = True
    if min_kappa is not None:
        passed = k is not None and k >= min_kappa
        print(f"\n  gate: kappa >= {min_kappa} -> {'PASS' if passed else 'FAIL'}")
        if k is None:
            print("    (undefined kappa fails the gate: no evidence of signal)")
    return passed


def report_fleiss(names, stats):
    k, obs, exp, n_items, n_raters = stats
    print(f"\n  Fleiss' kappa — {n_raters} raters: {', '.join(names)}")
    print(f"  items={n_items}  kappa={_fmt(k)} ({band(k)})  "
          f"observed={_fmt(obs)}  expected={_fmt(exp)}")
    if k is None:
        print("    kappa undefined: expected agreement is 1.0.")
