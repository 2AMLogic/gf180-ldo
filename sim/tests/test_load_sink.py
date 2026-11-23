#!/usr/bin/env python3
"""Unit tests for sim/harness/load_sink.py (#637). No PDK, ngspice or klt required.

python3 -m unittest sim/tests/test_load_sink.py -v
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR))

from harness import load_sink  # noqa: E402
from harness import testbench  # noqa: E402

#: The cards the ten decks carried by hand before #637, verbatim.
UNGATED = "Bload VOUT NLOAD I = 'v(ilc) * 0.5 * (1 + tanh((v(vout) - 0.2) / 0.05))'"
GATED = (
    "Bload VOUT NLOAD I = 'v(ilc) * 0.5 * (1 + tanh((v(vout) - 0.2) / 0.05)) "
    "* 0.5 * (1 + tanh((v(vin) - 2.0) / 0.05))'"
)
FULL = "Bload_full VOUT_FULL NLOAD_FULL I = 'v(ilc) * 0.5 * (1 + tanh((v(vout_full) - 0.2) / 0.05))'"

#: slug -> token its deck must use (the only gated bench is the 50 mA PSRR one, #478).
BENCH_TOKENS = {
    "dropout-vs-load": "BLOAD",
    "line-regulation": "BLOAD",
    "load-regulation": "BLOAD",
    "load-transient": "BLOAD",
    "psrr-vs-freq": "BLOAD",
    "vref-transfer": "BLOAD",
    "vref-transfer-50ma": "BLOAD",
    "psrr-vs-freq-50ma": "BLOAD_VIN_GATED",
    "quiescent-current": "BLOAD_FULL",
}


class LoadSinkCard(unittest.TestCase):
    def test_cards_match_the_pre_637_hand_copies(self):
        self.assertEqual(load_sink.TOKENS["BLOAD"], UNGATED)
        self.assertEqual(load_sink.TOKENS["BLOAD_VIN_GATED"], GATED)
        self.assertEqual(load_sink.TOKENS["BLOAD_FULL"], FULL)

    def test_render_fills_token_and_passes_plain_text_through(self):
        self.assertEqual(load_sink.render("a\n@BLOAD@\nb\n"), f"a\n{UNGATED}\nb\n")
        self.assertEqual(
            load_sink.render("alter @vinj[acmag] = 1\n"), "alter @vinj[acmag] = 1\n"
        )

    def test_unknown_token_is_refused(self):
        with self.assertRaises(SystemExit):
            load_sink.render("@BLOAD_TYPO@\n")


class DecksUseTheOneDefinition(unittest.TestCase):
    def test_no_deck_hand_types_a_bload_card(self):
        decks = list(SIM_DIR.glob("*/testbench/*.spice"))
        self.assertTrue(decks)
        for deck in decks:
            self.assertFalse(re.search(r"(?m)^Bload", deck.read_text()), deck)

    def test_each_bench_renders_its_expected_card(self):
        for slug, token in BENCH_TOKENS.items():
            tb = testbench.load(SIM_DIR / slug / "testbench")
            lines = tb.fragment_text().splitlines()
            self.assertIn(load_sink.TOKENS[token], lines, slug)
            self.assertEqual(sum(1 for ln in lines if ln.startswith("Bload")), 1, slug)

    def test_quiescent_klt_body_renders_the_full_card(self):
        text = (SIM_DIR / "quiescent-current/testbench/klt_body.spice").read_text()
        self.assertIn(FULL, load_sink.render(text).splitlines())

    def test_only_the_50ma_psrr_bench_is_supply_gated(self):
        gated = [
            s
            for s in BENCH_TOKENS
            if any(
                ln.startswith("Bload") and "v(vin)" in ln
                for ln in testbench.load(SIM_DIR / s / "testbench")
                .fragment_text()
                .splitlines()
            )
        ]
        self.assertEqual(gated, ["psrr-vs-freq-50ma"])


if __name__ == "__main__":
    unittest.main()
