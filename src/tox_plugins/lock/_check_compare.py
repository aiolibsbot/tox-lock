"""Report how the committed locks differ from a fresh compile.

Run by path, under the lock env's own interpreter, rather than
imported -- see :mod:`tox_plugins.lock._check_seed` for why the
standard library is all there is here, and why the env name in the
closing message is spelled out rather than read from the plugin that
wrote this command line.
"""

from __future__ import annotations

import difflib
import sys
import typing as _t
from pathlib import Path


if _t.TYPE_CHECKING:
    from collections import abc as _c


def _pins(lock_file: Path) -> list[str]:
    """Read the lines of a lock that say what is pinned.

    Comment lines are left out because ``uv`` opens the file it writes
    with a header naming the command that produced it --
    ``--output-file`` included, which is the one argument the check is
    obliged to change. The ``# via ...`` annotations trailing each pin
    go the same way; they restate the dependency graph the pins
    themselves encode.

    :param lock_file: The lock to read.
    :returns: Every line of it that is not a comment.
    """
    return [
        line
        for line in lock_file.read_text(encoding='utf-8').splitlines()
        if not line.lstrip().startswith('#')
    ]


def _drift(scratch_file: Path, lock_file: Path) -> _c.Iterator[str]:
    """Spell out what recompiling a lock's sources would change in it.

    The diff is rendered over the same filtered lines the comparison is
    made on, rather than over the files, so that what a reader is shown
    is exactly what was compared -- a diff full of header and ``# via``
    noise would invite the conclusion that the check is tripping over
    comments it in fact ignores. CI is usually the only place this ever
    runs, and a log saying nothing but "out of date" sends whoever
    reads it to recompile locally just to find out what moved.

    :param scratch_file: The lock as recompiling its sources produces it.
    :param lock_file: The lock the project committed.
    :yields: The report lines, none at all if the lock is current.
    """
    if not lock_file.is_file():
        yield f'{lock_file} does not exist.'
        return

    locked, compiled = _pins(lock_file), _pins(scratch_file)
    if locked == compiled:
        return

    yield from difflib.unified_diff(
        locked,
        compiled,
        fromfile=f'{lock_file} (locked)',
        tofile=f'{lock_file} (recompiled)',
        lineterm='',
    )


def main(args: _c.Sequence[str]) -> int:
    """Compare every configured lock against a fresh compile of it.

    Every lock is compared by one invocation, rather than one per lock,
    so that a project with several of them learns about all the drift
    in a single CI run. ``commands`` stop at the first failure, so a
    comparison per lock would report the first stale one and say
    nothing about the rest -- turning one red build into as many as
    there are locks behind it.

    :param args: The scratch and committed lock paths, pair by pair.
    :returns: The exit code to leave with.
    """
    paths = [Path(arg) for arg in args]
    stale: list[Path] = []
    for scratch_file, lock_file in zip(paths[::2], paths[1::2], strict=True):
        report = list(_drift(scratch_file, lock_file))
        if not report:
            continue

        sys.stderr.writelines(f'{line}\n' for line in report)
        stale.append(lock_file)

    if not stale:
        return 0

    sys.stderr.write(
        f'{", ".join(map(str, stale))} '
        f'{"is" if len(stale) == 1 else "are"} out of date '
        f'-- run `tox run -e lock-deps`.\n',
    )
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
