"""How big does an edge have to be before it is worth acting on?

`decision_analysis.py` used a hardcoded `_TRANSFER_DELTA_THRESHOLD = 1.0`
xP over three gameweeks. Measured against this project's own recorded
outcomes, that bar sits roughly an order of magnitude below the model's own
prediction error, which is why it fired on every single gameweek and
recommended a transfer every time.

The measurement, from `prediction_outcomes` (2026-09-19, n=54, after the
`actual_minutes` corruption was repaired):

    MAE per player per gameweek     2.79 pts
    stdev of signed error           3.89 pts
    bias (actual - predicted)      +1.07 pts

A transfer is a DIFFERENCE between two independent player projections, so
its error is roughly `sqrt(2)` times a single player's, and over a
three-gameweek horizon roughly `sqrt(3)` times again - about **9.5 points**.
Against that, a 1.0-point bar is noise. It is not a weak signal; it is no
signal at all.

The consequence was visible in the real ledger: a GW3 recommendation
projected at +9.24 realised as exactly 0 against doing nothing, having spent
a free transfer.

So the bar is derived from the measured error instead of asserted. What this
module does NOT do is claim more precision than n supports - below
`_MIN_SAMPLE` it returns the conservative fallback and says so, rather than
fitting a threshold to a handful of gameweeks.

## Deliberate conservatism

The swap-noise estimate treats the two players' errors as independent. They
are not perfectly independent (two players in the same fixture share a
scoreline), so the true noise is somewhat lower and this bar is somewhat
strict. That is the right direction to err: the failure mode being fixed is
acting too often on nothing, and a transfer not made is recoverable in a way
that a wasted free transfer is not.

The returned bar is a FRACTION of the noise estimate, not the whole of it.
Requiring an edge to exceed the full error bar would mean almost never
transferring, which is its own kind of wrong. `_NOISE_FRACTION` is the one
genuinely judgemental number here and is named so it can be argued with.
"""
import sqlite3
import statistics
from dataclasses import dataclass

# Below this many settled predictions, the error estimate is not worth
# fitting a decision rule to.
_MIN_SAMPLE = 30

# Used when there is not enough data to measure. Deliberately far above the
# old 1.0 and below the measured ~9.5 noise estimate - an honest "we do not
# know yet, so do not churn the squad on thin edges".
_FALLBACK_THRESHOLD = 4.0

# What share of the estimated swap noise an edge must exceed. Requiring the
# full error bar would mean effectively never transferring; requiring a tenth
# of it is what produced a transfer every week. Half is a judgement call,
# stated as one.
_NOISE_FRACTION = 0.5

# Never return a bar below this regardless of what the data says - a very
# low measured error early in a season (few, easy predictions) must not
# reopen the churn problem this module exists to close.
_ABSOLUTE_FLOOR = 2.0


@dataclass(frozen=True)
class MaterialityBar:
    """The threshold plus everything needed to explain it to a user who
    wants to know why their transfer was refused."""
    threshold: float
    horizon_gw: int
    sample_size: int
    mae: float | None
    error_stdev: float | None
    swap_noise: float | None
    measured: bool
    explanation: str


def transfer_materiality_bar(
    conn: sqlite3.Connection,
    horizon_gw: int = 3,
    season: str | None = None,
) -> MaterialityBar:
    """The minimum projected edge, in points over `horizon_gw` gameweeks,
    that a transfer must clear to be worth making.

    Reads only settled rows - a prediction without an outcome tells us
    nothing about error.
    """
    params: tuple = ()
    where = "predicted_median IS NOT NULL AND actual_points IS NOT NULL"
    if season is not None:
        where += " AND season=?"
        params = (season,)

    rows = conn.execute(
        f"SELECT predicted_median, actual_points FROM prediction_outcomes WHERE {where}",
        params,
    ).fetchall()

    n = len(rows)
    if n < _MIN_SAMPLE:
        return MaterialityBar(
            threshold=_FALLBACK_THRESHOLD,
            horizon_gw=horizon_gw,
            sample_size=n,
            mae=None,
            error_stdev=None,
            swap_noise=None,
            measured=False,
            explanation=(
                f"only {n} settled prediction(s) on record - too few to measure this model's own "
                f"error, so a conservative {_FALLBACK_THRESHOLD}pt bar over {horizon_gw} GW is used "
                f"rather than a fitted one"
            ),
        )

    errors = [r["actual_points"] - r["predicted_median"] for r in rows]
    mae = statistics.mean(abs(e) for e in errors)
    stdev = statistics.pstdev(errors)

    # Error on the DIFFERENCE of two independent projections, compounded
    # across the horizon.
    swap_noise = stdev * (2 ** 0.5) * (horizon_gw ** 0.5)
    threshold = max(swap_noise * _NOISE_FRACTION, _ABSOLUTE_FLOOR)

    return MaterialityBar(
        threshold=round(threshold, 2),
        horizon_gw=horizon_gw,
        sample_size=n,
        mae=round(mae, 2),
        error_stdev=round(stdev, 2),
        swap_noise=round(swap_noise, 2),
        measured=True,
        explanation=(
            f"measured from {n} settled predictions: MAE {mae:.2f}pt per player per GW, error stdev "
            f"{stdev:.2f}. A swap is a difference of two projections over {horizon_gw} GW, so its own "
            f"noise is about {swap_noise:.1f}pt - an edge smaller than {threshold:.1f}pt is not "
            f"distinguishable from that"
        ),
    )
