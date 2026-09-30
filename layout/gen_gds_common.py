"""Shared helpers for the per-cell ``gen_gds.py`` KLayout generators.

``layout/passives/gen_gds.py`` and ``layout/pass_array/gen_gds.py`` each
carried byte-identical copies of ``_fail``, ``_rd``, ``_load_pdk_pcells``
and ``_label`` (issue #333). Consolidated here, following the same
``sys.path.insert`` + ``from X import Y`` idiom ``sim/harness/pvt_log.py``'s
callers and ``layout/drclvs.py`` (``sys.path.insert(0, str(LAYOUT_DIR))``)
already use for exactly this kind of module.

``layout/testcell/gen_gds.py`` predates ``_fail`` and uses
``os.environ.setdefault("GF_PDK_OPTION", "D")`` rather than an
unconditional assignment -- a deliberate difference, not drift -- so it is
not routed through this module.
"""

import os
import sys

import pya  # noqa: F401  (provided by the KLayout interpreter)


def _fail(message):
    """Abort with ``message`` actually visible.

    ``klayout -b -r`` swallows a bare ``SystemExit``'s message *and* still
    exits 0, so a generator that aborts this way looks to its caller like a
    silent success that happened to write no file. Printing to stderr first
    is what makes the reason survive; ``layout/drclvs.py``'s "layout build
    produced no <path>" check is the backstop for the exit status.
    """
    print(f"gen_gds.py: {message}", file=sys.stderr)
    raise SystemExit(f"gen_gds.py: {message}")


def _rd(name, default=None):
    """Read a -rd switch (KLayout injects them as globals).

    KLayout injects ``-rd`` switches into the *executed script's own*
    module globals -- i.e. the caller's, not this shared module's. Reading
    plain ``globals()`` here would always miss them once this function is
    imported rather than defined inline, so the lookup goes through the
    immediate caller's frame instead.
    """
    caller_globals = sys._getframe(1).f_globals
    value = caller_globals.get(name, default)
    if value is None:
        _fail(f"missing required switch -rd {name}=...")
    return value


def _load_pdk_pcells(pdk_path, pdk_option):
    """Register the PDK's KLayout-API PCell library and return its name."""
    macros = os.path.join(pdk_path, "libs.tech", "klayout", "tech", "pymacros")
    if not os.path.isdir(macros):
        _fail(f"no PCell library at {macros}")
    sys.path.insert(0, macros)
    # The gf180mcu PCells read this to pick the metal stack / MIM option. It is
    # not advisory: cap_mim's produce_impl() raises outright if MIM-B is asked
    # for under option A.
    os.environ["GF_PDK_OPTION"] = pdk_option
    from klayout_api_cells import gf180mcu_klayoutapi  # noqa: E402

    gf180mcu_klayoutapi()
    return "gf180mcu_klayoutapi"


def _label(cell, layout, layer, name, x_um, y_um):
    point = pya.Point(int(round(x_um / layout.dbu)), int(round(y_um / layout.dbu)))
    cell.shapes(layout.layer(*layer)).insert(pya.Text(name, pya.Trans(point)))
