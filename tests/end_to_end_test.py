"""Tests running the seeded envs against a real ``uv``."""

from __future__ import annotations

import typing as _t

import pytest


if _t.TYPE_CHECKING:
    from tox.pytest import ToxProject, ToxProjectCreator


# NOTE: A source declaring no dependencies at all is what keeps these
# NOTE: tests resolvable without a package index: `uv pip compile` has
# NOTE: nothing to look up, so the only thing here that reaches one is
# NOTE: `tox` installing `uv` itself into the env.
_ZERO_DEP_PYPROJECT = """\
[project]
name = "demo-pkg"
version = "1.0.0"
dependencies = []
"""

# NOTE: A pin that compiling the source above cannot possibly produce,
# NOTE: which is the point: it stands in for a lock left behind by an
# NOTE: earlier state of the requirements.
_STALE_PIN = 'attrs==24.2.0'

_LOCK_FILE_NAME = 'requirements.txt'


@pytest.fixture
def lock_project(
    tox_project: ToxProjectCreator,
    enable_pip_pypi_access: str | None,  # noqa: ARG001
) -> ToxProject:
    """Build a project the lock envs can be run in for real.

    ``tox``'s own pytest plugin points ``pip`` at a port nothing is
    listening on, so that a test reaching for a package index fails
    loudly instead of quietly depending on the network. These do reach
    for one -- ``uv`` has to come from somewhere -- so they opt back in
    through the fixture ``tox`` provides for exactly that.

    :param tox_project: Tox-provided project factory fixture.
    :param enable_pip_pypi_access: Tox-provided index-access opt-in.
    :returns: A project with a dependency-less source to compile.
    """
    return tox_project({
        'tox.ini': '[tox]\n',
        'pyproject.toml': _ZERO_DEP_PYPROJECT,
    })


@pytest.mark.network
def test_the_writer_compiles_a_lock_the_check_accepts(
    lock_project: ToxProject,
) -> None:
    """The two envs agree about a lock one of them just wrote.

    :param lock_project: A project holding a compilable source.
    """
    write_outcome = lock_project.run('run', '-e', 'lock-deps')
    write_outcome.assert_success()

    lock_file = lock_project.path / _LOCK_FILE_NAME
    assert 'tox run -e lock-deps' in lock_file.read_text(encoding='utf-8')

    lock_project.run('run', '-e', 'lock-deps-check').assert_success()


@pytest.mark.network
def test_the_check_reports_the_pins_that_moved(
    lock_project: ToxProject,
) -> None:
    """A stale lock fails the check, unchanged, with a diff.

    :param lock_project: A project holding a compilable source.
    """
    lock_file = lock_project.path / _LOCK_FILE_NAME
    lock_file.write_text(f'{_STALE_PIN}\n', encoding='utf-8')

    check_outcome = lock_project.run('run', '-e', 'lock-deps-check')

    check_outcome.assert_failed()
    check_report = f'{check_outcome.out}{check_outcome.err}'
    assert f'-{_STALE_PIN}' in check_report
    assert f'{_LOCK_FILE_NAME} is out of date' in check_report
    assert lock_file.read_text(encoding='utf-8') == f'{_STALE_PIN}\n'
