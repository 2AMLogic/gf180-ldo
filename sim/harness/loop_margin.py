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
# Every record through `20260802-171044-db620a6` was taken at `dec 50` -- 4.7%
# frequency steps. That is fine for a smooth low-Q Bode response and blind to
# a sharp one, and the blindness is not graceful: a resonance narrow enough to
# fall between two grid points is not merely reported inaccurately, it can be
# invisible. `resurgence_db` (issue #59, DR-0008's precondition check) is
# computed off this same grid, so the detector inherits the blindness of the
# sample it is computed from.
#
# The bound is closed-form. Sampling a resonance of quality factor Q on a log
# grid of `dec` points per decade, the worst case is the peak landing exactly
# midway between two samples, an offset of d = 10^(1/(2*dec)) - 1 in relative
# frequency. A second-order resonance detuned by d reads
#
#     miss(Q, dec) = 20*log10( sqrt( (2*Q*d)^2 + 1 ) )   dB below its peak
#
# and the largest Q resolved to within a stated error E is therefore
#
#     Qmax(E, dec) = sqrt(10^(E/10) - 1) / (2*d)
#
#     dec | step   | miss at Q=80 | Qmax at 1 dB | Qmax at 0.1 dB
#     ----+--------+--------------+--------------+---------------
#      50 | 4.713% |    11.73 dB  |       10.9   |       3.3
#     100 | 2.329% |     6.47 dB  |       22.0   |       6.6
#     200 | 1.158% |     2.68 dB  |       44.1   |      13.2
#     400 | 0.577% |     0.84 dB  |       88.3   |      26.5
#     800 | 0.288% |     0.22 dB  |      176.7   |      53.0
#
# `dec 400` is chosen as the smallest power-of-two step from the old default
# that holds the worst-case miss under 1 dB -- a tenth of DR-0001's 10 dB
# gain-margin bar -- out to Q ~ 88. `dec 50` held that only out to Q ~ 11.
# This is a *stated capability*, not a proof of sufficiency: no finite grid
# resolves an arbitrarily sharp feature, and the honest claim is a bound where
# previously there was none.
#
# sim/loop-stability/testbench/selftest.py's third reference loop exercises
# the bound rather than asserting it: a Q = 80 resonance placed at the
# worst-case sampling offset for `dec 400` itself. At `dec 50` the extraction
# reports `resurgence_db = -0.79 dB` -- a clean, confident PASS on the DR-0008
# bar -- for a loop whose true continuous peak above its first 0 dB crossing
# is +3.90 dB. At `dec 400` the same extraction reports +3.11 dB, correctly
# failing it; the 0.79 dB residual is the analytic 0.84 dB worst-case miss
# above, measured. (Figures measured with the fixed-5%-offset scan start,
# issue #69; this resonance sits far enough above crossover that the offset's
# exact value barely changes them.)
#
# The same self-test answers the other question issue #58 raised -- whether
# `cph()` picks the wrong 360 deg branch across an under-sampled resonance.
# It does not, at either resolution (-269.97 deg against a -270 deg asymptote
# both times), and the reason is structural: a minimum-phase pole PAIR has
# 180 deg of total phase variation, so no sampling of one can produce the
# >180 deg sample-to-sample step `cph()` unwraps on. The resolution-sensitive
# quantity is the magnitude, not the branch.
#
# WHY NOT A TWO-PASS COARSE-THEN-REFINE SWEEP (the other option #58 offered):
#   1. It cannot fix this failure mode. A refine pass re-sweeps a window
#      centred on the coarse pass's own answer, so it inherits whatever the
#      coarse pass missed. On the self-test loop above there is nothing to
#      centre on: at `dec 50` the resonance does not appear at all.
#   2. It optimises a cost that is not being paid. The saving assumes runtime
#      scales with AC point count. Measured on this design at -j 1, one PVT
#      corner's 72-configuration sweep costs 72.1 s CPU at `dec 50` and
#      92.3 s at `dec 400` -- 1.28x for 8x the frequency points, because the
#      cost is dominated by the 72 DC operating-point solves and the model
#      setup around them, not by the AC points. See "Sweep resolution" in
#      sim/loop-stability/README.md.
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
