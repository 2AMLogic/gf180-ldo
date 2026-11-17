#!/usr/bin/env python3
"""Unit tests for layout/drclvs.py's LVS switch contract (issue #691).

    python3 -m unittest discover -s layout/tests -v

Two tiers:

* A PDK-free tier that pins the exact key set ``lvs_switches()`` emits, so
  a dead switch cannot quietly return.
* A PDK-backed tier that holds every emitted key -- the per-variant
  switches included -- to the ``$global``s the pinned ``gf180mcu.lvs``
  deck and its ``rule_decks/*.lvs`` actually dereference. The deck is a
  Ruby script: ``-rd key=value`` only sets a ``$key`` global, and a
  global nothing dereferences is silently unused -- the invocation looks
  valid while the deck never carries out the intent. That is the drift
  this tier guards: a key the deck never reads is a loud failure, not a
  silent no-op (the same failure mode the DRC driver's tests cover).

Skipped -- not failed -- on a host with no resolvable pinned PDK: the
layout test suite is otherwise PDK-free and may run without one.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

LAYOUT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAYOUT_DIR))
sys.path.insert(0, str(LAYOUT_DIR.parent / "sim"))

import drclvs  # noqa: E402
from harness.pdk import PdkNotFound, find_pdk  # noqa: E402


def fake_paths(tmp: Path) -> tuple[Path, Path, Path, Path]:
    """Placeholder paths: lvs_switches() is pure, nothing is read or written."""
    return tmp / "x.gds", tmp / "x.spice", tmp / "x.lvsdb", tmp / "x_extracted.cir"


def emitted_switch_keys() -> set[str]:
    """The key set lvs_switches() emits for the registered test cell."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        gds, netlist, lvsdb, extracted = fake_paths(root)
        spec = drclvs.CELLS["testcell"]
        pdk = drclvs.Pdk(path=root / "pdk", variant="gf180mcuD", source="test")
        switches = drclvs.lvs_switches(pdk, spec, gds, netlist, lvsdb, extracted)
    return set(switches)


class SwitchSetTests(unittest.TestCase):
    """The PDK-free tier: pin the emitted key set itself."""

    def test_the_switch_set_is_the_pinned_remaining_set(self):
        """Every key that survived the dead-switch purge, and no other.

        A dead key resurrected by a future edit fails here even on a
        PDK-less host; the PDK-backed tier below additionally checks the
        set against the deck itself, so a deck bump that retires a switch
        is caught where a PDK is installed.
        """
        self.assertEqual(
            emitted_switch_keys(),
            {
                "input",
                "schematic",
                "report",
                "target_netlist",
                "topcell",
                "run_mode",
                "verbose",
                "spice_net_names",
                "spice_comments",
                "net_only",
                "simplify",
                "implicit_connect",
                "top_lvl_pins",
                "combine",
                "purge",
                "purge_nets",
                "poly_res",
                "mim_cap",
                "metal_top",
                "mim_option",
                "metal_level",
            },
        )

    def test_the_dead_switches_of_issue_691_are_gone(self):
        """Named, so a regression names the issue it reintroduces.

        Measured against the pinned deck (gf180mcu.lvs + rule_decks/*.lvs,
        open_pdks f6eeac7): none of these four is ever dereferenced.
        """
        for dead in ("thr", "lvs_sub", "scale", "schematic_simplify"):
            self.assertNotIn(dead, emitted_switch_keys(), dead)


class DeckSubsetTests(unittest.TestCase):
    """The PDK-backed tier: keys the deck dereferences, or it does not run."""

    def setUp(self):
        try:
            self.pdk = find_pdk()
        except PdkNotFound as exc:
            self.skipTest(f"pinned PDK not resolvable: {exc}")
        deck_dir = self.pdk.klayout_dir / "lvs"
        deck_files = [deck_dir / "gf180mcu.lvs", *sorted((deck_dir / "rule_decks").glob("*.lvs"))]
        missing = [str(p) for p in deck_files if not p.is_file()]
        if missing:
            self.skipTest(f"pinned deck files missing: {missing}")
        text = "\n".join(p.read_text() for p in deck_files)
        # A -rd switch lands as a $global; the deck's switch vocabulary is
        # exactly the lowercase-underscore globals it dereferences.
        self.deck_globals = {m.group(1) for m in re.finditer(r"\$([a-z_]+)", text)}
        if not self.deck_globals:
            self.skipTest("deck tree dereferenced no $globals -- unexpected deck layout")

    def test_every_emitted_switch_key_is_a_deck_dereferenced_global(self):
        """keys(lvs_switches) subset of the deck's $globals -- the loud guard.

        Regression demonstration: temporarily re-adding ``lvs_sub`` to
        lvs_switches() makes this test fail with the stale key named
        (issue #691's acceptance criterion).
        """
        extra = sorted(emitted_switch_keys() - self.deck_globals)
        self.assertEqual(
            extra,
            [],
            "switches the pinned deck never dereferences (silently ignored "
            f"by klayout -r): {extra}",
        )


if __name__ == "__main__":
    unittest.main()
