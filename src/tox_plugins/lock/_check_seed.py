"""Prime the scratch file ``lock-deps-check`` compiles into.

Run by path, under the lock env's own interpreter, rather than
imported: that env installs the resolver and nothing else -- no
``tox``, and so no ``tox-lock`` either. Only the standard library is
available here, and only what the command line carries is known.
"""

from __future__ import annotations

import shutil
import sys
import typing as _t
from pathlib import Path


if _t.TYPE_CHECKING:
    from collections import abc as _c


def main(args: _c.Sequence[str]) -> int:
    """Copy a lock to the scratch path a fresh compile will overwrite.

    ``uv pip compile`` seeds its resolution from the output file when
    one is already there, leaving every pin that does not have to move
    exactly where it is. The check recompiles into a copy of the lock
    rather than into an empty file so that it reports *drift* -- the
    lock no longer matching the sources it claims to come from -- and
    not the mere existence of a newer release upstream, which is what
    ``-- --upgrade`` is for.

    :param args: The lock to copy and the scratch path to copy it to.
    :returns: The exit code to leave with.
    """
    lock_file, scratch_file = map(Path, args)
    scratch_file.parent.mkdir(parents=True, exist_ok=True)
    # NOTE: A lock that is not there yet must not leave the scratch
    # NOTE: file an earlier run wrote behind: the comparison would
    # NOTE: then be made against that, and a project that has never
    # NOTE: locked would be told its absent lock is current.
    scratch_file.unlink(missing_ok=True)
    if lock_file.is_file():
        shutil.copyfile(lock_file, scratch_file)

    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
