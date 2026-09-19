#!/usr/bin/env python3
"""Re-measure DR-0025's three `wnflag` facts against an arbitrary ngspice.

DR-0025 ("gf180mcu model-bin selection binds on the per-finger width `W/NF`")
established three properties **of the simulator**, all on ngspice-46:

- **F1** -- `.options wnflag=1` makes `design/netlist/ldo_core.spice`'s
  `W=2000u nf=40` pass-device geometry resolve to the *declared* bin
  `pfet_03v3.12`, with the instance's `w` left undivided at 2000 um
  (DR-0025 E2).
- **F2** -- with `wnflag=0` (and with no card at all) the deck does not parse:
  `could not find a valid modelname`. There is no silent clamp to a
  neighbouring bin, and a genuinely out-of-range *per-finger* width fails the
  same way even under `wnflag=1` (DR-0025 E4/E5).
- **F3** -- for two `.options` cards naming the same key, the **first** card
  wins and later ones are silently discarded. That ordering is what makes the
  harness's pin authoritative rather than decorative (DR-0025's "A testbench
  manifest cannot override the pin" consequence; pinned for ngspice-46 by
  `sim/tests/test_ngspice_options_precedence.py`).

None of the three carries across an ngspice major version by argument -- they
are simulator behaviour, not netlist or PDK behaviour -- which is what issue
#221 scoped and did not perform, and what issue #254 performs here. This
module is the re-runnable form of that measurement: point it at any ngspice
build and it re-derives all three, PASS/FAIL, with every raw ngspice log kept.

    python3 sim/toolchain-portability/testbench/wnflag_facts.py \
        --ngspice ~/.local/ngspice-47/bin/ngspice \
        --log-dir sim/toolchain-portability/corners/<record-id>/ngspice-47

Every deck runs in a throwaway working directory carrying its own
`.spiceinit`, because ngspice reads `./.spiceinit` *instead of* `~/.spiceinit`
when the former exists. Without that shadow this script would measure the
host -- DR-0025 E10 found exactly that: the reference host carries an
out-of-band `set wnflag=1` in its home directory, so an unshadowed probe would
report F1 "passing" on a build that ignores the card entirely.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SIM_DIR))

from harness import pdk as pdk_mod  # noqa: E402
from harness.pdk import Pdk, PdkNotFound  # noqa: E402
from harness.runner import (  # noqa: E402
    MODEL_BINNING_KEY,
    ngspice_major_version,
    ngspice_version_at,
)

TIMEOUT_S = 180

MODEL_LOOKUP_FAILURE = "could not find a valid modelname"

#: The pass device of `design/netlist/ldo_core.spice` (`XMpass`), verbatim in
#: the two numbers bin selection turns on: 40 fingers of 50 um.
PASS_W = "2000u"
PASS_L = "0.28u"
PASS_NF = "40"
PASS_BIN = "pfet_03v3.12"

#: DR-0025 E4's genuinely out-of-range control: 150 um in a *single* finger is
#: above every declared bin's `wmax`, so no value of `wnflag` can rescue it.
OOR_W = "150u"
OOR_NF = "1"

#: ...and its in-range twin on the same deck, which must still resolve.
IN_RANGE_W = "90u"
IN_RANGE_NF = "1"

NEUTRAL_SPICEINIT = (
    "* wnflag_facts.py fixture: shadows the host ~/.spiceinit so these probes\n"
    "* measure ngspice's own behaviour, not this host's configuration.\n"
    f"* Deliberately does NOT set {MODEL_BINNING_KEY}.\n"
    "set num_threads=1\n"
)


@dataclass
class Probe:
    """One ngspice run: a deck, what it is for, and what came back."""

    name: str
    purpose: str
    deck: str
    output: str = ""
    returncode: int | None = None


@dataclass
class Fact:
    """One DR-0025 fact: its probes, and whether they reproduced."""

    key: str
    statement: str
    dr0025_evidence: str
    probes: list[Probe] = field(default_factory=list)
    checks: list[tuple[str, bool]] = field(default_factory=list)

    @property
    def holds(self) -> bool:
        return bool(self.checks) and all(ok for _, ok in self.checks)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_deck(ngspice: Path, deck: str) -> tuple[str, int]:
    """Run one deck in a throwaway cwd with a neutral ``.spiceinit``."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / ".spiceinit").write_text(NEUTRAL_SPICEINIT)
        (work / "deck.spice").write_text(deck)
        proc = subprocess.run(
            [str(ngspice), "-b", "deck.spice"],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
        )
    return proc.stdout + proc.stderr, proc.returncode


def _options_cards(*values: str) -> str:
    return "".join(f".options {MODEL_BINNING_KEY}={v}\n" for v in values)


def _pdk_preamble(pdk: Pdk) -> str:
    return (
        f'.include "{pdk.design_include}"\n'
        f'.lib "{pdk.model_lib}" typical\n'
        ".temp 25\n"
    )


def deck_show_pass_device(pdk: Pdk, *wnflag: str) -> str:
    """DR-0025 E2's deck: instantiate XMpass's geometry and `show` the bin."""
    return (
        "* DR-0025 E2: which bin does the pass-device geometry resolve to?\n"
        + _pdk_preamble(pdk)
        + _options_cards(*wnflag)
        + "vdd vdd 0 dc 3.3\n"
        "vg g 0 dc 0\n"
        f"xmp vdd g vdd vdd pfet_03v3 W={PASS_W} L={PASS_L} nf={PASS_NF} m=1\n"
        ".op\n"
        ".control\n"
        "run\n"
        "show m.xmp.m0 : model l w nf\n"
        f'echo "EFFECTIVE=[${MODEL_BINNING_KEY}]"\n'
        ".endc\n"
        ".end\n"
    )


def deck_out_of_range(pdk: Pdk, wnflag: str) -> str:
    """DR-0025 E4's deck: an out-of-range finger plus an in-range control."""
    return (
        "* DR-0025 E4: no clamp, no extrapolation -- bin or hard error\n"
        + _pdk_preamble(pdk)
        + _options_cards(wnflag)
        + "vdd vdd 0 dc 3.3\n"
        "vg g 0 dc 0\n"
        f"xmoor vdd g vdd vdd pfet_03v3 W={OOR_W} L={PASS_L} nf={OOR_NF} m=1\n"
        ".op\n"
        ".control\n"
        "run\n"
        ".endc\n"
        ".end\n"
    )


def deck_in_range_control(pdk: Pdk, wnflag: str) -> str:
    return (
        "* DR-0025 E4 control: an in-range finger on the same deck shape\n"
        + _pdk_preamble(pdk)
        + _options_cards(wnflag)
        + "vdd vdd 0 dc 3.3\n"
        "vg g 0 dc 0\n"
        f"xmin vdd g vdd vdd pfet_03v3 W={IN_RANGE_W} L={PASS_L} "
        f"nf={IN_RANGE_NF} m=1\n"
        ".op\n"
        ".control\n"
        "run\n"
        "show m.xmin.m0 : model\n"
        ".endc\n"
        ".end\n"
    )


def deck_readback(*wnflag: str) -> str:
    """PDK-free: read the cp variable back after N `.options` cards.

    NOTE: the leading `* ...` line is load-bearing -- ngspice consumes the
    first non-comment line of a deck as its title, so without it the first
    `.options` card would be swallowed and this would silently measure a
    one-card deck. `compose_deck` emits a title line for the same reason.
    """
    return (
        "* duplicate .options key precedence probe\n"
        + _options_cards(*wnflag)
        + "r1 a 0 1k\n"
        "v1 a 0 dc 1\n"
        ".op\n"
        ".control\n"
        "run\n"
        f'echo "EFFECTIVE=[${MODEL_BINNING_KEY}]"\n'
        ".endc\n"
        ".end\n"
    )


_EFFECTIVE_RE = re.compile(r"EFFECTIVE=\[([^\]]*)\]")


def effective_wnflag(output: str) -> str | None:
    match = _EFFECTIVE_RE.search(output)
    return match.group(1) if match else None


_SHOW_FIELD_RE = {
    "model": re.compile(r"^\s*model\s+(\S+)\s*$", re.MULTILINE),
    "l": re.compile(r"^\s*l\s+(\S+)\s*$", re.MULTILINE),
    "w": re.compile(r"^\s*w\s+(\S+)\s*$", re.MULTILINE),
    "nf": re.compile(r"^\s*nf\s+(\S+)\s*$", re.MULTILINE),
}


def show_field(output: str, field_name: str) -> str | None:
    match = _SHOW_FIELD_RE[field_name].search(output)
    return match.group(1) if match else None


def measure(ngspice: Path, pdk: Pdk) -> list[Fact]:
    """Run every probe and return the three facts with their verdicts."""

    def go(fact: Fact, name: str, purpose: str, deck: str) -> Probe:
        out, rc = run_deck(ngspice, deck)
        probe = Probe(name=name, purpose=purpose, deck=deck, output=out, returncode=rc)
        fact.probes.append(probe)
        return probe

    # ---- F1: wnflag=1 resolves the pass device to the declared bin --------
    f1 = Fact(
        key="F1",
        statement=(
            f"`.options {MODEL_BINNING_KEY}=1` resolves the `W={PASS_W} "
            f"nf={PASS_NF}` pass device to the declared bin `{PASS_BIN}`, "
            "with `w` left undivided"
        ),
        dr0025_evidence="E2 / E5",
    )
    p = go(f1, "f1-bin-resolve-wnflag1", "show the resolved bin at wnflag=1",
           deck_show_pass_device(pdk, "1"))
    f1.checks = [
        (f"deck parses (no {MODEL_LOOKUP_FAILURE!r})",
         MODEL_LOOKUP_FAILURE not in p.output),
        (f"resolved model is {PASS_BIN}", show_field(p.output, "model") == PASS_BIN),
        ("instance w is 0.002 (undivided 2000 um)",
         show_field(p.output, "w") == "0.002"),
        (f"instance nf is {PASS_NF}", show_field(p.output, "nf") == PASS_NF),
        (f"{MODEL_BINNING_KEY} read back as 1", effective_wnflag(p.output) == "1"),
    ]

    # ---- F2: wnflag=0 fails to parse; nothing ever clamps ----------------
    f2 = Fact(
        key="F2",
        statement=(
            f"`{MODEL_BINNING_KEY}=0` (and no card at all) fails to parse with "
            f"{MODEL_LOOKUP_FAILURE!r} -- it never silently clamps to a "
            "neighbouring bin"
        ),
        dr0025_evidence="E4 / E5",
    )
    p0 = go(f2, "f2-bin-resolve-wnflag0", "the same deck at wnflag=0",
            deck_show_pass_device(pdk, "0"))
    pnone = go(f2, "f2-bin-resolve-no-card", "the same deck with no options card",
               deck_show_pass_device(pdk))
    poor1 = go(f2, "f2-out-of-range-wnflag1",
               "an out-of-range per-finger width, at wnflag=1",
               deck_out_of_range(pdk, "1"))
    pctl = go(f2, "f2-in-range-control-wnflag1",
              "an in-range per-finger width on the same deck shape",
              deck_in_range_control(pdk, "1"))
    f2.checks = [
        (f"wnflag=0 -> {MODEL_LOOKUP_FAILURE!r}",
         MODEL_LOOKUP_FAILURE in p0.output),
        ("wnflag=0 resolves no bin at all", show_field(p0.output, "model") is None),
        (f"no card -> {MODEL_LOOKUP_FAILURE!r}",
         MODEL_LOOKUP_FAILURE in pnone.output),
        (f"out-of-range finger ({OOR_W}/nf={OOR_NF}) hard-errors even at "
         "wnflag=1", MODEL_LOOKUP_FAILURE in poor1.output),
        (f"in-range control ({IN_RANGE_W}/nf={IN_RANGE_NF}) still resolves "
         f"{PASS_BIN}", show_field(pctl.output, "model") == PASS_BIN),
    ]

    # ---- F3: duplicate .options keys resolve to the FIRST card -----------
    f3 = Fact(
        key="F3",
        statement=(
            "for two `.options` cards naming the same key, the **first** card "
            "wins and the later one is silently discarded"
        ),
        dr0025_evidence=(
            '"A testbench manifest cannot override the pin" consequence'
        ),
    )
    p10 = go(f3, "f3-readback-1-then-0", "cp readback, cards 1 then 0",
             deck_readback("1", "0"))
    p01 = go(f3, "f3-readback-0-then-1", "cp readback, cards 0 then 1",
             deck_readback("0", "1"))
    ps1 = go(f3, "f3-readback-single-1", "control: a single card, 1",
             deck_readback("1"))
    ps0 = go(f3, "f3-readback-single-0", "control: a single card, 0",
             deck_readback("0"))
    b10 = go(f3, "f3-bin-1-then-0", "bin selection, cards 1 then 0",
             deck_show_pass_device(pdk, "1", "0"))
    b01 = go(f3, "f3-bin-0-then-1", "bin selection, cards 0 then 1",
             deck_show_pass_device(pdk, "0", "1"))
    f3.checks = [
        ("1-then-0 leaves 1 in effect", effective_wnflag(p10.output) == "1"),
        ("0-then-1 leaves 0 in effect", effective_wnflag(p01.output) == "0"),
        ("control: a single `1` card reads back 1",
         effective_wnflag(ps1.output) == "1"),
        ("control: a single `0` card reads back 0",
         effective_wnflag(ps0.output) == "0"),
        (f"1-then-0 still resolves {PASS_BIN}",
         show_field(b10.output, "model") == PASS_BIN),
        (f"0-then-1 dies with {MODEL_LOOKUP_FAILURE!r}",
         MODEL_LOOKUP_FAILURE in b01.output),
        ("neither ordering warns about the discarded card",
         "warn" not in b10.output.lower() and "warn" not in p10.output.lower()),
    ]

    return [f1, f2, f3]


def write_logs(facts: list[Fact], log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    for fact in facts:
        for probe in fact.probes:
            path = log_dir / f"{probe.name}.log"
            path.write_text(
                f"* probe   : {probe.name}\n"
                f"* purpose : {probe.purpose}\n"
                f"* exit    : {probe.returncode}\n"
                "* ---- deck ----------------------------------------------\n"
                + "".join(f"* {ln}\n" for ln in probe.deck.splitlines())
                + "* ---- ngspice stdout+stderr -----------------------------\n"
                + probe.output
            )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--ngspice",
        default=None,
        help="ngspice executable to measure (default: the one on PATH)",
    )
    ap.add_argument(
        "--log-dir",
        default=None,
        help="directory to write one raw log per probe into (evidence)",
    )
    args = ap.parse_args()

    exe = args.ngspice or shutil.which("ngspice")
    if not exe:
        print("FATAL: no ngspice given and none on PATH", file=sys.stderr)
        return 2
    ngspice = Path(exe).expanduser().resolve()
    if not ngspice.exists():
        print(f"FATAL: no such ngspice: {ngspice}", file=sys.stderr)
        return 2

    try:
        pdk = pdk_mod.find_pdk()
    except PdkNotFound as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 2

    banner = ngspice_version_at(ngspice)
    major = ngspice_major_version(banner)
    print(f"ngspice       : {ngspice}")
    print(f"  banner      : {banner}")
    print(f"  major       : {major}")
    print(f"  sha256      : {sha256_of(ngspice)}")
    print(f"PDK           : {pdk.path} ({pdk.variant} @ {pdk.version})")
    print(f"  models      : {pdk.model_lib}")
    print()

    facts = measure(ngspice, pdk)

    if args.log_dir:
        write_logs(facts, Path(args.log_dir))

    ok = True
    for fact in facts:
        verdict = "HOLDS" if fact.holds else "DOES NOT HOLD"
        print(f"{fact.key}: {verdict} -- {fact.statement}")
        print(f"      (DR-0025 {fact.dr0025_evidence})")
        for label, passed in fact.checks:
            print(f"      [{'ok' if passed else 'FAIL'}] {label}")
        print()
        ok = ok and fact.holds

    print(f"OVERALL: {'all three DR-0025 facts reproduce' if ok else 'DIVERGENCE'}"
          f" on {major or banner}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
