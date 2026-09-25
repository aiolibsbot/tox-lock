"""Tests that this project's own build backend is pinned.

:mod:`build_requires_test` establishes the general claim against
``tox``: the packaging env installs ``[build-system] requires`` in an
invocation no lock reaches, refuses the ``deps`` key a lock is
ordinarily carried on, and takes ``constraints``. This checks that the
tree those tests live in acts on it -- a README telling every project
to pin its backend, in a repository resolving its own against the
index, is advice nobody here has run.

The pinning costs one restatement. ``uv pip compile pyproject.toml``
reads ``[project] dependencies``; there is no option asking it for the
other table, so the sources of the backend lock are a copy of
``[build-system] requires`` rather than the table itself. A copy that
nothing compares is how a backend requirement added in one file goes
on being resolved from the index because the other was not touched --
silently, since an unpinned install and a pinned one read alike.
"""

from __future__ import annotations

import re
from pathlib import Path


_ROOT = Path(__file__).parents[1]
_PYPROJECT = _ROOT / 'pyproject.toml'
_TOX_INI = _ROOT / 'tox.ini'

_BACKEND_SOURCE = Path('requirements') / 'build-backend.in'
_BACKEND_LOCK = Path('requirements') / 'build-backend.txt'

# NOTE: A line scan rather than a parse, for the reason `_ci_matrix`
# NOTE: gives: `tomllib` arrived in 3.11 and the floor this project
# NOTE: declares is 3.10. `tox.ini` is not TOML anyway.
_REQUIRES_OPEN = 'requires = ['
_REQUIRES_CLOSE = ']'
_REQUIREMENT_RE = re.compile(r'^\s*"(?P<requirement>[^"]+)",$')

_COMMENT_PREFIX = '#'


def _build_system_requires() -> list[str]:
    """Read what the backend needs out of ``pyproject.toml``.

    :returns: The requirements ``[build-system] requires`` names.
    """
    lines = _PYPROJECT.read_text(encoding='utf-8').splitlines()
    opened = lines.index(_REQUIRES_OPEN)
    closed = lines.index(_REQUIRES_CLOSE, opened)
    matches = (_REQUIREMENT_RE.match(line) for line in lines[opened:closed])
    return [match['requirement'] for match in matches if match is not None]


def _lock_sources() -> list[str]:
    """Read the requirements the backend lock is compiled from.

    :returns: The non-comment entries of the lock's source file.
    """
    return [
        line
        for line in (_ROOT / _BACKEND_SOURCE).read_text(
            encoding='utf-8',
        ).splitlines()
        if line and not line.startswith(_COMMENT_PREFIX)
    ]


def test_the_backend_lock_is_compiled_from_what_the_build_needs() -> None:
    """Check the copy against the table it is a copy of.

    The whole cost of pinning the backend, and the only part of it that
    can rot: a requirement added to one file and not the other leaves
    the build resolving it from the index, with nothing said.
    """
    assert _lock_sources() == _build_system_requires()


def test_the_packaging_env_installs_from_the_backend_lock() -> None:
    """Check that the lock is compiled and then actually used.

    Two settings, and either alone is worth nothing: a lock in
    ``lock_files`` that no env names is a file kept current for its own
    sake, and a ``constraints`` entry naming a lock nothing compiles is
    a pin that drifts out from under the build it governs.
    """
    tox_ini = _TOX_INI.read_text(encoding='utf-8')

    assert f'{_BACKEND_LOCK.as_posix()} = {_BACKEND_SOURCE.as_posix()}' in (
        tox_ini
    )
    assert '\n[pkgenv]\n' in tox_ini
    assert _BACKEND_LOCK.name in tox_ini
