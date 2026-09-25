"""Tests running the seeded envs with ``tox-uv`` installed alongside.

The README's Scope section argues that this plugin is the
compile-and-verify half of a pair whose install half is ``tox``'s own
``pylock`` or ``tox-uv`` -- "meant to be used with them rather than
instead of them". Nothing in this repository ran that pairing: outside
this module ``tox-uv`` appears in the README and nowhere else, so the
claim was prose about a third-party release that moves on its own
schedule.

It cannot be checked from the rest of the suite either. ``tox-uv``
registers by assigning ``uv-venv-runner`` to ``tox``'s
``_default_run_env``, so merely installing it moves *every* env in the
process -- packaging envs included -- onto a different runner. A lock
holding it beside ``pytest`` would leave nothing at all exercising the
stock one. Hence a lock and an env of its own, and hence the skip
below: the module is collected by every env and runs in one.
"""

from __future__ import annotations

import typing as _t

import pytest


if _t.TYPE_CHECKING:
    from tox.pytest import ToxProject, ToxProjectCreator


pytest.importorskip(
    'tox_uv',
    reason='the interop env is the one that installs `tox-uv`',
)

# NOTE: Written out rather than read off `tox_uv._run.UvVenvRunner`,
# NOTE: which is where `tox-uv` spells it. Importing a private module
# NOTE: to learn the name would make a rename an `ImportError` during
# NOTE: collection; a literal makes it the assertion below failing,
# NOTE: which says which env got which runner.
_UV_RUNNER_ID = 'uv-venv-runner'


# NOTE: A source declaring no dependencies at all, so that the only
# NOTE: thing here reaching a package index is `tox` installing `uv`.
_ZERO_DEP_PYPROJECT = """\
[project]
name = "demo-pkg"
version = "1.0.0"
dependencies = []
"""

_LOCK_FILE_NAME = 'requirements.txt'

# NOTE: A pin compiling the source above cannot produce, standing in
# NOTE: for a lock left behind by an earlier state of the sources.
_STALE_PIN = 'attrs==24.2.0'

# NOTE: A `uv` setting with no bearing on what gets resolved, paired
# NOTE: below with the one variable that does. Both are `UV_*`; only
# NOTE: one of them survives the pairing, which is the whole point of
# NOTE: the test that reads them.
_INERT_UV_VAR = 'UV_NO_PROGRESS'

# NOTE: `uv pip compile` reads this as `--python`: which interpreter
# NOTE: the resolution is performed against.
_RESOLVING_UV_VAR = 'UV_PYTHON'


@pytest.fixture
def lock_project(
    tox_project: ToxProjectCreator,
    enable_pip_pypi_access: str | None,  # noqa: ARG001
) -> ToxProject:
    """Build a project the lock envs can be run in for real.

    :param tox_project: Tox-provided project factory fixture.
    :param enable_pip_pypi_access: Tox-provided index-access opt-in.
    :returns: A project with a dependency-less source to compile.
    """
    return tox_project({
        'tox.ini': '[tox]\n',
        'pyproject.toml': _ZERO_DEP_PYPROJECT,
    })


@pytest.mark.network
def test_the_pair_writes_and_accepts_a_lock(lock_project: ToxProject) -> None:
    """Both seeded envs do their job on ``tox-uv``'s runner.

    The envs this plugin seeds are seeded as configuration -- ``deps``,
    ``commands``, ``pass_env`` -- and never as a runner, so which one
    creates the virtualenv and installs into it is whatever the
    surrounding installation settles. This asserts that the answer
    ``tox-uv`` settles on still runs them.

    :param lock_project: A project holding a compilable source.
    """
    write_outcome = lock_project.run('run', '-e', 'lock-deps')
    write_outcome.assert_success()

    # NOTE: Without this the test passes just as well on the stock
    # NOTE: runner, which is the one every other module already covers.
    assert (
        lock_project.run('config', '-e', 'lock-deps', '-k', 'runner').out
    ).strip().endswith(_UV_RUNNER_ID)

    lock_file = lock_project.path / _LOCK_FILE_NAME
    assert 'tox run -e lock-deps' in lock_file.read_text(encoding='utf-8')

    lock_project.run('run', '-e', 'lock-deps-check').assert_success()


@pytest.mark.network
def test_the_check_still_refuses_a_stale_lock(
    lock_project: ToxProject,
) -> None:
    """The guard is a guard under the other runner too.

    An env that runs and reports success is the failure mode worth
    ruling out here: ``lock-deps-check`` earns its place in a CI matrix
    by going red, and a pairing that only broke the red half would look
    exactly like a green one.

    :param lock_project: A project holding a compilable source.
    """
    lock_file = lock_project.path / _LOCK_FILE_NAME
    lock_file.write_text(f'{_STALE_PIN}\n', encoding='utf-8')

    check_outcome = lock_project.run('run', '-e', 'lock-deps-check')

    check_outcome.assert_failed()
    assert f'{_LOCK_FILE_NAME} is out of date' in (
        f'{check_outcome.out}{check_outcome.err}'
    )


def test_uv_python_alone_does_not_survive_the_pairing(
    lock_project: ToxProject,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Record the one ``UV_*`` variable the pairing takes away.

    This plugin passes ``UV_*`` through as a ``pass_env`` *section*, so
    that a project configuring its resolver through the environment --
    which is nearly the only way ``uv`` is configured -- reaches the
    compile. ``tox-uv`` pops ``UV_PYTHON`` out of every env's
    environment, because it would otherwise outrank ``VIRTUAL_ENV``
    while ``tox-uv`` is creating that env. Correct for the creation,
    and invisible at the compile: the same ``tox run -e lock-deps``,
    in the same project, resolves against a different interpreter
    depending on whether an unrelated plugin is installed beside it.

    What keeps that from moving a lock in practice is the seeded
    ``--python-version``, which ``uv`` prefers to an interpreter it
    would otherwise have to go and find -- so a project declining that
    seed is a project this asymmetry can reach.

    :param lock_project: A project holding a compilable source.
    :param monkeypatch: Pytest's environment-manipulation fixture.
    """
    monkeypatch.setenv(_INERT_UV_VAR, '1')
    monkeypatch.setenv(_RESOLVING_UV_VAR, '3.10')

    outcome = lock_project.run(
        'run',
        '-e',
        'lock-deps',
        # NOTE: Nothing to install and nothing to resolve: this asks
        # NOTE: what the environment of the compile *is*, so running
        # NOTE: the compile would only put an index between the test
        # NOTE: and its answer.
        '-x',
        'testenv:lock-deps.deps=',
        '-x',
        'testenv:lock-deps.commands='
        'python -c "import os; print(sorted('
        "k for k in os.environ if k.startswith('UV_')"
        '))"',
    )

    outcome.assert_success()
    assert f"'{_INERT_UV_VAR}'" in outcome.out
    assert f"'{_RESOLVING_UV_VAR}'" not in outcome.out
