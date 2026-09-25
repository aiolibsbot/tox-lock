"""Tests pinning what a ``depends`` line does, and what it does not.

The README tells a project installing from a lock how to have its CI
notice a stale one, and every sentence of that advice is a claim about
``tox``'s ``depends`` rather than about anything this plugin owns.
Three of those claims are negative -- ``depends`` does not select, does
not resolve a label, and does not gate -- and a negative claim is
exactly the kind nothing else in this suite would notice going stale:
the check env not running is indistinguishable from a passing run.

So they are asserted here. If a later ``tox`` grows any of the three,
these go red and the advice gets rewritten rather than quietly
outliving the behaviour it was written against.
"""

from __future__ import annotations

import typing as _t


if _t.TYPE_CHECKING:
    from tox.pytest import ToxProjectCreator


# NOTE: Two envs that install nothing and run one marker each. Nothing
# NOTE: here reaches a package index -- `tox`'s own pytest plugin points
# NOTE: `pip` at a dead port -- and nothing here needs the resolver: the
# NOTE: subject is which envs tox runs and in what order, which it
# NOTE: settles before any of them starts.
_ORDERING_PROJECT = """\
[testenv]
skip_install = true

[testenv:first]
labels = a-label
commands = python -c "print('FIRST-RAN')"

[testenv:second]
depends = {depends}
commands = python -c "print('SECOND-RAN')"
"""

_FIRST_MARKER = 'FIRST-RAN'
_SECOND_MARKER = 'SECOND-RAN'


def test_depends_does_not_pull_the_check_env_into_the_run(
    tox_project: ToxProjectCreator,
) -> None:
    """An env depending on the check runs without it.

    The mistake the README names outright: a ``depends`` naming an env
    this invocation was not asked about is passed over in silence, so
    the guard never fires and the run it was meant to redden is green.
    The check env never starts here, which is why this needs no index.

    :param tox_project: Tox-provided project factory fixture.
    """
    config_files: dict[str, str] = {
        'tox.ini': (
            '[tox]\n'
            '[testenv:app]\n'
            'skip_install = true\n'
            'depends = lock-deps-check\n'
            'commands = python -c "print(\'APP-RAN\')"\n'
        ),
        'pyproject.toml': '[project]\nname = "demo"\nversion = "1.0.0"\n',
    }
    project = tox_project(config_files)

    tox_invocation_result = project.run('run', '-e', 'app')

    tox_invocation_result.assert_success()
    assert 'APP-RAN' in tox_invocation_result.out
    assert 'lock-deps-check' not in tox_invocation_result.out


def test_env_list_selects_the_check_env(
    tox_project: ToxProjectCreator,
) -> None:
    """The half of the advice that is this plugin's to keep working.

    The seeded envs are contributed as *additional* ones, so neither
    turns up in a default run a project did not ask for. A project that
    does ask -- by naming the check in ``env_list``, which is the line
    the README leads with -- has to get it, or the `depends` beneath it
    is ordering an env that is not there.

    :param tox_project: Tox-provided project factory fixture.
    """
    config_files: dict[str, str] = {
        'tox.ini': (
            '[tox]\n'
            'env_list =\n'
            '  lock-deps-check\n'
            '  tests\n'
            '[testenv:tests]\n'
            'skip_install = true\n'
            'depends = lock-deps-check\n'
        ),
        'pyproject.toml': '[project]\nname = "demo"\nversion = "1.0.0"\n',
    }
    project = tox_project(config_files)

    tox_invocation_result = project.run('list', '-d')

    tox_invocation_result.assert_success()
    default_envs, _, _ = tox_invocation_result.out.partition(
        'additional environments:',
    )
    assert 'lock-deps-check' in default_envs


def test_depends_passes_over_a_label(
    tox_project: ToxProjectCreator,
) -> None:
    """A label in ``depends`` orders nothing, and says nothing.

    ``depends`` resolves env names. The labels this plugin seeds -- and
    any a project writes -- are for selection, so naming one here is
    the same silent no-op as naming an env that is not in the run.

    :param tox_project: Tox-provided project factory fixture.
    """
    config_files: dict[str, str] = {
        'tox.ini': _ORDERING_PROJECT.format(depends='a-label'),
    }
    project = tox_project(config_files)

    tox_invocation_result = project.run('run', '-e', 'second,first')

    tox_invocation_result.assert_success()
    out = tox_invocation_result.out
    assert out.index(_SECOND_MARKER) < out.index(_FIRST_MARKER)


def test_depends_orders_the_envs_already_selected(
    tox_project: ToxProjectCreator,
) -> None:
    """Named by env, ``depends`` does reorder a selection.

    The half of the advice that works, and the reason the README keeps
    the line rather than dropping it: with both envs in the run, the
    check goes first and its diff reaches the CI log ahead of the
    failure it explains.

    :param tox_project: Tox-provided project factory fixture.
    """
    config_files: dict[str, str] = {
        'tox.ini': _ORDERING_PROJECT.format(depends='first'),
    }
    project = tox_project(config_files)

    tox_invocation_result = project.run('run', '-e', 'second,first')

    tox_invocation_result.assert_success()
    out = tox_invocation_result.out
    assert out.index(_FIRST_MARKER) < out.index(_SECOND_MARKER)


def test_depends_orders_but_does_not_gate(
    tox_project: ToxProjectCreator,
) -> None:
    """A failed dependency does not keep the dependent env from running.

    Which is the last of the three, and the one that decides how the
    guarantee has to be worded: the env installing from the lock runs
    against the stale one regardless. What goes red is the run.

    :param tox_project: Tox-provided project factory fixture.
    """
    config_files: dict[str, str] = {
        'tox.ini': (
            '[testenv]\n'
            'skip_install = true\n'
            '[testenv:first]\n'
            'commands = python -c "import sys; sys.exit(1)"\n'
            '[testenv:second]\n'
            'depends = first\n'
            f'commands = python -c "print(\'{_SECOND_MARKER}\')"\n'
        ),
    }
    project = tox_project(config_files)

    tox_invocation_result = project.run('run', '-e', 'second,first')

    tox_invocation_result.assert_failed()
    assert _SECOND_MARKER in tox_invocation_result.out
