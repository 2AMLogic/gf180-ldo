"""Loading a standalone script by path, as one module instead of 21 copies.

Most of this repo's drivers and checkers are *scripts*, not importable
package members: they sit under hyphenated directories
(``sim/loop-stability/testbench/``, ``spec/decision-records/``) that are not
legal package names, and many share a bare file name -- as of this commit
``find . -name klt_run.py`` finds sixteen, ``summarize.py`` five and
``sweep.py`` two. So anything that wants to reuse one imports it by path,
under a name of the caller's choosing, rather than by ``sys.path``
insertion. That decision is deliberate and is kept (issue #451): a chosen
name keeps a bare ``plan`` or ``klt_run`` out of the importing process's
namespace, and lets two same-named scripts coexist in one process, which a
``sys.path`` insertion cannot do.

What was *not* deliberate is that the four-line ``importlib.util``
incantation implementing that decision had been written out 21 times, in 20
files, and that the 21 copies did not agree with each other: 11 registered
the module in ``sys.modules`` before executing it and 10 did not, with the
reason for registering recorded in exactly one of them
(``layout/drclvs.py``). This module is that incantation, once, with the
reason attached -- the same consolidation as #117's ``ngspice_version()``,
#203's ``parse_row_fields()``, #265's ``load()`` and #592's deck renderer,
at the import layer (issue #625).
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types


def load_script(name: str, path: str | os.PathLike) -> types.ModuleType:
    """Import the script at *path* as a module registered under *name*.

    *name* is chosen by the caller, not derived from the file name, and it is
    load-bearing in two ways. It is the ``sys.modules`` key, so two scripts
    that share a file name must be given distinct names to coexist -- e.g.
    ``sim/soft-start-loop-gain/testbench/sweep.py`` loads loop-stability's
    ``sweep.py`` as ``loop_stability_sweep`` and its own sibling
    ``klt_run.py`` as ``ss_loop_gain_klt_run`` (issue #451). It also becomes
    the loaded module's ``__name__``, which is what the next paragraph turns
    on.

    The module is registered in ``sys.modules`` *before* ``exec_module``, and
    that order is the whole reason this is a function rather than four inline
    lines. A script that combines ``from __future__ import annotations`` with
    ``@dataclass`` -- which is to say almost every Python file in this repo --
    fails at import if it is not registered yet::

        File ".../dataclasses.py", in _is_type
          ns = sys.modules.get(cls.__module__).__dict__
        AttributeError: 'NoneType' object has no attribute '__dict__'

    Deferred annotations make the field types strings, so ``@dataclass`` has
    to go back to the defining module's globals to decide whether one of them
    is the ``KW_ONLY`` sentinel, and :func:`dataclasses._is_type` does that
    lookup unguarded. Registering unconditionally means a script can grow its
    first dataclass without every caller having to rediscover this.
    ``sim/tests/test_loader.py`` holds that as a regression test, with the
    unregistered idiom kept beside it as the oracle.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {name!r} from {os.fspath(path)!r}")
    module = importlib.util.module_from_spec(spec)
    # Register before executing -- see the docstring: `@dataclass` resolves
    # its annotations through `sys.modules[cls.__module__]`.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
