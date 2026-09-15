#!/usr/bin/env python3
"""Pin ngspice's duplicate-``.options``-key precedence with a real run.

Issue #214 / DR-0024 pin ``.options wnflag=1`` into every generated deck, and
``sim/harness/runner.compose_deck`` emits that card *before* any manifest
``options``. Whether "first" or "last" is the winning position is not a style
question -- it decides whether the pin is authoritative or decorative, and it
is a property of the simulator, not of anything this repo can assert from
reading its own source. So it gets a testbench, like every other claim here.

Measured answer (ngspice-46): for two ``.options`` cards naming the same key,
**the first card wins** and every later one is silently discarded -- no
warning is printed. The harness pin is emitted first for exactly that reason.

Unlike ``test_harness.py`` (which is deliberately ngspice-free and PDK-free),
this module shells out to a real ngspice. Both tests skip cleanly when
ngspice is absent, so the no-tooling CI lane stays green; the PVT lane, which
installs ngspice and the PDK, actually runs them.

Each run happens in a temporary working directory carrying its own
``.spiceinit``. ngspice reads ``./.spiceinit`` *instead of* ``~/.spiceinit``
when the former exists, so this shadows whatever the host happens to set --
including the ``set wnflag=1`` that DR-0024's E10 found on the reference host.
Without that shadow these tests would measure the host, not ngspice.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR))

from harness import pdk as pdk_mod  # noqa: E402
from harness.pdk import PdkNotFound  # noqa: E402
from harness.runner import MODEL_BINNING_KEY  # noqa: E402

NGSPICE = shutil.which("ngspice")
TIMEOUT_S = 120

# A local .spiceinit that deliberately says nothing about wnflag, so the only
# thing setting it is the deck under test.
NEUTRAL_SPICEINIT = (
    "* test fixture: shadows the host ~/.spiceinit so these tests measure\n"
    "* ngspice's own duplicate-.options precedence, not this host's config.\n"
    "* Deliberately does NOT set wnflag.\n"
    "set num_threads=1\n"
)


def _run_deck(deck: str) -> subprocess.CompletedProcess:
    """Run one deck in a throwaway cwd with a neutral ``.spiceinit``."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / ".spiceinit").write_text(NEUTRAL_SPICEINIT)
        (work / "deck.spice").write_text(deck)
        return subprocess.run(
            [NGSPICE, "-b", "deck.spice"],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
        )


def _find_pdk():
    try:
        return pdk_mod.find_pdk()
    except PdkNotFound:
        return None


def _host_presets_wnflag() -> bool:
    """True when something outside the deck already set ``wnflag``.

    A local ``.spiceinit`` shadows ``~/.spiceinit`` but *not* the install's
    ``spinit``, which some distro builds use to set variables. If ``wnflag``
    is already set when the deck is read, the first-setting-wins rule is
    already satisfied by that earlier setting and neither ``.options`` card
    can be observed -- the probe would be measuring the host, so skip rather
    than report a result that is not about ngspice's card ordering.

    (``set ngbehavior=hs``/``hsa``/``spe`` is *not* this case: it makes
    binning behave as if ``wnflag=1`` without setting the variable, so an
    explicit card in the deck is still the first setting of it.)
    """
    if NGSPICE is None:
        return False
    proc = _run_deck(
        "* host wnflag pre-set probe (deliberately no .options card)\n"
        "r1 a 0 1k\n"
        "v1 a 0 dc 1\n"
        ".op\n"
        ".control\n"
        "run\n"
        f'echo "PRESET=[${MODEL_BINNING_KEY}]"\n'
        ".endc\n"
        ".end\n"
    )
    return "PRESET=[]" not in (proc.stdout + proc.stderr)


HOST_PRESETS_WNFLAG = _host_presets_wnflag()
_SKIP_REASONS = (
    (NGSPICE is None, "ngspice not on PATH"),
    (HOST_PRESETS_WNFLAG, f"host presets {MODEL_BINNING_KEY!r} outside the deck"),
)


def _skip_if_unusable(cls):
    for condition, reason in _SKIP_REASONS:
        cls = unittest.skipIf(condition, reason)(cls)
    return cls


@_skip_if_unusable
class DuplicateOptionKeyPrecedenceTests(unittest.TestCase):
    """The mechanism: which of two same-key ``.options`` cards takes effect."""

    def _effective_wnflag(self, first: str, second: str) -> str:
        # NOTE: the first non-comment line of an ngspice deck is consumed as
        # the title, so the leading `* ...` line is load-bearing -- without it
        # `first` would be swallowed and the test would silently measure a
        # one-card deck. compose_deck emits a title line for the same reason.
        deck = (
            "* duplicate .options key precedence probe\n"
            f".options {MODEL_BINNING_KEY}={first}\n"
            f".options {MODEL_BINNING_KEY}={second}\n"
            "r1 a 0 1k\n"
            "v1 a 0 dc 1\n"
            ".op\n"
            ".control\n"
            "run\n"
            f'echo "EFFECTIVE=[${MODEL_BINNING_KEY}]"\n'
            ".endc\n"
            ".end\n"
        )
        proc = _run_deck(deck)
        out = proc.stdout + proc.stderr
        for line in out.splitlines():
            if line.startswith("EFFECTIVE=["):
                return line[len("EFFECTIVE=[") : -1]
        self.fail(f"ngspice printed no EFFECTIVE= line; output was:\n{out}")

    def test_first_card_wins_not_the_last(self):
        """1-then-0 leaves 1 in effect; 0-then-1 leaves 0. Earliest wins."""
        self.assertEqual("1", self._effective_wnflag("1", "0"))
        self.assertEqual("0", self._effective_wnflag("0", "1"))

    def test_a_single_card_is_honoured_either_way(self):
        """Control: the probe reads the card, it is not stuck on a constant."""
        deck_tmpl = (
            "* single .options card control\n"
            ".options {key}={value}\n"
            "r1 a 0 1k\n"
            "v1 a 0 dc 1\n"
            ".op\n"
            ".control\n"
            "run\n"
            'echo "EFFECTIVE=[${key}]"\n'
            ".endc\n"
            ".end\n"
        )
        for value in ("0", "1"):
            with self.subTest(value=value):
                proc = _run_deck(deck_tmpl.format(key=MODEL_BINNING_KEY, value=value))
                self.assertIn(f"EFFECTIVE=[{value}]", proc.stdout + proc.stderr)


@_skip_if_unusable
class DuplicateOptionKeyBinSelectionTests(unittest.TestCase):
    """The effect: same precedence, observed through real gf180mcu binning.

    The cp-variable readback above is the mechanism; this is the consequence
    that DR-0024 actually cares about. A ``W=2000u nf=40`` ``pfet_03v3`` is
    50 um per finger: it resolves to the declared bin ``pfet_03v3.12`` under
    ``wnflag=1`` and hard-errors under ``wnflag=0``, so the run's outcome
    reports which card won without needing to trust the readback.
    """

    MODEL_LOOKUP_FAILURE = "could not find a valid modelname"

    @classmethod
    def setUpClass(cls):
        cls.pdk = _find_pdk()
        if cls.pdk is None:
            raise unittest.SkipTest("gf180mcu PDK not found")

    def _run_pass_device(self, first: str, second: str) -> str:
        deck = (
            "* gf180mcu bin selection under duplicate .options cards\n"
            f'.include "{self.pdk.design_include}"\n'
            f'.lib "{self.pdk.model_lib}" typical\n'
            ".temp 25\n"
            f".options {MODEL_BINNING_KEY}={first}\n"
            f".options {MODEL_BINNING_KEY}={second}\n"
            "vdd vdd 0 dc 3.3\n"
            "vg g 0 dc 0\n"
            "mp vdd g vdd vdd pfet_03v3 W=2000u L=0.6u nf=40 m=1\n"
            ".op\n"
            ".control\n"
            "run\n"
            "print i(vdd)\n"
            ".endc\n"
            ".end\n"
        )
        proc = _run_deck(deck)
        return proc.stdout + proc.stderr

    def test_pin_first_survives_a_later_contradicting_card(self):
        out = self._run_pass_device("1", "0")
        self.assertNotIn(self.MODEL_LOOKUP_FAILURE, out)

    def test_a_later_card_cannot_rescue_a_wrong_first_card(self):
        out = self._run_pass_device("0", "1")
        self.assertIn(self.MODEL_LOOKUP_FAILURE, out)


if __name__ == "__main__":
    unittest.main()
