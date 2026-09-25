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

# NOTE: A requirement with an exact pin and no dependencies of its own:
# NOTE: compiling it produces one line for `uv` to annotate, and the
# NOTE: annotation is the whole subject of the test using it.
_ANNOTATED_PIN = 'attrs == 24.2.0'

# NOTE: A source `uv` cannot open, which fails the one compile that
# NOTE: names it and leaves every other lock's compile a decision for
# NOTE: the env rather than for tox's command runner.
_MISSING_SOURCE = 'nonexistent.in'


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
def test_annotations_moving_is_drift_the_check_reports(
    tox_project: ToxProjectCreator,
    enable_pip_pypi_access: str | None,  # noqa: ARG001
) -> None:
    """A lock whose pins hold still is not therefore current.

    ``uv`` annotates each pin with the requirement that pulled it in,
    so moving one between two sources of the same lock rewrites the
    file without moving a single version. That is the drift a
    comparison made on the pins alone cannot see: the check passes and
    ``tox run -e lock-deps`` changes the lock anyway.

    :param tox_project: Tox-provided project factory fixture.
    :param enable_pip_pypi_access: Tox-provided index-access opt-in.
    """
    project = tox_project({
        'tox.ini': (
            '[tox]\n'
            'lock_files =\n'
            '  requirements.txt = base.in, extra.in\n'
        ),
        'base.in': f'{_ANNOTATED_PIN}\n',
        'extra.in': '',
    })

    project.run('run', '-e', 'lock-deps').assert_success()

    lock_file = project.path / 'requirements.txt'
    written = lock_file.read_text(encoding='utf-8')
    assert '# via -r base.in' in written

    (project.path / 'base.in').write_text('', encoding='utf-8')
    (project.path / 'extra.in').write_text(
        f'{_ANNOTATED_PIN}\n',
        encoding='utf-8',
    )

    check_outcome = project.run('run', '-e', 'lock-deps-check')

    check_outcome.assert_failed()
    check_report = f'{check_outcome.out}{check_outcome.err}'
    assert '-    # via -r base.in' in check_report
    assert '+    # via -r extra.in' in check_report
    assert 'requirements.txt is out of date' in check_report
    # NOTE: The check is still the env that never writes, however much
    # NOTE: of the file it now compares.
    assert lock_file.read_text(encoding='utf-8') == written


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


@pytest.mark.network
def test_a_lock_that_will_not_compile_spares_the_others(
    tox_project: ToxProjectCreator,
    enable_pip_pypi_access: str | None,  # noqa: ARG001
    subtests: SubTests,
) -> None:
    """The writer produces every lock it can, and still fails.

    ``uv pip compile`` writes one output per invocation, so the writer
    runs one command per configured lock -- and ``tox`` abandons the
    rest of ``commands`` at the first non-zero exit. Stopping there
    would leave every lock after the broken one untouched, which is a
    scheduled refresh job reporting one failure and quietly renewing
    nothing.

    :param tox_project: Tox-provided project factory fixture.
    :param enable_pip_pypi_access: Tox-provided index-access opt-in.
    :param subtests: Pytest's subtest fixture for granular reporting.
    """
    project = tox_project({
        'tox.ini': (
            '[tox]\n'
            'lock_files =\n'
            f'  broken.txt = {_MISSING_SOURCE}\n'
            '  sound.txt = pyproject.toml\n'
        ),
        'pyproject.toml': _ZERO_DEP_PYPROJECT,
    })

    write_outcome = project.run('run', '-e', 'lock-deps')

    with subtests.test(msg='the run fails'):
        write_outcome.assert_failed()

    with subtests.test(msg='the unresolvable lock is named'):
        assert _MISSING_SOURCE in f'{write_outcome.out}{write_outcome.err}'

    with subtests.test(msg='the lock after it was written anyway'):
        assert (project.path / 'sound.txt').is_file()


@pytest.mark.network
def test_the_check_says_nothing_about_a_lock_it_could_not_recompile(
    tox_project: ToxProjectCreator,
    enable_pip_pypi_access: str | None,  # noqa: ARG001
    subtests: SubTests,
) -> None:
    """The check stops rather than vouch for an untouched scratch.

    Carrying on past a failed recompile is the one thing the check must
    not do: it compiles into a copy of the lock, so a compile that
    never ran leaves a scratch file identical to the lock it was copied
    from -- and the comparison would report the very lock it could not
    recompile as current. ``ignore_errors`` on the writer, which the
    check takes as its ``base``, must not reach it.

    :param tox_project: Tox-provided project factory fixture.
    :param enable_pip_pypi_access: Tox-provided index-access opt-in.
    :param subtests: Pytest's subtest fixture for granular reporting.
    """
    project = tox_project({
        'tox.ini': (
            '[tox]\n'
            'lock_files =\n'
            f'  broken.txt = {_MISSING_SOURCE}\n'
            '  sound.txt = pyproject.toml\n'
            '\n[testenv:lock-deps]\nignore_errors = true\n'
        ),
        'pyproject.toml': _ZERO_DEP_PYPROJECT,
    })
    for lock_name in ('broken.txt', 'sound.txt'):
        (project.path / lock_name).write_text(
            f'{_STALE_PIN}\n',
            encoding='utf-8',
        )

    check_outcome = project.run('run', '-e', 'lock-deps-check')
    check_report = f'{check_outcome.out}{check_outcome.err}'

    with subtests.test(msg='the check fails'):
        check_outcome.assert_failed()

    with subtests.test(msg='the unresolvable source is named'):
        assert _MISSING_SOURCE in check_report

    with subtests.test(msg='no verdict is reported for any lock'):
        assert 'out of date' not in check_report
