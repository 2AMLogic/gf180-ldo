"""The loop-margin semantics shared by the loop-gain benches (issue #630).

The DR-0001 margin bars, the DR-0008 resurgence precondition, the AC band and
resolution, the PVT grid axes and the ``Row`` margin verdicts were defined in
``sim/loop-stability/testbench/sweep.py``. A second loop-gain bench
(``sim/soft-start-loop-gain/``) needs the *same* objects -- its whole claim
to comparability with ``sim/loop-stability/``'s records rests on the two
using the same bars, the same AC band and resolution, and the same margin
semantics -- and reached them by loading that driver by filesystem path,
which leaked its bench directory into ``sys.path`` and shadowed the
borrowing bench's own modules. They live here instead: one definition under
``harness/``, imported by name by both benches, with both identities asserted
by ``sim/tests/test_soft_start_loop_gain.py``. Nothing is copied, so nothing
can drift.
"""

from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import deck as deck_mod
from .report import parse_row_fields as _harness_parse_row_fields

# --- the ratified matrix (DR-0001 section "Consequences") --------------------
PROCESS_CORNERS = ("tt", "ff", "ss", "fs", "sf", "res_ff", "res_ss")
TEMPS_C = (-40.0, 27.0, 125.0)
NOMINAL_SUPPLY_V = 3.3
SUPPLY_TOL = 0.10

# DR-0001 stability criterion.
PM_MIN_DEG = 45.0
GM_MIN_DB = 10.0

# DR-0008's precondition check (issue #59), reported and failed SEPARATELY
# from the two DR-0001 bars above. A phase/gain margin read off a Bode plot is
# only a stability test when T(s) has no right-half-plane poles; the cheapest
# frequency-domain signature of that precondition failing is |T| climbing back
# above 0 dB somewhere above its first 0 dB crossing. For a loop that rolls
# off monotonically through crossover this quantity is negative by
# construction, so the bar is "<= 0 dB" with no engineering slack in it.
#
# This is necessary-but-not-sufficient evidence of an RHP pole pair -- a
# well-damped but under-margined loop can resurge without one -- so it does
# NOT replace sim/amp-selfosc/'s time-domain measurement, which stays the
# load-bearing check per DR-0008.
RESURGENCE_MAX_DB = 0.0

# Regulation target, and how far a point's DC output may sit from it before the
# run is treated as void. VOUT_NOM_V is set by the design's own divider and
# reference (VREF = 1.2 V driven by the deck's own Vref since #174/DR-0021,
# Rtop = 300k, Rbot = 600k => 1.2 * 900/600 = 1.8 V).
# The window is deliberately wide: it is a branch check (regulating vs the
# current-limit latch state, which sits tens of volts away), not an accuracy
# check -- accuracy is sim/load-regulation/ and sim/line-regulation/'s claim.
VOUT_NOM_V = 1.8
VOUT_TOL_FRAC = 0.10

# AC sweep band. The low end must sit well below the output pole at the
# largest C_eff / lightest load (a few Hz); the high end well above the
# highest crossover seen (a few MHz) so a -180 deg crossing, if there is
# one, is inside the band rather than assumed away.
F_START = "0.01"
F_STOP = "1e9"
#
# --- AC_DEC: the sweep resolution, and why it is 400 (issue #58) -----------
#
# The resolution is part of the measurement, not a performance knob: a
# resonance narrow enough to fall between two grid points is not merely
# reported inaccurately, it can be invisible, and `resurgence_db` (issue #59,
# DR-0008's precondition check) inherits the blindness of the grid it is
# computed from. At 400 points per decade, the worst-case sampling error --
# a resonance peak landing exactly midway between two samples -- stays within
# 1 dB through approximately Q = 88, a tenth of DR-0001's 10 dB gain-margin
# bar; the pre-#58 `dec 50` default held that only out to Q ~ 11. This is a
# stated capability, not a proof of sufficiency: no finite grid resolves an
# arbitrarily sharp feature.
#
# The derivation, the sampling-error table, the Q = 80 self-test that
# exercises this bound, the phase-unwrap analysis, and the measured runtime
# comparison that rejects the two-pass coarse-then-refine alternative live in
# the "Sweep resolution" section of sim/loop-stability/README.md; update that
# section together with this constant.
AC_DEC = "400"


# ---------------------------------------------------------------------------
# one PVT point
# ---------------------------------------------------------------------------
@dataclass
class Row:
    corner_id: str
    corner: str
    temp_c: float
    vin_v: float
    iload_a: float
    ceff_f: float
    esr_ohm: float
    vout_v: float
    dcgain_db: float
    f0_hz: float | None
    phase_at_f0_deg: float | None
    f180_hz: float | None
    gain_at_f180_db: float | None
    f0_rising_hz: float | None
    resurgence_db: float | None = None

    @property
    def pm_deg(self) -> float | None:
        if self.phase_at_f0_deg is None:
            return None
        return 180.0 + self.phase_at_f0_deg

    @property
    def gm_db(self) -> float:
        """Gain margin. ``inf`` when the phase never reaches -180 deg in band.

        That is not a measurement failure: for a loop whose phase asymptotes
        to -180 deg from above, there is no frequency at which the loop
        inverts, so no finite gain multiplier drives it to T = -1. Reported
        as ``inf`` and treated as passing the >= 10 dB bar.
        """
        if self.gain_at_f180_db is None:
            return math.inf
        return -self.gain_at_f180_db

    @property
    def passes(self) -> bool:
        """The DR-0001 verdict, and only that.

        The DR-0008 resurgence bar is deliberately NOT folded in here: it is a
        different claim (whether a Bode margin is a legitimate reading at all)
        against a criterion that is not yet ratified, and folding it in would
        silently restate every historical PM/GM verdict. See ``resurges``.
        """
        pm = self.pm_deg
        return pm is not None and pm >= PM_MIN_DEG and self.gm_db >= GM_MIN_DB

    @property
    def resurges(self) -> bool:
        """Does |T| climb back above 0 dB above its first 0 dB crossing?

        ``None`` -- no first crossing in band, so no region above one -- is
        not a resurgence. Such a point has no crossover and therefore already
        fails the phase-margin bar on its own account; it is never a silent
        pass of anything.
        """
        return self.resurgence_db is not None and self.resurgence_db > RESURGENCE_MAX_DB

    @property
    def config_id(self) -> str:
        return f"{fmt_ma(self.iload_a)}_{fmt_uf(self.ceff_f)}_{fmt_esr(self.esr_ohm)}"


def fmt_ma(a: float) -> str:
    ma = a * 1e3
    return f"{ma:g}mA"


def fmt_uf(f: float) -> str:
    return f"{f * 1e6:g}uF"


def fmt_esr(r: float) -> str:
    return f"{r * 1e3:g}mohm"


def parse_opt_float(tok: str) -> float | None:
    tok = tok.strip()
    if not tok:
        return None
    try:
        return float(tok)
    except ValueError:
        return None


ROW_FIELDS = (
    "iload_a", "ceff_f", "esr_ohm", "vout_v", "dcgain_db", "f0_hz",
    "phase_at_f0_deg", "f180_hz", "gain_at_f180_db", "f0_rising_hz",
    "resurgence_db",
)


def nan_or(tok: str) -> float:
    """``parse_opt_float(tok)``, but an unparsable token becomes NaN. A
    legitimate 0.0 is kept (``parse_opt_float(tok) or nan`` would turn it
    into NaN)."""
    v = parse_opt_float(tok)
    return float("nan") if v is None else v


def parse_row_fields(line: str) -> dict[str, str]:
    """Parse one ``ROW k=v k=v ...`` line against this module's ``ROW_FIELDS``.

    The parsing/validation itself is ``harness.report.parse_row_fields()``,
    shared with ``sim/soft-start-loop-gain/testbench/sweep.py`` (see that
    shared function's docstring for why key=value rather than positional).
    This wrapper just binds it to the loop-margin field list -- the layout
    ``sim/loop-stability/``'s deck writes and ``sim/soft-start-loop-gain/``'s
    anchor cross-check re-parses.
    """
    return _harness_parse_row_fields(line, ROW_FIELDS)


def base_row_kwargs(f: dict[str, str]) -> dict[str, float | None]:
    """Row fields coerced from a parsed ``ROW`` line that every sweep shares."""
    return dict(
        ceff_f=float(f["ceff_f"]),
        esr_ohm=float(f["esr_ohm"]),
        vout_v=nan_or(f["vout_v"]),
        dcgain_db=nan_or(f["dcgain_db"]),
        f0_hz=parse_opt_float(f["f0_hz"]),
        phase_at_f0_deg=parse_opt_float(f["phase_at_f0_deg"]),
        f180_hz=parse_opt_float(f["f180_hz"]),
        gain_at_f180_db=parse_opt_float(f["gain_at_f180_db"]),
        f0_rising_hz=parse_opt_float(f["f0_rising_hz"]),
        resurgence_db=parse_opt_float(f["resurgence_db"]),
    )


def print_curve_log(deck_text: str, header: str, log: Path, deck: Path,
                    cwd: Path | None = None) -> Path:
    """Splice ``print tdb tph`` ahead of the ``ROW`` echo, run the single-config
    deck once and write ``header`` + the shared column note + output to ``log``.
    Shared by every sweep's ``run_curve()``."""
    deck_mod.require_substituted(deck_text, source=str(deck))
    deck.write_text(deck_text.replace('      echo "ROW', "      print tdb tph\n" + '      echo "ROW'))
    proc = subprocess.run(["ngspice", "-b", str(deck)], capture_output=True, text=True,
                          cwd=None if cwd is None else str(cwd))
    log.write_text(
        header
        + "* the two printed columns after the frequency are |T| in dB and "
        "unwrapped phase(T) in degrees\n"
        + proc.stdout + proc.stderr
    )
    return log


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------
def gm_str(row: Row) -> str:
    return "inf" if math.isinf(row.gm_db) else f"{row.gm_db:.2f}"


def pm_str(row: Row) -> str:
    pm = row.pm_deg
    return "n/a" if pm is None else f"{pm:.2f}"


def res_str(row: Row) -> str:
    r = row.resurgence_db
    return "n/a" if r is None else f"{r:+.2f}"


def worst_of(rows: list[Row]) -> Row:
    """The row with the smallest phase margin (GM as tiebreak)."""

    def key(r: Row):
        pm = r.pm_deg
        return (
            -1e9 if pm is None else pm,
            r.gm_db if not math.isinf(r.gm_db) else 1e9,
        )

    return min(rows, key=key)


def worst_resurgence_of(rows: list[Row]) -> Row:
    """The row with the largest gain resurgence above its first crossing."""
    return max(rows, key=lambda r: -math.inf if r.resurgence_db is None
               else r.resurgence_db)
