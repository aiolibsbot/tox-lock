"""Tests running the seeded envs against a real ``uv``."""

from __future__ import annotations

import typing as _t

import pytest


if _t.TYPE_CHECKING:
    from pytest_subtests import SubTests

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


@pytest.mark.network
def test_a_pep_751_lock_is_written_and_accepted(
    tox_project: ToxProjectCreator,
    enable_pip_pypi_access: str | None,  # noqa: ARG001
    subtests: SubTests,
) -> None:
    """Naming the lock ``pylock.toml`` is all a PEP 751 lock takes.

    ``uv`` picks the output format off the file name, so the writer
    produces a PEP 751 lock and the check -- compiling into a scratch
    file that keeps that name -- produces one too and agrees with it.
    Neither this plugin nor the project it runs in says the word
    "format" anywhere.

    :param tox_project: Tox-provided project factory fixture.
    :param enable_pip_pypi_access: Tox-provided index-access opt-in.
    :param subtests: Pytest's subtest fixture for granular reporting.
    """
    project = tox_project({
        'tox.ini': '[tox]\nlock_files = pylock.toml = pyproject.toml\n',
        'pyproject.toml': _ZERO_DEP_PYPROJECT,
    })

    project.run('run', '-e', 'lock-deps').assert_success()

    lock_file = project.path / 'pylock.toml'
    lock_contents = lock_file.read_text(encoding='utf-8')
    with subtests.test(msg='the lock is a PEP 751 document'):
        assert 'lock-version = "1.0"' in lock_contents

    with subtests.test(msg='the check accepts what was just written'):
        project.run('run', '-e', 'lock-deps-check').assert_success()

    lock_file.write_text(
        lock_contents.replace('lock-version = "1.0"', 'lock-version = "1.1"'),
        encoding='utf-8',
    )
    check_outcome = project.run('run', '-e', 'lock-deps-check')
    with subtests.test(msg='an edited lock is reported as stale'):
        check_outcome.assert_failed()
        assert 'pylock.toml is out of date' in (
            f'{check_outcome.out}{check_outcome.err}'
        )


@pytest.mark.network
def test_several_locks_are_written_and_checked_together(
    tox_project: ToxProjectCreator,
    enable_pip_pypi_access: str | None,  # noqa: ARG001
    subtests: SubTests,
) -> None:
    """Both configured locks get written, then both get checked.

    The two share a file name on purpose: they compile into the same
    tox temp dir, so a scratch file named after the lock alone would
    have the second compile land on the first one's output.

    :param tox_project: Tox-provided project factory fixture.
    :param enable_pip_pypi_access: Tox-provided index-access opt-in.
    :param subtests: Pytest's subtest fixture for granular reporting.
    """
    project = tox_project({
        'tox.ini': (
            '[tox]\n'
            'lock_files =\n'
            '  requirements/base.txt = pyproject.toml\n'
            '  constraints/base.txt = extra.in\n'
        ),
        'pyproject.toml': _ZERO_DEP_PYPROJECT,
        'extra.in': '',
    })

    project.run('run', '-e', 'lock-deps').assert_success()

    lock_files = [
        project.path / 'requirements' / 'base.txt',
        project.path / 'constraints' / 'base.txt',
    ]
    for lock_file in lock_files:
        with subtests.test(msg=f'{lock_file.name} was written'):
            assert lock_file.is_file()

    with subtests.test(msg='the check accepts what was just written'):
        project.run('run', '-e', 'lock-deps-check').assert_success()

    for lock_file in lock_files:
        lock_file.write_text(f'{_STALE_PIN}\n', encoding='utf-8')

    check_outcome = project.run('run', '-e', 'lock-deps-check')
    check_report = f'{check_outcome.out}{check_outcome.err}'

    with subtests.test(msg='the check fails'):
        check_outcome.assert_failed()

    for lock_file in lock_files:
        with subtests.test(msg=f'{lock_file} is named as stale'):
            assert str(lock_file.relative_to(project.path)) in check_report
