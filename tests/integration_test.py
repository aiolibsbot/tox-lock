"""Behavioral tests for the tox-lock plugin."""

from __future__ import annotations

import typing as _t

import pytest


if _t.TYPE_CHECKING:
    from pytest_subtests import SubTests

    from tox.pytest import ToxProjectCreator


def test_lock_env_registered(tox_project: ToxProjectCreator) -> None:
    """The plugin contributes the ``lock-deps`` env.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project({'tox.ini': '[tox]\n'})
    tox_invocation_result = project.run('list')
    tox_invocation_result.assert_success()
    assert 'lock-deps' in tox_invocation_result.out


@pytest.mark.parametrize(
    ('config_key', 'extra_args', 'expected_present'),
    (
        pytest.param(
            'commands',
            (),
            ('-m uv pip compile',),
            id='lock-deps-default',
        ),
        pytest.param(
            'commands',
            (),
            ('--generate-hashes', '--output-file requirements.txt'),
            id='lock-deps-hash-pinned-output',
        ),
        pytest.param(
            'commands',
            ('--', '--upgrade-package', 'tox'),
            ('pyproject.toml --upgrade-package tox',),
            id='lock-deps-with-posargs',
        ),
        pytest.param(
            'deps',
            (),
            ('uv',),
            id='lock-deps-deps',
        ),
    ),
)
def test_env_config(
    *,
    tox_project: ToxProjectCreator,
    config_key: str,
    extra_args: tuple[str, ...],
    expected_present: tuple[str, ...],
    subtests: SubTests,
) -> None:
    """The plugin's env produces the expected config values.

    :param tox_project: Tox-provided project factory fixture.
    :param config_key: The env config key to query.
    :param extra_args: Extra CLI arguments to append to the ``tox`` call,
        including the ``--`` separator and any positional arguments.
    :param expected_present: Substrings that must appear in the output.
    :param subtests: Pytest's subtest fixture for granular reporting.
    """
    project = tox_project({'tox.ini': '[tox]\n'})
    tox_invocation_result = project.run(
        'config',
        '-e',
        'lock-deps',
        '-k',
        config_key,
        *extra_args,
    )
    tox_invocation_result.assert_success()
    for substring in expected_present:
        with subtests.test(msg=substring):
            assert substring in tox_invocation_result.out


@pytest.mark.parametrize(
    ('config_files', 'extra_args', 'expected_present', 'expected_absent'),
    (
        pytest.param(
            {'tox.ini': '[tox]\n[testenv]\ncommands = pytest\n'},
            (),
            ('commands = python -bb -E -s -I -Werror -m uv',),
            ('commands = pytest',),
            id='ini-base-testenv-does-not-leak',
        ),
        pytest.param(
            {
                'tox.ini': (
                    '[tox]\n'
                    '[testenv:lock-deps]\n'
                    'deps = pip-tools\n'
                    'commands = pip-compile -o constraints.txt\n'
                    'pass_env = SOURCE_DATE_EPOCH\n'
                ),
            },
            (),
            (
                'deps = pip-tools',
                'commands = pip-compile -o constraints.txt',
                'SOURCE_DATE_EPOCH',
            ),
            ('-Werror',),
            id='ini-env-section-wins',
        ),
        pytest.param(
            {'tox.toml': '[env.lock-deps]\ndeps = ["pip-tools"]\n'},
            (),
            ('deps = pip-tools', 'commands = python -bb'),
            (),
            id='toml-env-table-wins-unset-keys-default',
        ),
        pytest.param(
            {'tox.ini': '[tox]\n[testenv:lock-deps]\ndescription = mine\n'},
            ('-x', 'testenv:lock-deps.deps=uv<99'),
            ('deps = uv<99',),
            (),
            id='ini-cli-override-wins',
        ),
        pytest.param(
            {'tox.ini': '[tox]\n'},
            ('-x', 'testenv:lock-deps.deps=uv<99'),
            ('deps = uv<99',),
            (),
            id='ini-cli-override-wins-without-a-section',
        ),
        pytest.param(
            {'tox.toml': '[env_run_base]\n'},
            ('-x', 'env.lock-deps.deps=uv<99'),
            ('deps = uv<99',),
            (),
            id='toml-cli-override-wins-without-a-table',
        ),
        pytest.param(
            {'tox.ini': '[tox]\n'},
            ('-x', 'testenv:lock-deps.deps={env:LOCK_PIN:uv<98}'),
            ('deps = uv<98',),
            (),
            id='cli-override-substitutions-are-expanded',
        ),
        pytest.param(
            {'tox.ini': '[testenv]\ncommands = pytest\n'},
            ('-x', 'testenv:lock-deps.deps={env:LOCK_PIN:uv<97}'),
            ('deps = uv<97',),
            (),
            id='core-less-config-still-expands-an-override',
        ),
        pytest.param(
            {'tox.ini': '[testenv]\ncommands = pytest\n'},
            ('-x', 'testenv:lock-deps.deps={[testenv]deps}'),
            ('deps = {[testenv]deps}',),
            (),
            id='core-less-config-leaves-a-section-reference-alone',
        ),
    ),
)
def test_user_config_precedence(
    *,
    tox_project: ToxProjectCreator,
    config_files: dict[str, str],
    extra_args: tuple[str, ...],
    expected_present: tuple[str, ...],
    expected_absent: tuple[str, ...],
    subtests: SubTests,
) -> None:
    """The user's own env section beats the plugin; ``[testenv]`` does not.

    :param tox_project: Tox-provided project factory fixture.
    :param config_files: The tox config files to create in the project.
    :param extra_args: Extra CLI arguments to append to the ``tox`` call.
    :param expected_present: Substrings that must appear in the output.
    :param expected_absent: Substrings that must not appear in the output.
    :param subtests: Pytest's subtest fixture for granular reporting.
    """
    project = tox_project(config_files)
    tox_invocation_result = project.run(
        'config',
        '-e',
        'lock-deps',
        '-k',
        'deps',
        'commands',
        'pass_env',
        *extra_args,
    )
    tox_invocation_result.assert_success()
    for substring in expected_present:
        with subtests.test(msg=f'present: {substring}'):
            assert substring in tox_invocation_result.out
    for substring in expected_absent:
        with subtests.test(msg=f'absent: {substring}'):
            assert substring not in tox_invocation_result.out


def test_posargs_reach_the_command_verbatim(
    tox_project: ToxProjectCreator,
) -> None:
    """An escaped comment character survives into the lock command.

    Seeding a :class:`~tox.config.types.Command` rather than a shell
    string keeps the arguments exactly as typed. A string would be
    re-split by ``StrConvert.to_command()``, which rewrites ``\\#`` into
    ``#`` -- silently pointing ``--output-file`` at a different file
    than the one the user named.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project({'tox.ini': '[tox]\n'})
    tox_invocation_result = project.run(
        'config',
        '-e',
        'lock-deps',
        '-k',
        'commands',
        '--',
        '--output-file',
        'out\\#1.txt',
    )
    tox_invocation_result.assert_success()
    assert "'out\\#1.txt'" in tox_invocation_result.out


@pytest.mark.parametrize(
    ('config_files', 'expected_present'),
    (
        pytest.param(
            {'tox.ini': '[tox]\n'},
            ('--output-file requirements.txt pyproject.toml',),
            id='ini-defaults',
        ),
        pytest.param(
            {
                'tox.ini': (
                    '[tox]\n'
                    'lock_file = requirements/base.txt\n'
                    'lock_input = requirements/base.in\n'
                ),
            },
            ('--output-file requirements/base.txt requirements/base.in',),
            id='ini-custom-paths',
        ),
        pytest.param(
            {
                'tox.toml': (
                    'lock_file = "constraints.txt"\n'
                    'lock_input = "setup.cfg"\n'
                ),
            },
            ('--output-file constraints.txt setup.cfg',),
            id='toml-custom-paths',
        ),
        pytest.param(
            {'tox.ini': '[testenv]\ncommands = pytest\n'},
            ('--output-file requirements.txt pyproject.toml',),
            id='core-less-config-falls-back-to-the-defaults',
        ),
    ),
)
def test_lock_paths_are_configurable(
    *,
    tox_project: ToxProjectCreator,
    config_files: dict[str, str],
    expected_present: tuple[str, ...],
    subtests: SubTests,
) -> None:
    """The core section names the files the lock command works on.

    :param tox_project: Tox-provided project factory fixture.
    :param config_files: The tox config files to create in the project.
    :param expected_present: Substrings that must appear in the output.
    :param subtests: Pytest's subtest fixture for granular reporting.
    """
    project = tox_project(config_files)
    tox_invocation_result = project.run(
        'config',
        '-e',
        'lock-deps',
        '-k',
        'commands',
        'description',
    )
    tox_invocation_result.assert_success()
    for substring in expected_present:
        with subtests.test(msg=substring):
            assert substring in tox_invocation_result.out


def test_lock_paths_expand_substitutions(
    tox_project: ToxProjectCreator,
) -> None:
    """A core-section path gets the config file's own substitutions.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project({
        'tox.ini': '[tox]\nlock_file = {env:LOCK_OUT:pinned.txt}\n',
    })
    tox_invocation_result = project.run(
        'config',
        '-e',
        'lock-deps',
        '-k',
        'commands',
    )
    tox_invocation_result.assert_success()
    assert '--output-file pinned.txt' in tox_invocation_result.out


def test_lock_paths_are_shown_in_the_env_description(
    tox_project: ToxProjectCreator,
) -> None:
    """``tox list`` tells the user which lock file the env writes.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project({
        'tox.ini': '[tox]\nlock_file = constraints.txt\n',
    })
    tox_invocation_result = project.run('list')
    tox_invocation_result.assert_success()
    assert 'constraints.txt' in tox_invocation_result.out
