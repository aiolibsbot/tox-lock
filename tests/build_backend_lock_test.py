"""Tests that this project's own build backend is pinned.

:mod:`build_requires_test` establishes the general claim against
``tox``: the packaging env installs ``[build-system] requires`` in an
invocation no lock reaches, refuses the ``deps`` key a lock is
ordinarily carried on, and takes ``constraints``. This checks that the
tree those tests live in acts on it -- a README telling every project
to pin its backend, in a repository resolving its own against the
index, is advice nobody here has run.

``uv pip compile pyproject.toml`` reads ``[project] dependencies``
and has no option asking it for the other table, so the sources of the
backend lock are a mirror of ``[build-system] requires`` rather than
the table itself. Keeping that mirror is ``lock_build_requires``'
job -- see :mod:`build_requires_source_test` -- and what is checked
here is that this tree asks for it, since a mirror kept by hand is how
a backend requirement added to the table goes on being resolved from
the index because the copy was not touched.
"""

from __future__ import annotations

from pathlib import Path


_ROOT = Path(__file__).parents[1]
_PYPROJECT = Path('pyproject.toml')
_TOX_INI = _ROOT / 'tox.ini'

_BACKEND_SOURCE = Path('requirements') / 'build-backend.in'
_BACKEND_LOCK = Path('requirements') / 'build-backend.txt'

def test_the_backend_mirror_is_written_by_the_plugin() -> None:
    """Check that the lock's sources are kept in step with the table.

    The whole cost of pinning the backend, and the only part of it that
    can rot: a requirement added to the table and not to the file the
    lock is compiled from leaves the build resolving it from the index,
    with nothing said. Declaring it here is what hands that to
    ``lock-deps-check``, which CI already runs.
    """
    assert (
        f'{_BACKEND_SOURCE.as_posix()} = {_PYPROJECT.as_posix()}'
        in _TOX_INI.read_text(encoding='utf-8')
    )


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
