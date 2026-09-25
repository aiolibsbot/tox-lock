"""Tests for compiling a lock out of a ``[build-system] requires`` table.

``uv pip compile pyproject.toml`` reads ``[project] dependencies``, and
has no option asking for the other table -- so a project pinning its
build backend, as :mod:`build_requires_test` shows it must, compiles
that lock out of a hand-written mirror of ``[build-system] requires``.

A mirror nothing compares is how a backend requirement added to one
file goes on being resolved from the index because the other was not
touched, silently: an unpinned install and a pinned one read alike.
These check that the plugin writes the mirror instead, and that
``lock-deps-check`` reports it when the committed one has fallen
behind the table it claims to copy.
"""

from __future__ import annotations

import typing as _t


if _t.TYPE_CHECKING:
    from tox.execute.request import ExecuteRequest
    from tox.pytest import ToxProject, ToxProjectCreator, ToxRunOutcome

import pytest


_MIRROR = 'requirements/build-backend.in'
_BACKEND_LOCK = 'requirements/build-backend.txt'

_FIRST_REQUIREMENT = 'setuptools >= 77'
_SECOND_REQUIREMENT = 'setuptools-scm >= 8'

_PYPROJECT = f"""\
[build-system]
requires = [
  "{_FIRST_REQUIREMENT}",
  "{_SECOND_REQUIREMENT}",
]
build-backend = "setuptools.build_meta"

[project]
name = "demo"
version = "1.0.0"
dependencies = []
"""

_TOX_INI = f"""\
[tox]
lock_files =
  {_BACKEND_LOCK} = {_MIRROR}
lock_build_requires =
  {_MIRROR} = pyproject.toml
"""

# NOTE: A mirror written the way a project that had been keeping it by
# NOTE: hand would have left it: one of the two requirements, and the
# NOTE: one whose absence an unpinned install says nothing about.
_STALE_MIRROR = f'{_FIRST_REQUIREMENT}\n'

# NOTE: Enough of a lock for the seeding step to copy and the
# NOTE: comparison to find current, so that what a run reports is the
# NOTE: mirror alone rather than a lock that was never compiled.
_LOCK = '# lock\n'

_UV_COMMAND = 'uv'


def _write(project: ToxProject, name: str, content: str) -> None:
    """Put a file in the project, directories and all.

    ``tox``'s own project factory writes what it is given into an
    existing tree, so a lock under ``requirements/`` has to be written
    after the project rather than handed to it.

    :param project: The project to write into.
    :param name: The path of the file, relative to the project root.
    :param content: What to write there.
    """
    target = project.path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding='utf-8')


def _stub_compiles(project: ToxProject) -> None:
    """Stand in for the resolver and leave everything else real.

    Only the ``uv pip compile`` invocations are stood in for. The
    plugin's own helper scripts -- the mirror writer under test, the
    scratch seeding and the comparison -- run for real, so what the
    assertions read is a file the plugin actually wrote.

    :param project: The project to stub the resolver in.
    """

    def stub(request: ExecuteRequest) -> int | None:
        """Report a resolver invocation as having succeeded.

        :param request: The command ``tox`` asked to run.
        :returns: Zero for a compile, else :data:`None` to run it.
        """
        return 0 if _UV_COMMAND in request.cmd else None

    project.patch_execute(stub)


def _run_with_compiles_stubbed(
    project: ToxProject,
    *args: str,
) -> ToxRunOutcome:
    """Stub the resolver and run an env.

    :param project: The project to run in.
    :param args: The arguments to run ``tox`` with.
    :returns: The result of the tox invocation.
    """
    _stub_compiles(project)
    return project.run(*args)


def test_the_mirror_is_written_from_the_table(
    tox_project: ToxProjectCreator,
) -> None:
    """``lock-deps`` writes the mirror before compiling from it.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project({'tox.ini': _TOX_INI, 'pyproject.toml': _PYPROJECT})

    tox_invocation_result = _run_with_compiles_stubbed(
        project,
        'run',
        '-e',
        'lock-deps',
    )

    tox_invocation_result.assert_success()
    written = (project.path / _MIRROR).read_text(encoding='utf-8')
    assert _FIRST_REQUIREMENT in written
    assert _SECOND_REQUIREMENT in written


def test_a_stale_mirror_is_reported_as_drift(
    tox_project: ToxProjectCreator,
) -> None:
    """``lock-deps-check`` fails on a mirror the table has outgrown.

    The hazard the hand-written copy carries: the lock is a faithful
    compile of its sources, and its sources no longer say what the
    project's build backend needs.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project({'tox.ini': _TOX_INI, 'pyproject.toml': _PYPROJECT})
    _write(project, _MIRROR, _STALE_MIRROR)
    _write(project, _BACKEND_LOCK, _LOCK)

    tox_invocation_result = _run_with_compiles_stubbed(
        project,
        'run',
        '-e',
        'lock-deps-check',
    )

    tox_invocation_result.assert_failed()
    assert _SECOND_REQUIREMENT in tox_invocation_result.out
    # NOTE: The committed mirror is left exactly as it was found: a
    # NOTE: check says whether the tree is current, it does not quietly
    # NOTE: make it so.
    assert (project.path / _MIRROR).read_text(
        encoding='utf-8',
    ) == _STALE_MIRROR


def test_a_current_mirror_is_not_reported(
    tox_project: ToxProjectCreator,
) -> None:
    """``lock-deps-check`` passes once the mirror says what the table does.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project({'tox.ini': _TOX_INI, 'pyproject.toml': _PYPROJECT})
    _stub_compiles(project)
    project.run('run', '-e', 'lock-deps').assert_success()
    _write(project, _BACKEND_LOCK, _LOCK)

    tox_invocation_result = project.run('run', '-e', 'lock-deps-check')

    tox_invocation_result.assert_success()


def test_a_mirror_no_lock_compiles_is_refused(
    tox_project: ToxProjectCreator,
) -> None:
    """A mirror feeding no lock is refused rather than written for nothing.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project({
        'tox.ini': (
            '[tox]\n'
            'lock_files =\n'
            '  requirements.txt = pyproject.toml\n'
            'lock_build_requires =\n'
            f'  {_MIRROR} = pyproject.toml\n'
        ),
        'pyproject.toml': _PYPROJECT,
    })

    tox_invocation_result = project.run('config', '-e', 'lock-deps')

    tox_invocation_result.assert_failed()
    assert _MIRROR.replace('/', '\\') in tox_invocation_result.out or (
        _MIRROR in tox_invocation_result.out
    )


def test_a_table_the_plugin_cannot_read_is_refused(
    tox_project: ToxProjectCreator,
) -> None:
    """A source naming no ``[build-system] requires`` is refused.

    Saying nothing would leave the mirror emptied and the lock it feeds
    compiled out of an empty file -- a backend pinned to nothing, which
    reads from CI exactly like a backend pinned correctly.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project({
        'tox.ini': _TOX_INI,
        'pyproject.toml': '[project]\nname = "demo"\nversion = "1.0.0"\n',
    })

    tox_invocation_result = project.run('config', '-e', 'lock-deps')

    tox_invocation_result.assert_failed()
    assert 'build-system' in tox_invocation_result.out


@pytest.mark.parametrize(
    ('selected', 'expected_written'),
    (
        pytest.param(_BACKEND_LOCK, True, id='the-lock-it-feeds'),
        pytest.param('requirements.txt', False, id='another-lock'),
    ),
)
def test_the_mirror_follows_the_lock_it_feeds(
    *,
    tox_project: ToxProjectCreator,
    selected: str,
    expected_written: bool,
) -> None:
    """``--lock-file`` narrows the mirrors written along with the locks.

    ``--lock-file`` says which locks an invocation is about, and a
    mirror is a source of one -- so narrowing to a lock it does not
    feed leaves it alone rather than rewriting it.

    :param tox_project: Tox-provided project factory fixture.
    :param selected: The lock to narrow the invocation to.
    :param expected_written: Whether the mirror should have been written.
    """
    project = tox_project({
        'tox.ini': (
            '[tox]\n'
            'lock_files =\n'
            f'  {_BACKEND_LOCK} = {_MIRROR}\n'
            '  requirements.txt = pyproject.toml\n'
            'lock_build_requires =\n'
            f'  {_MIRROR} = pyproject.toml\n'
        ),
        'pyproject.toml': _PYPROJECT,
    })

    tox_invocation_result = _run_with_compiles_stubbed(
        project,
        'run',
        '-e',
        'lock-deps',
        '--lock-file',
        selected,
    )

    tox_invocation_result.assert_success()
    assert (project.path / _MIRROR).is_file() is expected_written


def test_a_source_that_is_not_there_is_refused(
    tox_project: ToxProjectCreator,
) -> None:
    """A metadata file the plugin cannot read is refused.

    The same silence as an unreadable table, arriving one step
    earlier: a project locking its build backend out of a file that
    was moved would otherwise get a mirror emptied of everything the
    backend needs, and a lock over nothing.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project({
        'tox.ini': _TOX_INI.replace('pyproject.toml', 'moved.toml'),
        'pyproject.toml': _PYPROJECT,
    })

    tox_invocation_result = project.run('config', '-e', 'lock-deps')

    tox_invocation_result.assert_failed()
    assert 'moved.toml' in tox_invocation_result.out
