#!/usr/bin/env python3
"""Golden-record tests for the per-experiment rollup scripts (issue #381).
No PDK and no ngspice required.

    python3 -m unittest discover -s sim/tests -t sim/tests

The rollup scripts turn committed raw corner logs into the numbers quoted in
records and READMEs (sigmas, worst corners, pass/fail counts). Each one is
re-run here against ONE already-committed record's raw logs, read in place
under ``sim/<slug>/corners/<record-id>/``, and its headline numbers are
compared with the values that record's ``.md`` states. The expected values
are parsed out of the record text at test time, never retyped here, so a
regression in a script's parsing or arithmetic shows up as a disagreement
with committed evidence.

Tolerance, unless a test states otherwise: a record value printed as e.g.
``62.0253`` is taken to mean "the true value, rounded to that many decimal
places", so the computed value must agree to within HALF A UNIT IN THE LAST
PRINTED DIGIT (``printed_tol``; 0.00005 for ``62.0253``, 0.5 for ``1000``).

Each script also gets a malformed-input case (a truncated log, a missing
sample line, a ragged dump), synthesized in a temporary directory from the
committed fixture text, asserting the script raises rather than returning a
partial rollup.

Nothing here writes under ``sim/*/records`` or ``sim/*/corners``: fixtures
are read in place and every output goes to a ``TemporaryDirectory``.

The ``klt_run.py`` wrappers (soft-start, current-limit, quiescent-current)
submit work to ``klt sim`` and cannot run here; only their pure
post-processing (``derive`` / ``grade``) is tested, against the committed
``klt-report.json`` + ``summary.csv`` pairs they produced. ``klt`` itself is
never invoked.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import re
import sys
import tempfile
import types
import unittest
from decimal import Decimal
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR))


def _load(name: str, rel: str) -> types.ModuleType:
    """Import a script by path under a unique module name (several are all
    called ``summarize.py`` / ``klt_run.py``)."""
    spec = importlib.util.spec_from_file_location(name, SIM_DIR / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


mc = _load("mc_summarize", "mc-output-accuracy/summarize.py")
ss = _load("ss_summarize", "soft-start/testbench/summarize.py")
pa = _load("ss_peak_analyze", "soft-start/testbench/peak_analyze.py")
cl = _load("cl_summarize", "current-limit/testbench/summarize.py")
es = _load("es_summarize", "enable-shutdown/testbench/summarize.py")
ss_klt = _load("ss_klt_run", "soft-start/testbench/klt_run.py")
cl_klt = _load("cl_klt_run", "current-limit/testbench/klt_run.py")
iq_klt = _load("iq_klt_run", "quiescent-current/testbench/klt_run.py")
from harness import klt_batch as kb  # noqa: E402


# --- record-text helpers ------------------------------------------------------

_NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _clean(cell: str) -> str:
    """Markdown cell -> plain text: no bold, Unicode minus -> ASCII."""
    return cell.replace("**", "").replace("−", "-").strip()


def numbers(cell: str) -> list[str]:
    """The numeric tokens of a cell, as printed, ignoring `code` spans (corner
    ids carry digits that are not values)."""
    return _NUM_RE.findall(re.sub(r"`[^`]*`", " ", _clean(cell)))


def corner_ids(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def printed_tol(printed: str) -> float:
    """Half a unit in the last printed digit of ``printed``."""
    exp = Decimal(printed.lstrip("+")).as_tuple().exponent
    return 0.5 * 10.0 ** exp


def md_tables(text: str) -> list[tuple[list[str], list[list[str]]]]:
    """Every pipe table in ``text`` as (header cells, body rows of cells)."""
    tables = []
    lines = text.splitlines()
    i = 0
    while i < len(lines) - 1:
        head, sep = lines[i].strip(), lines[i + 1].strip()
        if head.startswith("|") and re.fullmatch(r"\|(\s*:?-+:?\s*\|)+", sep):
            split = lambda s: [c.strip() for c in s.strip().strip("|").split("|")]  # noqa: E731
            header = split(head)
            body = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                body.append(split(lines[i]))
                i += 1
            tables.append((header, body))
        else:
            i += 1
    return tables


def md_table(text: str, first_header: str) -> tuple[list[str], list[list[str]]]:
    found = [t for t in md_tables(text) if _clean(t[0][0]).startswith(first_header)]
    if len(found) != 1:
        raise AssertionError(f"expected one table headed {first_header!r}, found {len(found)}")
    return found[0]


def md_row(body: list[list[str]], label_prefix: str) -> list[str]:
    found = [r for r in body if _clean(r[0]).startswith(label_prefix)]
    if len(found) != 1:
        raise AssertionError(f"expected one row starting {label_prefix!r}, found {len(found)}")
    return found[0]


def record_grid(text: str) -> tuple[str, str, str]:
    """The ``process {..} x T {.. °C} x Vin {.. V}`` grid a record states, as
    the space-separated strings run.sh passes to summarize.py."""
    flat = _clean(re.sub(r"\s+", " ", text))
    m = re.search(r"process \{([^}]*)\} × T \{([^}]*?) °C\} × Vin \{([^}]*?) V\}", flat)
    if not m:
        raise AssertionError("record states no process x T x Vin grid")
    return tuple(" ".join(p.strip() for p in g.split(",")) for g in m.groups())


class GoldenCase(unittest.TestCase):
    def assertPrinted(self, computed: float, printed: str, what: str, rel: float = 0.0) -> None:
        """``computed`` agrees with the record's ``printed`` value to half a
        unit in its last digit, widened by ``rel`` (relative) where a test
        states why its inputs carry extra quantization."""
        tol = max(printed_tol(printed), rel * abs(float(printed))) * (1 + 1e-9)
        self.assertLessEqual(
            abs(computed - float(printed)), tol,
            f"{what}: rollup gives {computed!r}, record prints {printed} (tol {tol:g})")

    def assertSameCsv(self, regenerated: Path, committed: Path) -> None:
        self.assertEqual(regenerated.read_text().splitlines(), committed.read_text().splitlines(),
                         f"{regenerated.name} does not regenerate {committed}")


# --- sim/mc-output-accuracy/summarize.py --------------------------------------

MC_RECORD = "20260905-223503-3093ea1"
MC_DIR = SIM_DIR / "mc-output-accuracy"


class McOutputAccuracyGolden(GoldenCase):
    @classmethod
    def setUpClass(cls):
        cls.md = (MC_DIR / "records" / f"{MC_RECORD}.md").read_text()
        cls.r = mc.rollup(MC_DIR / "corners" / MC_RECORD)
        header, body = md_table(cls.md, "corner-id")
        cls.table = {corner_ids(row[0])[0]: dict(zip(header, row)) for row in body}

    def test_every_record_corner_is_rolled_up(self):
        self.assertEqual(set(self.r["per_corner"]), set(self.table))

    def test_per_corner_distribution_matches_record(self):
        # Tolerance: the record's columns are the harness's full-precision
        # measurements rounded to 6 significant figures, but summarize.py can
        # only see the MCSAMPLE lines, whose samples are THEMSELVES printed to
        # 6 significant figures. A statistic re-derived from those carries its
        # own ~1e-6 relative quantization on top of the record's rounding, so
        # the bound here is half a unit in the record's last digit or 1e-5
        # relative, whichever is larger (observed worst on this record: ~4e-6
        # relative, so the bound has ~2.5x headroom and is still far below
        # any change that would move a printed sigma).
        rel = 1e-5
        stats = dict(self.r["rows"])
        for corner, row in self.table.items():
            st = stats[corner]
            self.assertEqual(st["n"], int(row["n_samples"]), corner)
            self.assertPrinted(st["mean"], row["mean_mv"], f"{corner} mean_mv", rel)
            self.assertPrinted(st["sd"], row["sigma_mv"], f"{corner} sigma_mv", rel)
            self.assertPrinted(3 * st["sd"], row["sigma3_mv"], f"{corner} sigma3_mv", rel)
            self.assertPrinted(st["worst_abs"], row["worst_abs_mv"], f"{corner} worst_abs_mv", rel)

    def test_worst_corners_and_verdict_match_record(self):
        by_sigma = max(self.table, key=lambda c: float(self.table[c]["sigma_mv"]))
        by_mean = max(self.table, key=lambda c: abs(float(self.table[c]["mean_mv"])))
        self.assertEqual(self.r["worst_sigma"][0], by_sigma)
        self.assertEqual(self.r["worst_mean"][0], by_mean)
        self.assertPrinted(self.r["amp_3sigma"], self.table[by_sigma]["sigma3_mv"], "worst 3 sigma",
                           rel=1e-5)  # same MCSAMPLE quantization as above
        # The script's S3.1 target is the same limit the record graded sigma3_mv against.
        _, spread = md_table(self.md, "measurement")
        limit = float(re.search(r"max=([\d.]+)", md_row(spread, "`sigma3_mv`")[-1]).group(1))
        self.assertEqual(mc.TARGET_OUT_3SIGMA_MV, limit)
        overall = re.search(r"\*\*Overall: (PASS|FAIL)\*\*", self.md).group(1)
        self.assertEqual(self.r["verdict"], overall)


class McOutputAccuracyMalformed(unittest.TestCase):
    """A real corner log, damaged in a temp dir; rollup must refuse it."""

    def setUp(self):
        self.src = sorted((MC_DIR / "corners" / MC_RECORD).glob("*.log"))[:3]
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        for p in self.src:
            (self.dir / p.name).write_text(p.read_text())
        self.victim = self.dir / self.src[1].name
        self.lines = self.victim.read_text().splitlines()
        self.sample_idx = [i for i, ln in enumerate(self.lines) if "MCSAMPLE" in ln]

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, lines):
        self.victim.write_text("\n".join(lines) + "\n")

    def test_valid_copy_rolls_up(self):
        self.assertEqual(len(mc.rollup(self.dir)["per_corner"]), 3)

    def test_truncated_sample_line_fails(self):
        lines = list(self.lines)
        i = self.sample_idx[-1]
        lines[i] = " ".join(lines[i].split()[:10])  # cut mid-line
        self._write(lines)
        with self.assertRaisesRegex(mc.RollupError, "truncated"):
            mc.rollup(self.dir)

    def test_missing_sample_line_fails(self):
        lines = list(self.lines)
        del lines[self.sample_idx[len(self.sample_idx) // 2]]
        self._write(lines)
        with self.assertRaisesRegex(mc.RollupError, "missing"):
            mc.rollup(self.dir)

    def test_log_without_samples_fails(self):
        self._write([ln for ln in self.lines if "MCSAMPLE" not in ln])
        with self.assertRaisesRegex(mc.RollupError, "no MCSAMPLE lines"):
            mc.rollup(self.dir)


# --- sim/soft-start/testbench/summarize.py ------------------------------------

SS_RECORD = "20260918-190207-8a59d23"
SS_DIR = SIM_DIR / "soft-start"

# record clause row (prefix) -> (summarize.py FLAGS label substring, measured
# column the "worst point here" cell quotes, max/min, bound-at-1uF-only).
SS_CLAUSES = {
    "steady ramp rate": ("steady ramp rate above", "m_slope_vpms", max, False),
    "settling ≤ 1.8 ms": ("within the proposed", "m_t_startup_ms", max, False),
    "settled accuracy": ("settled output outside", None, None, False),
    "overshoot": ("startup overshoot", "m_vout_max_en", max, False),
    "inrush": ("inrush above", "m_icap_peak_ma", max, True),
    "clearance": ("peak supply current within", "m_isup_peak_ma", max, True),
    "peak dV_out/dt": ("peak dVout/dt above", "m_dvout_max", max, False),
    "monotonic": ("non-monotonic ramp", "m_dvout_min", min, False),
}


class SoftStartSummarizeGolden(GoldenCase):
    @classmethod
    def setUpClass(cls):
        cls.md = (SS_DIR / "records" / f"{SS_RECORD}.md").read_text()
        cls.rows = ss.rollup(SS_DIR / "corners" / SS_RECORD)
        cls.vals = {cid: v for cid, _, v in cls.rows}
        _, cls.body = md_table(cls.md, "clause (DR-0024 proposed bound)")

    def _flag(self, substring):
        found = [pred for label, pred in ss.FLAGS if substring in label]
        self.assertEqual(len(found), 1, substring)
        return found[0]

    def test_point_count(self):
        n = int(re.search(r"(\d+) points attempted", self.md).group(1))
        self.assertEqual(len(self.rows), n)

    def test_clause_pass_counts_and_worst_points(self):
        prev_corner = None
        for prefix, (flag, col, pick, bound_only) in SS_CLAUSES.items():
            with self.subTest(clause=prefix):
                row = md_row(self.body, prefix)
                passed, total = map(int, re.search(r"(\d+)/(\d+)", _clean(row[1])).groups())
                pred = self._flag(flag)
                pop = [v for v in self.vals.values() if v["m_cout_is_bound"] or not bound_only]
                self.assertEqual(len(pop), total)
                self.assertEqual(sum(1 for v in pop if not pred(v)), passed)

                worst, named = row[3], corner_ids(row[3])
                if col is None:
                    # This row names the failing points themselves.
                    flagged = {c for c, v in self.vals.items() if pred(v)}
                    self.assertEqual(flagged, set(named))
                    continue
                printed = numbers(worst)[0]
                extreme = pick(v[col] for v in pop)
                self.assertPrinted(extreme, printed, f"{prefix} worst")
                if "same point" in worst:
                    named = [prev_corner]
                for c in named:  # a named point attains the worst value (ties allowed)
                    self.assertPrinted(self.vals[c][col], printed, f"{prefix} at {c}")
                prev_corner = named[0] if named else prev_corner

    def test_csv_regenerates_committed_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "summary.csv"
            ss.write_csv(self.rows, out)
            self.assertSameCsv(out, SS_DIR / "corners" / SS_RECORD / "summary.csv")


class SoftStartSummarizeMalformed(unittest.TestCase):
    def test_truncated_log_fails(self):
        src = sorted((SS_DIR / "corners" / SS_RECORD).glob("*.log"))[0]
        lines = src.read_text().splitlines()
        last_meas = max(i for i, ln in enumerate(lines) if ln.startswith("m_"))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / src.name).write_text("\n".join(lines[:last_meas]) + "\n")
            with self.assertRaisesRegex(SystemExit, "missing measurements"):
                ss.rollup(Path(tmp))

    def test_empty_dir_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SystemExit, "no \\*.log"):
                ss.rollup(Path(tmp))


# --- sim/soft-start/testbench/peak_analyze.py ---------------------------------

PEAK_RECORD = "20261007-ss-351-peak-event"
PEAK_EVENT_DIR = SS_DIR / "corners" / PEAK_RECORD


def _write_dat(csv_path: Path, dat_path: Path) -> list[str]:
    """Rebuild a ``wrdata ... time <names>`` dump from a committed event CSV
    (``t t t v1 t v2 ...`` per row); returns the vector names."""
    with csv_path.open() as fh:
        rows = list(csv.reader(fh))
    names = rows[0][1:]
    out = [" ".join(["time"] * 3 + [f"time {n}" for n in names])]
    for r in rows[1:]:
        t = repr(float(r[0]) * 1e-6)
        out.append(" ".join([t, t] + [f"{t} {x}" for x in r[1:]]))
    dat_path.write_text("\n".join(out) + "\n")
    return names


class PeakAnalyzeGolden(GoldenCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dat = Path(self.tmp.name) / "dat"
        self.dat.mkdir()
        self.names = {d: _write_dat(PEAK_EVENT_DIR / f"event_{d}.csv", self.dat / f"{d}_x.dat")
                      for d in ("new", "baseline")}

    def tearDown(self):
        self.tmp.cleanup()

    def test_event_tables_regenerate(self):
        out = Path(self.tmp.name) / "out"
        extras = self.names["new"][len(pa.CORE):]
        self.assertEqual(self.names["new"][:len(pa.CORE)], pa.CORE)
        pa.main(["--dat-dir", str(self.dat), "--out", str(out), "--win-tag", "_x",
                 "--extra-names", ",".join(extras)])
        for dut in ("new", "baseline"):
            self.assertSameCsv(out / f"event_{dut}.csv", PEAK_EVENT_DIR / f"event_{dut}.csv")

    def test_peak_matches_record(self):
        # The committed event waveform is the 1 ns max-step run subsampled
        # every 20 ns, so its peak can only sit at or below the record's 1 ns
        # peak, and within the record's own 1 % convergence criterion of it;
        # the peak instant must agree to within one 20 ns sample.
        md = (SS_DIR / "records" / f"{PEAK_RECORD}.md").read_text()
        _, conv = md_table(md, "max step")
        row = md_row(conv, "1 ns")
        _, events = md_table(md, "t (us)")
        t_peak = next(r[0] for r in events if _clean(r[1]).startswith("peak"))
        for dut, cell in (("new", row[1]), ("baseline", row[2])):
            with self.subTest(dut=dut):
                t, v = pa.load(self.dat / f"{dut}_x.dat", pa.CORE)
                icap_ma, t_us, _ = pa.peak(t, v)
                ref = float(numbers(cell)[0])
                self.assertLessEqual(icap_ma, ref + printed_tol(numbers(cell)[0]))
                self.assertGreaterEqual(icap_ma, ref * (1 - 0.01))
                self.assertLessEqual(abs(t_us - float(t_peak)), 0.02)


class PeakAnalyzeMalformed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dat = Path(self.tmp.name) / "new_x.dat"
        _write_dat(PEAK_EVENT_DIR / "event_new.csv", self.dat)

    def tearDown(self):
        self.tmp.cleanup()

    def test_truncated_dump_fails(self):
        lines = self.dat.read_text().splitlines()
        lines[-1] = " ".join(lines[-1].split()[:-3])
        self.dat.write_text("\n".join(lines) + "\n")
        with self.assertRaisesRegex(ValueError, "truncated"):
            pa.load(self.dat, pa.CORE)
        with self.assertRaisesRegex(ValueError, "truncated"):
            pa.main(["--dat-dir", self.tmp.name, "--out", str(Path(self.tmp.name) / "o")])

    def test_header_only_dump_fails(self):
        self.dat.write_text(self.dat.read_text().splitlines()[0] + "\n")
        with self.assertRaisesRegex(ValueError, "no data rows"):
            pa.load(self.dat, pa.CORE)


# --- sim/current-limit/testbench/summarize.py ---------------------------------

CL_RECORD = "20260923-141325-33035d79"
CL_DIR = SIM_DIR / "current-limit"


class CurrentLimitGolden(GoldenCase):
    @classmethod
    def setUpClass(cls):
        cls.md = (CL_DIR / "records" / f"{CL_RECORD}.md").read_text()
        cls.grid = record_grid(cls.md)
        cls.rows = cl.rollup(CL_DIR / "corners" / CL_RECORD, *cls.grid)
        cls.vals = {r[0]: r[-1] for r in cls.rows}
        header, cls.body = md_table(cls.md, "Quantity")
        cls.col = next(i for i, h in enumerate(header) if h.startswith("this record"))

    def cell(self, prefix):
        return md_row(self.body, prefix)[self.col]

    def col_values(self, name):
        return [v[name] for v in self.vals.values()]

    def test_grid(self):
        self.assertEqual(len(self.rows), int(re.search(r"(\d+) points", self.md).group(1)))

    def test_min_max_rows(self):
        for prefix, col in (("onset at `Vout` = 1.764 V", "m_ilim_1764_ma"),
                            ("onset into a dead short", "m_ilim_0000_ma"),
                            ("flatness, 0 V vs 1.5 V", "m_flat_0_vs_1500_pct"),
                            ("no-load supply current", "m_ivin_0ma_ua")):
            with self.subTest(row=prefix):
                lo, hi = numbers(self.cell(prefix))
                self.assertPrinted(min(self.col_values(col)), lo, f"{prefix} min")
                self.assertPrinted(max(self.col_values(col)), hi, f"{prefix} max")

    def test_sense_margin_floor(self):
        (floor,) = numbers(self.cell("sense-domain margin"))
        self.assertPrinted(min(self.col_values("m_sense_margin_pct")), floor, "sense margin")

    def test_short_dissipation_worst_corner(self):
        cell = self.cell("dissipation into a short, worst corner")
        (printed,), (corner,) = numbers(cell), corner_ids(cell)
        worst = max(self.vals, key=lambda c: self.vals[c]["m_pshort_mw"])
        self.assertEqual(worst, corner)
        self.assertPrinted(self.vals[corner]["m_pshort_mw"], printed, "short dissipation")

    def test_window_counts_and_checks(self):
        lo, hi = map(float, re.search(r"ratified (\d+)–(\d+) mA window",
                                      md_row(self.body, "corners outside the ratified")[0]).groups())
        outside, total = map(int, numbers(self.cell("corners outside the ratified")))
        self.assertEqual(total, len(self.rows))
        self.assertEqual(sum(1 for x in self.col_values("m_ilim_1764_ma") if not lo <= x <= hi),
                         outside)
        ck = cl.checks(self.rows)
        self.assertEqual(_clean(self.cell("corners where the limit engages")), "none")
        self.assertEqual(ck["engages_at_or_below_50ma"], [])
        self.assertEqual(_clean(self.cell("corners outside the ±2 % window")), "none")
        self.assertEqual(ck["outside_window_at_50ma"], [])

    def test_csv_regenerates_committed_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "summary.csv"
            cl.write_csv(self.rows, out)
            self.assertSameCsv(out, CL_DIR / "corners" / CL_RECORD / "summary.csv")


class CurrentLimitMalformed(unittest.TestCase):
    def test_truncated_log_fails(self):
        src = CL_DIR / "corners" / CL_RECORD / "tt_27c_3.30v.log"
        lines = src.read_text().splitlines()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / src.name).write_text("\n".join(lines[: len(lines) // 2]) + "\n")
            with self.assertRaisesRegex(SystemExit, "missing measurements"):
                cl.rollup(Path(tmp), "tt", "27", "3.30")

    def test_missing_grid_point_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                cl.rollup(Path(tmp), "tt", "27", "3.30")


# --- sim/enable-shutdown/testbench/summarize.py -------------------------------

ES_RECORD = "20260905-232555-3093ea1"
ES_DIR = SIM_DIR / "enable-shutdown"

_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve".split())}


class EnableShutdownGolden(GoldenCase):
    @classmethod
    def setUpClass(cls):
        cls.md = (ES_DIR / "records" / f"{ES_RECORD}.md").read_text()
        cls.grid = record_grid(cls.md)
        cls.rows = es.rollup(ES_DIR / "corners" / ES_RECORD, *cls.grid)
        cls.vals = {r[0]: r[-1] for r in cls.rows}
        header, cls.body = md_table(cls.md, "Quantity")
        cls.col = next(i for i, h in enumerate(header) if _clean(h) == "this record")

    def test_grid(self):
        self.assertEqual(len(self.rows), int(re.search(r"(\d+) points", self.md).group(1)))

    def test_binding_corner_rows(self):
        corner = None
        for prefix, col in (("shutdown Iq @", "m_iq_off_ua"),
                            ("Vin→Vout leakage @", "m_ileak_vin_vout_ua"),
                            ("disabled `VOUT` @ same corner", "m_vout_off"),
                            ("enabled Iq @", "m_iq_en_ua")):
            with self.subTest(row=prefix):
                row = md_row(self.body, prefix)
                m = re.search(r"(\w+)/(-?\d+) °C/([\d.]+) V", _clean(row[0]))
                if m:
                    corner = "%s_%sc_%.2fv" % (m.group(1), m.group(2), float(m.group(3)))
                (printed,) = numbers(row[self.col])
                self.assertPrinted(self.vals[corner][col], printed, f"{prefix} at {corner}")

    def test_best_corner_and_startup(self):
        (best,) = numbers(md_row(self.body, "enabled Iq, best corner")[self.col])
        self.assertPrinted(min(v["m_iq_en_ua"] for v in self.vals.values()), best, "best Iq")
        passed, total = map(int, re.search(
            r"(\d+)/(\d+)", md_row(self.body, "startup reached")[self.col]).groups())
        startup = next(p for label, p in es.FLAGS if label.startswith("startup failed"))
        self.assertEqual(total, len(self.rows))
        self.assertEqual(sum(1 for v in self.vals.values() if not startup(v)), passed)
        flat = re.sub(r"\s+", " ", self.md)
        for which, pick in (("fastest", min), ("slowest", max)):
            m = re.search(r"([\d.]+) µs \(%s corner, `([^`]+)`\)" % which, flat)
            printed, corner = m.groups()
            self.assertEqual(pick(self.vals, key=lambda c: self.vals[c]["m_t_startup_us"]), corner)
            self.assertPrinted(self.vals[corner]["m_t_startup_us"], printed, f"{which} startup")

    def test_every_flag_reports_none(self):
        m = re.search(r"reports `none` for every one of the (\w+) checks", re.sub(r"\s+", " ", self.md))
        self.assertEqual(len(es.FLAGS), _WORDS[m.group(1)])
        for label, pred in es.FLAGS:
            self.assertEqual([c for c, v in self.vals.items() if pred(v)], [], label)

    def test_csv_regenerates_committed_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "summary.csv"
            es.write_csv(self.rows, out)
            self.assertSameCsv(out, ES_DIR / "corners" / ES_RECORD / "summary.csv")


class EnableShutdownMalformed(unittest.TestCase):
    def test_truncated_log_fails(self):
        src = ES_DIR / "corners" / ES_RECORD / "ff_125c_3.63v.log"
        lines = src.read_text().splitlines()
        last_meas = max(i for i, ln in enumerate(lines) if ln.startswith("m_"))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / src.name).write_text("\n".join(lines[:last_meas]) + "\n")
            with self.assertRaisesRegex(SystemExit, "missing measurements"):
                es.rollup(Path(tmp), "ff", "125", "3.63")


# --- klt_run.py wrappers: pure post-processing only ----------------------------

def _klt_values(report_path: Path, supply_key: str = "vin") -> dict[str, dict]:
    """The ``{corner_id: {measurement: value}}`` dict ``klt_ab.run_ab`` hands
    each wrapper, rebuilt from a committed report via ``klt_batch.collect``
    (whose only side effects land in a temp dir here)."""
    report = json.loads(report_path.read_text())
    with tempfile.TemporaryDirectory() as tmp:
        return kb.collect(report, types.SimpleNamespace(supply_key=supply_key), Path(tmp))


def _summary(path: Path) -> dict[tuple[str, str], dict]:
    with path.open() as fh:
        return {(r["dut"], r["corner"]): r for r in csv.DictReader(fh)}


class KltRunWrappers(GoldenCase):
    def test_soft_start_derive(self):
        base = SS_DIR / "corners" / "20261007-ss-351-rerun-1u"
        summary = _summary(base / "summary.csv")
        derived = {}
        for dut in ("new", "baseline"):
            for cid, v in _klt_values(base / "main" / dut / "klt-report.json").items():
                d = ss_klt.derive(v, 1)
                derived[dut] = d
                row = summary[(dut, cid)]
                for k, x in d.items():
                    self.assertAlmostEqual(x, float(row[k]), places=12, msg=f"{dut} {k}")
        # ... and the numbers the peak-event record says this rerun reproduced.
        md = re.sub(r"\s+", " ", (SS_DIR / "records" / f"{PEAK_RECORD}.md").read_text())
        m = re.search(r"reproduces the reported ([\d.]+) mA / ([\d.]+) mA / ([\d.]+) / ([\d.]+) V/ms", md)
        new_i, base_i, new_dv, base_dv = m.groups()
        self.assertPrinted(derived["new"]["icap_peak_ma"], new_i, "new icap")
        self.assertPrinted(derived["baseline"]["icap_peak_ma"], base_i, "baseline icap")
        self.assertPrinted(derived["new"]["dvout_max_vpms"], new_dv, "new dV/dt")
        self.assertPrinted(derived["baseline"]["dvout_max_vpms"], base_dv, "baseline dV/dt")

    def test_current_limit_grade(self):
        base = CL_DIR / "corners" / "20261007-ilim-320-tt27-probe"
        summary = _summary(base / "summary.csv")
        for dut in ("new", "baseline"):
            for cid, v in _klt_values(base / dut / "klt-report.json").items():
                vin = float(cid.rsplit("_", 1)[1].rstrip("v"))
                row = summary[(dut, cid)]
                for k, x in cl_klt.grade(v, vin).items():
                    if isinstance(x, bool):
                        self.assertEqual(str(x), row[k], f"{dut} {k}")
                    else:
                        self.assertAlmostEqual(x, float(row[k]), places=9, msg=f"{dut} {k}")

    def test_quiescent_current_grade(self):
        base = SIM_DIR / "quiescent-current" / "corners" / "20261007-iq-320-tt27-probe"
        summary = _summary(base / "summary.csv")
        for dut in ("new", "baseline"):
            for cid, v in _klt_values(base / dut / "klt-report.json", "vsup").items():
                self.assertEqual(str(iq_klt.grade(v)), summary[(dut, cid)]["pass"], f"{dut} {cid}")


if __name__ == "__main__":
    unittest.main()
