"""Behavioral tests for the tox-lock plugin."""

from __future__ import annotations

import sys
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
                    'lock_input = ["setup.cfg"]\n'
                ),
            },
            ('--output-file constraints.txt setup.cfg',),
            id='toml-custom-paths',
        ),
        pytest.param(
            {
                'tox.ini': (
                    '[tox]\n'
                    'lock_input =\n'
                    '  requirements/base.in\n'
                    '  requirements/test.in\n'
                ),
            },
            (
                '--output-file requirements.txt '
                'requirements/base.in requirements/test.in',
            ),
            id='ini-several-inputs',
        ),
        pytest.param(
            {
                'tox.toml': (
                    'lock_input = ["requirements/base.in", '
                    '"requirements/test.in"]\n'
                ),
            },
            (
                '--output-file requirements.txt '
                'requirements/base.in requirements/test.in',
            ),
            id='toml-several-inputs',
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
    subtests: SubTests,
) -> None:
    """``tox list`` names the files the env reads and writes.

    :param tox_project: Tox-provided project factory fixture.
    :param subtests: Pytest's subtest fixture for granular reporting.
    """
    project = tox_project({
        'tox.ini': (
            '[tox]\n'
            'lock_file = constraints.txt\n'
            'lock_input =\n'
            '  base.in\n'
            '  test.in\n'
        ),
    })
    tox_invocation_result = project.run('list')
    tox_invocation_result.assert_success()
    for substring in ('constraints.txt', 'base.in, test.in'):
        with subtests.test(msg=substring):
            assert substring in tox_invocation_result.out


@pytest.mark.parametrize(
    ('config_files', 'expected_present', 'expected_absent'),
    (
        pytest.param(
            {'tox.ini': '[tox]\n'},
            ('compile --generate-hashes --output-file',),
            (),
            id='defaults-to-hash-pinning',
        ),
        pytest.param(
            {'tox.ini': '[tox]\nlock_options =\n'},
            ('compile --output-file',),
            ('--generate-hashes',),
            id='ini-empty-opts-out-of-hashes',
        ),
        pytest.param(
            {'tox.toml': 'lock_options = []\n'},
            ('compile --output-file',),
            ('--generate-hashes',),
            id='toml-empty-opts-out-of-hashes',
        ),
        pytest.param(
            {
                'tox.ini': (
                    '[tox]\n'
                    'lock_options =\n'
                    '  --generate-hashes\n'
                    '  --universal\n'
                ),
            },
            ('compile --generate-hashes --universal --output-file',),
            (),
            id='ini-several-options',
        ),
        pytest.param(
            {
                'tox.toml': (
                    'lock_options = ["--python-version 3.10", "--no-header"]\n'
                ),
            },
            ('compile --python-version 3.10 --no-header --output-file',),
            (),
            id='toml-an-option-and-its-value-are-split-apart',
        ),
        pytest.param(
            {'tox.ini': '[tox]\nlock_options = {env:LOCK_OPTS:--no-annotate}\n'},
            ('compile --no-annotate --output-file',),
            ('--generate-hashes',),
            id='substitutions-are-expanded',
        ),
        pytest.param(
            {'tox.ini': '[testenv]\ncommands = pytest\n'},
            ('compile --generate-hashes --output-file',),
            (),
            id='core-less-config-falls-back-to-the-default',
        ),
    ),
)
def test_lock_options_are_configurable(
    *,
    tox_project: ToxProjectCreator,
    config_files: dict[str, str],
    expected_present: tuple[str, ...],
    expected_absent: tuple[str, ...],
    subtests: SubTests,
) -> None:
    """The core section names the options the lock is compiled with.

    :param tox_project: Tox-provided project factory fixture.
    :param config_files: The tox config files to create in the project.
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
        'commands',
    )
    tox_invocation_result.assert_success()
    for substring in expected_present:
        with subtests.test(msg=f'present: {substring}'):
            assert substring in tox_invocation_result.out
    for substring in expected_absent:
        with subtests.test(msg=f'absent: {substring}'):
            assert substring not in tox_invocation_result.out


def test_lock_options_are_shown_in_the_env_description(
    tox_project: ToxProjectCreator,
) -> None:
    """``tox list`` tells the user how the lock will be compiled.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project({
        'tox.ini': '[tox]\nlock_options = --universal\n',
    })
    tox_invocation_result = project.run('list')
    tox_invocation_result.assert_success()
    assert 'uv pip compile --universal' in tox_invocation_result.out


def test_lock_options_reach_the_command_verbatim(
    tox_project: ToxProjectCreator,
) -> None:
    """A quoted option value keeps the spaces it was quoted for.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project({
        'tox.ini': (
            '[tox]\n'
            'lock_options = --custom-compile-command "make lock"\n'
        ),
    })
    tox_invocation_result = project.run(
        'config',
        '-e',
        'lock-deps',
        '-k',
        'commands',
    )
    tox_invocation_result.assert_success()
    assert "--custom-compile-command 'make lock'" in tox_invocation_result.out


def test_check_env_registered(tox_project: ToxProjectCreator) -> None:
    """The plugin contributes the ``lock-deps-check`` env.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project({'tox.ini': '[tox]\n'})
    tox_invocation_result = project.run('list')
    tox_invocation_result.assert_success()
    assert 'lock-deps-check' in tox_invocation_result.out


@pytest.mark.parametrize(
    ('config_files', 'config_keys', 'expected_present', 'expected_absent'),
    (
        pytest.param(
            {'tox.ini': '[tox]\n'},
            ('commands',),
            (
                'lock-deps-check',
                'requirements.txt pyproject.toml',
                '--generate-hashes',
            ),
            ('--output-file requirements.txt',),
            id='compiles-into-a-scratch-file-not-the-lock',
        ),
        pytest.param(
            {'tox.ini': '[tox]\nlock_file = requirements/base.txt\n'},
            ('commands', 'commands_pre'),
            ('requirements/base.txt',),
            ('--output-file requirements/base.txt',),
            id='scratch-file-follows-a-custom-lock-name',
        ),
        pytest.param(
            {
                'tox.ini': (
                    '[tox]\nlock_options =\nlock_input = requirements.in\n'
                ),
            },
            ('commands',),
            ('compile --output-file', 'requirements.in'),
            ('--generate-hashes',),
            id='honours-the-core-lock-settings',
        ),
        pytest.param(
            {'tox.ini': '[tox]\n'},
            ('deps', 'package'),
            ('deps = uv', 'package = skip'),
            (),
            id='runs-uv-without-building-the-project',
        ),
    ),
)
def test_check_env_config(
    *,
    tox_project: ToxProjectCreator,
    config_files: dict[str, str],
    config_keys: tuple[str, ...],
    expected_present: tuple[str, ...],
    expected_absent: tuple[str, ...],
    subtests: SubTests,
) -> None:
    """The check env mirrors the lock env but writes somewhere else.

    :param tox_project: Tox-provided project factory fixture.
    :param config_files: The tox config files to create in the project.
    :param config_keys: The env config keys to query.
    :param expected_present: Substrings that must appear in the output.
    :param expected_absent: Substrings that must not appear in the output.
    :param subtests: Pytest's subtest fixture for granular reporting.
    """
    project = tox_project(config_files)
    tox_invocation_result = project.run(
        'config',
        '-e',
        'lock-deps-check',
        '-k',
        *config_keys,
    )
    tox_invocation_result.assert_success()
    for substring in expected_present:
        with subtests.test(msg=f'present: {substring}'):
            assert substring in tox_invocation_result.out
    for substring in expected_absent:
        with subtests.test(msg=f'absent: {substring}'):
            assert substring not in tox_invocation_result.out


def test_check_env_posargs_reach_the_compile_command(
    tox_project: ToxProjectCreator,
) -> None:
    """The check env passes arguments through like the lock env does.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project({'tox.ini': '[tox]\n'})
    tox_invocation_result = project.run(
        'config',
        '-e',
        'lock-deps-check',
        '-k',
        'commands',
        '--',
        '--upgrade',
    )
    tox_invocation_result.assert_success()
    assert 'pyproject.toml --upgrade' in tox_invocation_result.out


def test_check_env_honours_a_cli_override(
    tox_project: ToxProjectCreator,
) -> None:
    """``-x`` reaches the check env, section or no section.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project({'tox.ini': '[tox]\n'})
    tox_invocation_result = project.run(
        'config',
        '-e',
        'lock-deps-check',
        '-k',
        'deps',
        '-x',
        'testenv:lock-deps-check.deps=uv<99',
    )
    tox_invocation_result.assert_success()
    assert 'deps = uv<99' in tox_invocation_result.out


def test_check_env_description_names_both_ends(
    tox_project: ToxProjectCreator,
    subtests: SubTests,
) -> None:
    """``tox list`` says what the check env compares.

    :param tox_project: Tox-provided project factory fixture.
    :param subtests: Pytest's subtest fixture for granular reporting.
    """
    project = tox_project({
        'tox.ini': (
            '[tox]\nlock_file = constraints.txt\nlock_input = base.in\n'
        ),
    })
    tox_invocation_result = project.run('list')
    tox_invocation_result.assert_success()
    for substring in ('constraints.txt', 'base.in', 'fail if it is not'):
        with subtests.test(msg=substring):
            assert substring in tox_invocation_result.out


@pytest.mark.parametrize(
    ('core_section', 'expected_deps'),
    (
        pytest.param(
            '[tox]\n',
            'deps = -r requirements.txt',
            id='lock-file-left-at-its-default',
        ),
        pytest.param(
            '[tox]\nlock_file = requirements/base.txt\n',
            'deps = -r requirements/base.txt',
            id='lock-file-configured',
        ),
    ),
)
def test_lock_file_is_referenceable_from_another_env(
    core_section: str,
    expected_deps: str,
    tox_project: ToxProjectCreator,
) -> None:
    """Other envs can install from the lock without repeating its path.

    ``{[tox]lock_file}`` resolves against the core config set, so the
    setting answers whether or not the project ever wrote it down.
    Were it only readable once spelled out in the config file, every
    project consuming its own lock would have to restate the default
    just to name it -- and would then own that path twice.

    :param core_section: The core section the project is configured with.
    :param expected_deps: The dependency line the reference resolves to.
    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project({
        'tox.ini': (
            f'{core_section}\n'
            '[testenv:use]\n'
            'skip_install = true\n'
            'deps = -r {[tox]lock_file}\n'
        ),
    })
    tox_invocation_result = project.run('config', '-e', 'use', '-k', 'deps')
    tox_invocation_result.assert_success()
    assert expected_deps in tox_invocation_result.out


@pytest.mark.parametrize(
    ('config_files', 'expected_deps'),
    (
        pytest.param({'tox.ini': '[tox]\n'}, 'uv', id='defaults-to-uv'),
        pytest.param(
            {'tox.ini': '[tox]\nlock_uv = uv == 0.9.2\n'},
            'uv == 0.9.2',
            id='ini-pinned',
        ),
        pytest.param(
            {'tox.toml': 'lock_uv = ["uv == 0.9.2"]\n'},
            'uv == 0.9.2',
            id='toml-pinned',
        ),
        pytest.param(
            {'tox.ini': '[tox]\nlock_uv = uv == {env:UV_PIN:0.9.3}\n'},
            'uv == 0.9.3',
            id='substitutions-are-expanded',
        ),
        pytest.param(
            {'tox.ini': '[testenv]\ncommands = pytest\n'},
            'uv',
            id='core-less-config-falls-back-to-the-default',
        ),
    ),
)
@pytest.mark.parametrize('env_name', ('lock-deps', 'lock-deps-check'))
def test_lock_uv_is_configurable_for_both_envs(
    *,
    tox_project: ToxProjectCreator,
    config_files: dict[str, str],
    expected_deps: str,
    env_name: str,
) -> None:
    """One core setting pins the ``uv`` both envs are run with.

    :param tox_project: Tox-provided project factory fixture.
    :param config_files: The tox config files to create in the project.
    :param expected_deps: The dependency the env must end up with.
    :param env_name: The seeded env whose ``deps`` are inspected.
    """
    project = tox_project(config_files)
    tox_invocation_result = project.run(
        'config',
        '-e',
        env_name,
        '-k',
        'deps',
    )
    tox_invocation_result.assert_success()
    assert f'deps = {expected_deps}' in tox_invocation_result.out


def test_lock_uv_does_not_leak_across_the_seeded_envs(
    tox_project: ToxProjectCreator,
) -> None:
    """Overriding one env's ``uv`` leaves the other one alone.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project({'tox.ini': '[tox]\nlock_uv = uv == 0.9.2\n'})
    tox_invocation_result = project.run(
        'config',
        '-e',
        'lock-deps',
        '-k',
        'deps',
        '-x',
        'testenv:lock-deps.deps=uv==0.9.4',
    )
    tox_invocation_result.assert_success()
    assert 'deps = uv==0.9.4' in tox_invocation_result.out


@pytest.mark.parametrize(
    ('config_files', 'expected_base_python'),
    (
        pytest.param(
            {'tox.ini': '[tox]\nlock_python = py312\n'},
            'py312',
            id='ini-pinned',
        ),
        pytest.param(
            {'tox.toml': 'lock_python = ["py312"]\n'},
            'py312',
            id='toml-pinned',
        ),
        pytest.param(
            {'tox.ini': '[tox]\nlock_python = py3{env:PY_MINOR:12}\n'},
            'py312',
            id='substitutions-are-expanded',
        ),
    ),
)
@pytest.mark.parametrize('env_name', ('lock-deps', 'lock-deps-check'))
def test_lock_python_is_configurable_for_both_envs(
    *,
    tox_project: ToxProjectCreator,
    config_files: dict[str, str],
    expected_base_python: str,
    env_name: str,
) -> None:
    """One core setting names the interpreter both envs resolve under.

    :param tox_project: Tox-provided project factory fixture.
    :param config_files: The tox config files to create in the project.
    :param expected_base_python: The interpreter the env must end up with.
    :param env_name: The seeded env whose ``base_python`` is inspected.
    """
    project = tox_project(config_files)
    tox_invocation_result = project.run(
        'config',
        '-e',
        env_name,
        '-k',
        'base_python',
    )
    tox_invocation_result.assert_success()
    assert f'base_python = {expected_base_python}' in tox_invocation_result.out


@pytest.mark.parametrize(
    'config_files',
    (
        pytest.param({'tox.ini': '[tox]\n'}, id='core-section'),
        pytest.param(
            {'tox.ini': '[testenv]\ncommands = pytest\n'},
            id='core-less-config',
        ),
    ),
)
@pytest.mark.parametrize('env_name', ('lock-deps', 'lock-deps-check'))
def test_unset_lock_python_leaves_the_tox_default_alone(
    *,
    tox_project: ToxProjectCreator,
    config_files: dict[str, str],
    env_name: str,
) -> None:
    """An unconfigured interpreter is tox's own, not a seeded guess.

    :param tox_project: Tox-provided project factory fixture.
    :param config_files: The tox config files to create in the project.
    :param env_name: The seeded env whose ``base_python`` is inspected.
    """
    project = tox_project(config_files)
    tox_invocation_result = project.run(
        'config',
        '-e',
        env_name,
        '-k',
        'base_python',
    )
    tox_invocation_result.assert_success()
    assert f'base_python = {sys.executable}' in tox_invocation_result.out


def test_lock_python_does_not_leak_across_the_seeded_envs(
    tox_project: ToxProjectCreator,
) -> None:
    """Overriding one env's interpreter leaves the other one alone.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project({'tox.ini': '[tox]\nlock_python = py312\n'})
    tox_invocation_result = project.run(
        'config',
        '-e',
        'lock-deps',
        '-k',
        'base_python',
        '-x',
        'testenv:lock-deps.base_python=py311',
    )
    tox_invocation_result.assert_success()
    assert 'base_python = py311' in tox_invocation_result.out


@pytest.mark.parametrize(
    ('config_files', 'label', 'expected_envs'),
    (
        pytest.param({'tox.ini': '[tox]\n'}, 'lock', ['lock-deps'], id='ini-default'),
        pytest.param(
            {'tox.ini': '[tox]\n'},
            'lock-check',
            ['lock-deps-check'],
            id='ini-default-check',
        ),
        pytest.param(
            {'tox.toml': 'env_list = []\n'},
            'lock',
            ['lock-deps'],
            id='toml-default',
        ),
        pytest.param(
            {'tox.toml': 'env_list = []\n'},
            'lock-check',
            ['lock-deps-check'],
            id='toml-default-check',
        ),
        pytest.param(
            {'tox.ini': '[testenv]\ncommands = pytest\n'},
            'lock',
            ['lock-deps'],
            id='core-less-config',
        ),
        pytest.param(
            {'tox.ini': '[testenv]\ncommands = pytest\n'},
            'lock-check',
            ['lock-deps-check'],
            id='core-less-config-check',
        ),
        pytest.param(
            {'tox.ini': '[tox]\nlock_labels = pins\n'},
            'pins',
            ['lock-deps'],
            id='ini-configured',
        ),
        pytest.param(
            {'tox.ini': '[tox]\nlock_check_labels = pins-audit\n'},
            'pins-audit',
            ['lock-deps-check'],
            id='ini-configured-check',
        ),
        pytest.param(
            {'tox.toml': 'lock_labels = ["pins"]\n'},
            'pins',
            ['lock-deps'],
            id='toml-configured',
        ),
        pytest.param(
            {'tox.toml': 'lock_check_labels = ["pins-audit"]\n'},
            'pins-audit',
            ['lock-deps-check'],
            id='toml-configured-check',
        ),
        pytest.param(
            {'tox.ini': '[tox]\nlock_labels = {env:LOCK_LABEL:pins}\n'},
            'pins',
            ['lock-deps'],
            id='substitutions-are-expanded',
        ),
        pytest.param(
            {
                'tox.ini':
                '[tox]\nlock_check_labels = {env:LOCK_LABEL:pins-audit}\n',
            },
            'pins-audit',
            ['lock-deps-check'],
            id='substitutions-are-expanded-check',
        ),
        pytest.param(
            {'tox.ini': '[tox]\nlock_labels = pins\nlock_check_labels = pins\n'},
            'pins',
            ['lock-deps', 'lock-deps-check'],
            id='a-project-may-still-group-them',
        ),
    ),
)
def test_each_env_answers_to_its_own_label(
    *,
    tox_project: ToxProjectCreator,
    config_files: dict[str, str],
    label: str,
    expected_envs: list[str],
) -> None:
    """Selecting a label runs the env carrying it and nothing else.

    :param tox_project: Tox-provided project factory fixture.
    :param config_files: The tox config files to create in the project.
    :param label: The label to select the envs by.
    :param expected_envs: The env names the label is expected to select.
    """
    project = tox_project(config_files)
    tox_invocation_result = project.run('list', '--no-desc', '-m', label)
    tox_invocation_result.assert_success()
    assert tox_invocation_result.out.split() == expected_envs


@pytest.mark.parametrize(
    ('config_key', 'label', 'unlabelled_env'),
    (
        pytest.param('lock_labels', 'lock', 'lock-deps', id='write'),
        pytest.param(
            'lock_check_labels',
            'lock-check',
            'lock-deps-check',
            id='check',
        ),
    ),
)
def test_lock_labels_can_be_emptied(
    *,
    tox_project: ToxProjectCreator,
    config_key: str,
    label: str,
    unlabelled_env: str,
) -> None:
    """A project wanting no label at all says so by emptying the key.

    :param tox_project: Tox-provided project factory fixture.
    :param config_key: The core setting to empty.
    :param label: The label that setting would otherwise assign.
    :param unlabelled_env: The env name that label no longer selects.
    """
    project = tox_project({'tox.ini': f'[tox]\n{config_key} =\n'})
    tox_invocation_result = project.run('list', '--no-desc', '-m', label)
    tox_invocation_result.assert_success()
    assert unlabelled_env not in tox_invocation_result.out


def test_lock_labels_are_overridable_per_env(
    tox_project: ToxProjectCreator,
) -> None:
    """Labelling one env by hand drops the label seeded on it.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project({
        'tox.ini': '[tox]\n[testenv:lock-deps]\nlabels = write\n',
    })
    tox_invocation_result = project.run('list', '--no-desc', '-m', 'lock')
    tox_invocation_result.assert_success()
    assert 'lock-deps' not in tox_invocation_result.out


@pytest.mark.parametrize(
    'env_name',
    ('lock-deps', 'lock-deps-check'),
)
def test_uv_environment_is_always_passed_through(
    *,
    tox_project: ToxProjectCreator,
    env_name: str,
) -> None:
    """Both lock envs see the environment `uv` is configured with.

    :param tox_project: Tox-provided project factory fixture.
    :param env_name: The seeded env to inspect.
    """
    project = tox_project({'tox.ini': '[tox]\n'})
    tox_invocation_result = project.run('config', '-e', env_name, '-k', 'pass_env')
    tox_invocation_result.assert_success()
    assert 'UV_*' in tox_invocation_result.out.split()


@pytest.mark.parametrize(
    'config_files',
    (
        pytest.param(
            {'tox.ini': '[tox]\nlock_pass_env =\n    MY_INDEX_TOKEN\n'},
            id='ini',
        ),
        pytest.param({'tox.toml': 'lock_pass_env = ["MY_INDEX_TOKEN"]\n'}, id='toml'),
        pytest.param(
            {'tox.ini': '[tox]\nlock_pass_env = {env:LOCK_VAR:MY_INDEX_TOKEN}\n'},
            id='substitutions-are-expanded',
        ),
    ),
)
@pytest.mark.parametrize(
    'env_name',
    ('lock-deps', 'lock-deps-check'),
)
def test_extra_pass_env_adds_to_the_uv_environment(
    *,
    tox_project: ToxProjectCreator,
    config_files: dict[str, str],
    env_name: str,
) -> None:
    """Naming another variable to pass does not trade `UV_*` away.

    :param tox_project: Tox-provided project factory fixture.
    :param config_files: The tox config files to create in the project.
    :param env_name: The seeded env to inspect.
    """
    project = tox_project(config_files)
    tox_invocation_result = project.run('config', '-e', env_name, '-k', 'pass_env')
    tox_invocation_result.assert_success()
    passed_env = tox_invocation_result.out.split()
    assert {'UV_*', 'MY_INDEX_TOKEN'} <= set(passed_env)


def test_pass_env_is_overridable_per_env(tox_project: ToxProjectCreator) -> None:
    """A command-line override replaces what the plugin seeded.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project({'tox.ini': '[tox]\nlock_pass_env = MY_INDEX_TOKEN\n'})
    tox_invocation_result = project.run(
        'config',
        '-e',
        'lock-deps',
        '-k',
        'pass_env',
        '-x',
        'testenv:lock-deps.pass_env=OTHER_TOKEN',
    )
    tox_invocation_result.assert_success()
    passed_env = tox_invocation_result.out.split()
    assert 'OTHER_TOKEN' in passed_env
    assert 'MY_INDEX_TOKEN' not in passed_env
