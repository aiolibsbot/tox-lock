"""Behavioral tests for the tox-lock plugin."""

from __future__ import annotations

import os
import sys
import typing as _t
from importlib.metadata import version as _installed_version

import pytest
from packaging.version import Version
from tox.config.loader.api import ConfigLoadArgs
from tox.execute.request import shell_cmd

from tox_plugins.lock._plugin import _SeedLoader, _split_option


if _t.TYPE_CHECKING:
    from pytest_subtests import SubTests
    from tox.pytest import ToxProjectCreator


# NOTE: ``tox`` only began expanding the substitutions in an override's
# NOTE: value before handing it to the loader in v4.62.0. Older releases
# NOTE: run this plugin perfectly well -- they just pass
# NOTE: ``{env:LOCK_PIN}`` through with its braces on, as they do for
# NOTE: every other env. That is `tox`'s behaviour rather than the
# NOTE: plugin's, so it gates the cases that depend on it instead of
# NOTE: the floor `pyproject.toml` declares. The same release is where
# NOTE: `Loader.substitute()` -- the method the seed loader overrides,
# NOTE: and the one it delegates to -- came to exist at all.
#
# Ref: https://github.com/tox-dev/tox/pull/4048
_substituted_overrides = pytest.mark.skipif(
    Version(_installed_version('tox')) < Version('4.62'),
    reason='`tox` expands the substitutions in an override since v4.62.0',
)


def _native_paths(expected: str) -> str:
    """Respell a path expectation for the platform the suite runs on.

    The config files these tests write spell their paths with forward
    slashes -- the spelling both tox formats accept everywhere. What
    comes back out of ``tox config`` is ``str(Path(...))``, so on
    Windows the separators are backslashes and an expectation written
    the way the input was matches nothing.

    :param expected: The expected substring, POSIX-spelled.
    :returns: The same substring, spelled for the running platform.
    """
    return expected.replace('/', os.sep)


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
        pytest.param(
            'ignore_errors',
            (),
            ('ignore_errors = True',),
            id='lock-deps-writes-every-lock-it-can',
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
            assert _native_paths(substring) in tox_invocation_result.out


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
            marks=_substituted_overrides,
            id='cli-override-substitutions-are-expanded',
        ),
        pytest.param(
            {'tox.ini': '[testenv]\ncommands = pytest\n'},
            ('-x', 'testenv:lock-deps.deps={env:LOCK_PIN:uv<97}'),
            ('deps = uv<97',),
            (),
            marks=_substituted_overrides,
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
            assert _native_paths(substring) in tox_invocation_result.out
    for substring in expected_absent:
        with subtests.test(msg=f'absent: {substring}'):
            assert _native_paths(substring) not in tox_invocation_result.out


# NOTE: The three cases above drive `_SeedLoader.substitute` through the
# NOTE: command line, and reach it on a narrow band of `tox` releases:
# NOTE: v4.62.0 is where an override's value began being expanded at
# NOTE: all, and from v4.64.1 `tox` builds a real config-file loader for
# NOTE: a section the file lacks -- which outranks the seed, so the
# NOTE: expansion happens there instead. In between, the seed loader is
# NOTE: the only thing carrying the override, and the declared floor is
# NOTE: below the whole band, so the method cannot be deleted either.
# NOTE: No single supported `tox` therefore runs it end to end, and a
# NOTE: coverage gate measuring one is a gate on which `tox` the lock
# NOTE: happens to pin. These cases call the method directly, so what
# NOTE: is measured is the method rather than the release.
#
# Refs:
# * https://github.com/tox-dev/tox/pull/4048
@pytest.mark.parametrize(
    ('config_files', 'raw_value', 'expected_value'),
    (
        pytest.param(
            {'tox.ini': '[tox]\n[testenv]\ndeps = pytest\n'},
            '{[testenv]deps}',
            'pytest',
            # NOTE: The delegation this case is about is to
            # NOTE: `Loader.substitute()`, which is itself only there
            # NOTE: from v4.62.0 -- the same release that started
            # NOTE: calling it. Below that the override here is inert
            # NOTE: rather than wrong: nothing in `tox` reaches it, and
            # NOTE: there is no older API for it to have delegated to.
            marks=_substituted_overrides,
            id='a-core-section-resolves-a-section-reference',
        ),
        pytest.param(
            {'tox.ini': '[testenv]\ndeps = pytest\n'},
            '{env:LOCK_PIN:uv<97}',
            'uv<97',
            id='a-core-less-config-still-reads-the-environment',
        ),
        pytest.param(
            {'tox.ini': '[testenv]\ndeps = pytest\n'},
            '{[testenv]deps}',
            '{[testenv]deps}',
            id='a-core-less-config-leaves-a-section-reference-alone',
        ),
    ),
)
def test_seed_loader_expands_an_override_value(
    *,
    tox_project: ToxProjectCreator,
    config_files: dict[str, str],
    raw_value: str,
    expected_value: str,
) -> None:
    """The seed loader expands an override the way the config file would.

    :param tox_project: Tox-provided project factory fixture.
    :param config_files: The tox config files to create in the project.
    :param raw_value: The override value as the user typed it.
    :param expected_value: What expanding that value must produce.
    """
    project = tox_project(config_files)
    tox_invocation_result = project.run('config', '-e', 'lock-deps')
    tox_invocation_result.assert_success()

    tox_config = tox_invocation_result.state.conf
    config_load_args = ConfigLoadArgs(
        chain=[],
        name='deps',
        env_name='lock-deps',
    )
    substituted_value = _SeedLoader().substitute(
        raw_value,
        tox_config,
        config_load_args,
    )
    assert substituted_value == expected_value


def test_posargs_reach_the_command_verbatim(
    tox_project: ToxProjectCreator,
) -> None:
    r"""An escaped comment character survives into the lock command.

    Seeding a :class:`~tox.config.types.Command` rather than a shell
    string keeps the arguments exactly as typed. A string would be
    re-split by ``StrConvert.to_command()``, which rewrites ``\#`` into
    ``#`` -- silently pointing the option at a different file than the
    one the user named.

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
        '--constraint',
        'out\\#1.txt',
    )
    tox_invocation_result.assert_success()
    assert shell_cmd(('out\\#1.txt',)) in tox_invocation_result.out


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
                    'lock_files = '
                    'requirements/base.txt = requirements/base.in\n'
                ),
            },
            ('--output-file requirements/base.txt requirements/base.in',),
            id='ini-custom-paths',
        ),
        pytest.param(
            {
                'tox.toml': (
                    'lock_files = '
                    '{ "constraints.txt" = ["setup.cfg"] }\n'
                ),
            },
            ('--output-file constraints.txt setup.cfg',),
            id='toml-custom-paths',
        ),
        pytest.param(
            {
                'tox.ini': (
                    '[tox]\n'
                    'lock_files = requirements.txt = '
                    'requirements/base.in, requirements/test.in\n'
                ),
            },
            (
                (
                    '--output-file requirements.txt '
                    'requirements/base.in requirements/test.in'
                ),
            ),
            id='ini-several-inputs',
        ),
        pytest.param(
            {
                'tox.toml': (
                    'lock_files = { "requirements.txt" = '
                    '["requirements/base.in", "requirements/test.in"] }\n'
                ),
            },
            (
                (
                    '--output-file requirements.txt '
                    'requirements/base.in requirements/test.in'
                ),
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
            assert _native_paths(substring) in tox_invocation_result.out


def test_lock_paths_expand_substitutions(
    tox_project: ToxProjectCreator,
) -> None:
    """A core-section path gets the config file's own substitutions.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project({
        'tox.ini':
            '[tox]\nlock_files = '
            '{env:LOCK_OUT:pinned.txt} = pyproject.toml\n',
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
            'lock_files = constraints.txt = base.in, test.in\n'
        ),
    })
    tox_invocation_result = project.run('list')
    tox_invocation_result.assert_success()
    for substring in ('constraints.txt', 'base.in, test.in'):
        with subtests.test(msg=substring):
            assert _native_paths(substring) in tox_invocation_result.out


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
            {
                'tox.ini':
                    '[tox]\nlock_options = {env:LOCK_OPTS:--no-annotate}\n',
            },
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
            assert _native_paths(substring) in tox_invocation_result.out
    for substring in expected_absent:
        with subtests.test(msg=f'absent: {substring}'):
            assert _native_paths(substring) not in tox_invocation_result.out


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
    assert (
        shell_cmd(('--custom-compile-command', 'make lock'))
        in tox_invocation_result.out
    )


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
            {
                'tox.ini':
                    '[tox]\nlock_files = '
                    'requirements/base.txt = pyproject.toml\n',
            },
            ('commands', 'commands_pre'),
            ('requirements/base.txt',),
            ('--output-file requirements/base.txt',),
            id='scratch-file-follows-a-custom-lock-name',
        ),
        pytest.param(
            {
                'tox.ini': (
                    '[tox]\nlock_options =\n'
                    'lock_files = requirements.txt = requirements.in\n'
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
        pytest.param(
            {'tox.ini': '[tox]\n'},
            ('ignore_errors',),
            ('ignore_errors = False',),
            (),
            id='stops-at-a-recompile-it-could-not-run',
        ),
        pytest.param(
            {
                'tox.ini': (
                    '[tox]\n[testenv:lock-deps]\nignore_errors = true\n'
                ),
            },
            ('ignore_errors',),
            ('ignore_errors = False',),
            (),
            id='the-writers-ignore-errors-is-not-inherited',
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
            assert _native_paths(substring) in tox_invocation_result.out
    for substring in expected_absent:
        with subtests.test(msg=f'absent: {substring}'):
            assert _native_paths(substring) not in tox_invocation_result.out


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
            '[tox]\nlock_files = constraints.txt = base.in\n'
        ),
    })
    tox_invocation_result = project.run('list')
    tox_invocation_result.assert_success()
    for substring in ('constraints.txt', 'base.in', 'fail if it is not'):
        with subtests.test(msg=substring):
            assert _native_paths(substring) in tox_invocation_result.out


def test_a_lock_path_is_nameable_once_for_both_ends(
    tox_project: ToxProjectCreator,
    subtests: SubTests,
) -> None:
    """A project names a lock once and both ends of it follow.

    With several locks there is no longer a single ``lock_file`` key an
    env installing from one could point at, so the path is named where
    it belongs -- in a section of the project's own -- and referenced
    from both the mapping that compiles it and the env that installs
    it. Stock tox resolves the reference on either side, so nothing
    here owns the path twice.

    :param tox_project: Tox-provided project factory fixture.
    :param subtests: Pytest's subtest fixture for granular reporting.
    """
    project = tox_project({
        'tox.ini': (
            '[tox]\n'
            'lock_files = {[lock]test} = requirements/test.in\n'
            '[lock]\n'
            'test = requirements/test.txt\n'
            '[testenv:use]\n'
            'skip_install = true\n'
            'deps = -r {[lock]test}\n'
        ),
    })

    # NOTE: The compile command names the lock as a `Path`, so it
    # NOTE: comes back out spelled with the platform's own separator.
    # NOTE: `deps` is the string the project wrote, which tox hands
    # NOTE: back untouched -- forward slash and all, everywhere.
    expectations = (
        (
            'lock-deps',
            'commands',
            _native_paths('--output-file requirements/test.txt'),
        ),
        ('use', 'deps', 'deps = -r requirements/test.txt'),
    )
    for env_name, config_key, expected in expectations:
        tox_invocation_result = project.run(
            'config',
            '-e',
            env_name,
            '-k',
            config_key,
        )
        with subtests.test(msg=f'{env_name} resolves the reference'):
            tox_invocation_result.assert_success()
            assert expected in tox_invocation_result.out


@pytest.mark.parametrize(
    ('config_files', 'expected_commands'),
    (
        pytest.param(
            {
                'tox.ini': (
                    '[tox]\n'
                    'lock_files =\n'
                    '  requirements/base.txt = requirements/base.in\n'
                    '  requirements/test.txt = '
                    'requirements/base.in, requirements/test.in\n'
                ),
            },
            (
                '--output-file requirements/base.txt requirements/base.in',
                (
                    '--output-file requirements/test.txt '
                    'requirements/base.in requirements/test.in'
                ),
            ),
            id='ini-several-locks',
        ),
        pytest.param(
            {
                'tox.toml': (
                    'lock_files = { "base.txt" = ["base.in"], '
                    '"test.txt" = ["base.in", "test.in"] }\n'
                ),
            },
            (
                '--output-file base.txt base.in',
                '--output-file test.txt base.in test.in',
            ),
            id='toml-several-locks',
        ),
    ),
)
def test_every_configured_lock_gets_compiled(
    *,
    tox_project: ToxProjectCreator,
    config_files: dict[str, str],
    expected_commands: tuple[str, ...],
    subtests: SubTests,
) -> None:
    """A project's dependency sets each get a lock of their own.

    ``uv pip compile`` writes one output per invocation, so the writer
    env runs one per configured lock rather than the plugin picking a
    single set of requirements to be the project's.

    :param tox_project: Tox-provided project factory fixture.
    :param config_files: The tox config files to create in the project.
    :param expected_commands: The compile commands that must be seeded.
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
    for expected_command in expected_commands:
        with subtests.test(msg=expected_command):
            assert _native_paths(expected_command) in tox_invocation_result.out


def test_locks_sharing_a_name_get_scratch_files_of_their_own(
    tox_project: ToxProjectCreator,
) -> None:
    """Two locks with one file name do not compile over each other.

    The check env compiles into the tox temp dir, and a project is free
    to keep ``requirements/base.txt`` next to ``constraints/base.txt``.
    Were the scratch file named after the lock alone, the second
    compile would land on the first one's output and both comparisons
    would read the same file -- a check that passes by overwriting its
    own evidence.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project({
        'tox.ini': (
            '[tox]\n'
            'lock_files =\n'
            '  requirements/base.txt = requirements/base.in\n'
            '  constraints/base.txt = constraints/base.in\n'
        ),
    })
    tox_invocation_result = project.run(
        'config',
        '-e',
        'lock-deps-check',
        '-k',
        'commands',
    )
    tox_invocation_result.assert_success()

    scratch_outputs = {
        argument
        for line in tox_invocation_result.out.splitlines()
        for argument in line.split()
        if argument.endswith('base.txt') and 'base.txt' in argument
        if '.tmp' in argument
    }
    assert len(scratch_outputs) == 2  # noqa: PLR2004


@pytest.mark.parametrize(
    'lock_file_name',
    ('pylock.toml', 'pylock.dev.toml'),
    ids=('the-plain-name', 'a-named-lock'),
)
def test_a_pep_751_lock_keeps_its_name_into_the_scratch_file(
    tox_project: ToxProjectCreator,
    lock_file_name: str,
    subtests: SubTests,
) -> None:
    """Naming the lock is the whole of asking for a PEP 751 one.

    ``uv`` reads the output format off the file name -- ``pylock.toml``
    and ``pylock.<name>.toml`` are written as PEP 751 locks, everything
    else as ``requirements.txt`` ones -- so a project gets one by
    naming it, with no option and no setting of this plugin's own. The
    check env has to compile into a scratch file carrying that same
    name, or it would produce a ``requirements.txt`` lock to compare
    against a PEP 751 one and report every line of a current lock as
    drift.

    :param tox_project: Tox-provided project factory fixture.
    :param lock_file_name: The PEP 751 lock name under test.
    :param subtests: Pytest's subtest fixture for granular reporting.
    """
    project = tox_project({
        'tox.ini': f'[tox]\nlock_files = {lock_file_name} = pyproject.toml\n',
    })

    expected_envs = {
        'lock-deps': f'--output-file {lock_file_name}',
        'lock-deps-check': f'{lock_file_name} pyproject.toml',
    }
    for env_name, expected_argument in expected_envs.items():
        tox_invocation_result = project.run(
            'config',
            '-e',
            env_name,
            '-k',
            'commands',
        )
        tox_invocation_result.assert_success()
        with subtests.test(msg=env_name):
            assert expected_argument in tox_invocation_result.out


def test_locking_nothing_is_refused_rather_than_seeded(
    tox_project: ToxProjectCreator,
    subtests: SubTests,
) -> None:
    """An empty mapping fails loudly instead of checking nothing.

    Seeded as-is it would leave the writer compiling nothing and the
    check passing every time, which is a green CI job asserting that no
    lock is stale by virtue of there being none.

    :param tox_project: Tox-provided project factory fixture.
    :param subtests: Pytest's subtest fixture for granular reporting.
    """
    project = tox_project({'tox.ini': '[tox]\nlock_files =\n'})
    tox_invocation_result = project.run('list')

    with subtests.test(msg='the run fails'):
        assert tox_invocation_result.code != 0

    for expected_text in ('`lock_files`', 'names no lock at all'):
        with subtests.test(msg=f'the message says {expected_text}'):
            assert expected_text in tox_invocation_result.out


@pytest.mark.parametrize(
    ('config_files', 'expected_deps'),
    (
        pytest.param({'tox.ini': '[tox]\n'}, 'uv', id='defaults-to-uv'),
        pytest.param(
            {'tox.ini': '[tox]\n[testenv:lock-deps]\ndeps = uv == 0.9.2\n'},
            'uv == 0.9.2',
            id='ini-pinned-on-the-writer',
        ),
        pytest.param(
            {'tox.toml': '[env.lock-deps]\ndeps = ["uv == 0.9.2"]\n'},
            'uv == 0.9.2',
            id='toml-pinned-on-the-writer',
        ),
        pytest.param(
            {
                'tox.ini':
                '[tox]\n[testenv:lock-deps]\n'
                'deps = uv == {env:UV_PIN:0.9.3}\n',
            },
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
def test_the_resolver_is_pinned_once_for_both_envs(
    *,
    tox_project: ToxProjectCreator,
    config_files: dict[str, str],
    expected_deps: str,
    env_name: str,
) -> None:
    """Pinning ``uv`` on the writer env pins it for the check env too.

    Two ``uv`` releases may pin the same requirements differently, so a
    check resolving with one while the lock was written with another
    reports drift that is not there.

    :param tox_project: Tox-provided project factory fixture.
    :param config_files: The tox config files to create in the project.
    :param expected_deps: The dependency both envs must end up with.
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


def test_the_check_env_may_still_pin_its_own_resolver(
    tox_project: ToxProjectCreator,
) -> None:
    """A check env section outranks the writer env it inherits from.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project({
        'tox.ini': (
            '[tox]\n'
            '[testenv:lock-deps]\n'
            'deps = uv == 0.9.2\n'
            '[testenv:lock-deps-check]\n'
            'deps = uv == 0.9.9\n'
        ),
    })
    tox_invocation_result = project.run(
        'config',
        '-e',
        'lock-deps-check',
        '-k',
        'deps',
    )
    tox_invocation_result.assert_success()
    assert 'deps = uv == 0.9.9' in tox_invocation_result.out


@pytest.mark.parametrize(
    ('config_files', 'expected_base_python'),
    (
        pytest.param(
            {'tox.ini': '[tox]\n[testenv:lock-deps]\nbase_python = py312\n'},
            'py312',
            id='ini-named-on-the-writer',
        ),
        pytest.param(
            {'tox.toml': '[env.lock-deps]\nbase_python = ["py312"]\n'},
            'py312',
            id='toml-named-on-the-writer',
        ),
        pytest.param(
            {
                'tox.ini':
                '[tox]\n[testenv:lock-deps]\n'
                'base_python = py3{env:PY_MINOR:12}\n',
            },
            'py312',
            id='substitutions-are-expanded',
        ),
    ),
)
@pytest.mark.parametrize('env_name', ('lock-deps', 'lock-deps-check'))
def test_the_interpreter_is_named_once_for_both_envs(
    *,
    tox_project: ToxProjectCreator,
    config_files: dict[str, str],
    expected_base_python: str,
    env_name: str,
) -> None:
    """Naming the writer env's interpreter names the check env's as well.

    ``uv pip compile`` resolves for the Python it runs under, so the
    same sources compiled on 3.11 and on 3.13 legitimately differ.

    :param tox_project: Tox-provided project factory fixture.
    :param config_files: The tox config files to create in the project.
    :param expected_base_python: The interpreter both envs must end up with.
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
def test_an_unnamed_interpreter_is_left_to_tox(
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


@pytest.mark.parametrize(
    ('config_key', 'user_value'),
    (
        pytest.param('commands', 'echo hi', id='commands'),
        pytest.param('commands_pre', 'echo hi', id='commands_pre'),
        pytest.param('commands_post', 'echo hi', id='commands_post'),
        pytest.param('description', 'hi', id='description'),
        pytest.param('labels', 'hi', id='labels'),
        pytest.param('package', 'wheel', id='package'),
    ),
)
def test_the_writer_env_settings_the_plugin_owns_stay_behind(
    *,
    tox_project: ToxProjectCreator,
    config_key: str,
    user_value: str,
) -> None:
    """What the plugin owns on the writer does not reach the check env.

    The check env inherits the writer's section so that a project
    configures the two alike where it matters -- the resolver, the
    interpreter, the environment. What makes the two envs *different*
    must not come along: a project rewriting the writer's commands
    would otherwise have the check env run them instead of checking
    anything.

    :param tox_project: Tox-provided project factory fixture.
    :param config_key: The env setting written on the writer env.
    :param user_value: The value written there.
    """
    project = tox_project({
        'tox.ini':
        f'[tox]\n[testenv:lock-deps]\n{config_key} = {user_value}\n',
    })
    tox_invocation_result = project.run(
        'config',
        '-e',
        'lock-deps-check',
        '-k',
        config_key,
    )
    tox_invocation_result.assert_success()
    assert f'{config_key} = {user_value}' not in tox_invocation_result.out


@pytest.mark.parametrize(
    'config_files',
    (
        pytest.param(
            {'tox.ini': '[tox]\n[testenv]\ndeps = pytest\n'},
            id='ini-without-a-writer-section',
        ),
        pytest.param(
            {
                'tox.ini':
                '[tox]\n[testenv]\ndeps = pytest\n[testenv:lock-deps]\n',
            },
            id='ini-through-a-writer-section',
        ),
        pytest.param(
            {'tox.toml': '[env_run_base]\ndeps = ["pytest"]\n'},
            id='toml-without-a-writer-table',
        ),
    ),
)
def test_the_generic_env_does_not_reach_the_check_env(
    *,
    tox_project: ToxProjectCreator,
    config_files: dict[str, str],
) -> None:
    """Inheriting the writer env does not drag ``[testenv]`` along.

    tox does not chain ``base`` through the section it names, which is
    what keeps the check env off a project's generic test settings even
    though the writer env it inherits from sits under them.

    :param tox_project: Tox-provided project factory fixture.
    :param config_files: The tox config files to create in the project.
    """
    project = tox_project(config_files)
    tox_invocation_result = project.run(
        'config',
        '-e',
        'lock-deps-check',
        '-k',
        'deps',
    )
    tox_invocation_result.assert_success()
    assert 'pytest' not in tox_invocation_result.out


@pytest.mark.parametrize(
    ('config_files', 'label', 'expected_envs'),
    (
        pytest.param(
            {'tox.ini': '[tox]\n'},
            'lock',
            ['lock-deps'],
            id='ini-default',
        ),
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
            {'tox.ini': '[tox]\n[testenv:lock-deps]\nlabels = pins\n'},
            'pins',
            ['lock-deps'],
            id='ini-renamed-on-the-writer',
        ),
        pytest.param(
            {
                'tox.ini':
                '[tox]\n[testenv:lock-deps-check]\nlabels = pins-audit\n',
            },
            'pins-audit',
            ['lock-deps-check'],
            id='ini-renamed-on-the-checker',
        ),
        pytest.param(
            {'tox.toml': '[env.lock-deps]\nlabels = ["pins"]\n'},
            'pins',
            ['lock-deps'],
            id='toml-renamed-on-the-writer',
        ),
        pytest.param(
            {
                'tox.ini':
                '[tox]\n[testenv:lock-deps]\n'
                'labels = {env:LOCK_LABEL:pins}\n',
            },
            'pins',
            ['lock-deps'],
            id='substitutions-are-expanded',
        ),
        pytest.param(
            {
                'tox.ini':
                '[tox]\n'
                '[testenv:lock-deps]\nlabels = pins\n'
                '[testenv:lock-deps-check]\nlabels = pins\n',
            },
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
    ('env_name', 'label'),
    (
        pytest.param('lock-deps', 'lock', id='write'),
        pytest.param('lock-deps-check', 'lock-check', id='check'),
    ),
)
def test_a_seeded_label_can_be_emptied(
    *,
    tox_project: ToxProjectCreator,
    env_name: str,
    label: str,
) -> None:
    """A project wanting no label at all says so in the env's section.

    :param tox_project: Tox-provided project factory fixture.
    :param env_name: The env to strip the seeded label off.
    :param label: The label that env would otherwise answer to.
    """
    project = tox_project({
        'tox.ini': f'[tox]\n[testenv:{env_name}]\nlabels =\n',
    })
    tox_invocation_result = project.run('list', '--no-desc', '-m', label)
    tox_invocation_result.assert_success()
    assert env_name not in tox_invocation_result.out


def test_a_hand_written_label_replaces_the_seeded_one(
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
    tox_invocation_result = project.run(
        'config', '-e', env_name, '-k', 'pass_env',
    )
    tox_invocation_result.assert_success()
    assert 'UV_*' in tox_invocation_result.out.split()


@pytest.mark.parametrize(
    'config_files',
    (
        pytest.param(
            {'tox.ini': '[tox]\nlock_pass_env =\n    MY_INDEX_TOKEN\n'},
            id='ini',
        ),
        pytest.param(
            {'tox.toml': 'lock_pass_env = ["MY_INDEX_TOKEN"]\n'},
            id='toml',
        ),
        pytest.param(
            {
                'tox.ini':
                    '[tox]\n'
                    'lock_pass_env = {env:LOCK_VAR:MY_INDEX_TOKEN}\n',
            },
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
    tox_invocation_result = project.run(
        'config', '-e', env_name, '-k', 'pass_env',
    )
    tox_invocation_result.assert_success()
    passed_env = tox_invocation_result.out.split()
    assert {'UV_*', 'MY_INDEX_TOKEN'} <= set(passed_env)


def test_pass_env_is_overridable_per_env(
        tox_project: ToxProjectCreator,
) -> None:
    """A command-line override replaces what the plugin seeded.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project(
        {'tox.ini': '[tox]\nlock_pass_env = MY_INDEX_TOKEN\n'},
    )
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


@pytest.mark.parametrize('env_name', ('lock-deps', 'lock-deps-check'))
def test_lock_header_names_the_env_that_reproduces_it(
    tox_project: ToxProjectCreator,
    env_name: str,
) -> None:
    """Both envs stamp the lock with a command a reader can run.

    :param tox_project: Tox-provided project factory fixture.
    :param env_name: The seeded env whose command is inspected.
    """
    project = tox_project({'tox.ini': '[tox]\n'})
    tox_invocation_result = project.run(
        'config',
        '-e',
        env_name,
        '-k',
        'commands',
    )
    tox_invocation_result.assert_success()
    assert (
        shell_cmd(('--custom-compile-command', 'tox run -e lock-deps'))
        in tox_invocation_result.out
    )


@pytest.mark.parametrize(
    ('config_files', 'extra_args', 'expected_command'),
    (
        pytest.param(
            {
                'tox.ini': (
                    '[tox]\n'
                    'lock_options = --custom-compile-command "make lock"\n'
                ),
            },
            (),
            'make lock',
            id='named-in-lock-options',
        ),
        pytest.param(
            {
                'tox.ini': (
                    '[tox]\n'
                    'lock_options = --custom-compile-command=make\n'
                ),
            },
            (),
            '--custom-compile-command=make',
            id='named-in-lock-options-glued-to-its-value',
        ),
        pytest.param(
            {'tox.ini': '[tox]\n'},
            ('--', '--custom-compile-command', 'make lock'),
            'make lock',
            id='named-in-posargs',
        ),
    ),
)
@pytest.mark.parametrize('env_name', ('lock-deps', 'lock-deps-check'))
def test_a_configured_lock_header_replaces_the_seeded_one(
    *,
    tox_project: ToxProjectCreator,
    config_files: dict[str, str],
    extra_args: tuple[str, ...],
    expected_command: str,
    env_name: str,
) -> None:
    """The seeded header withdraws rather than duplicating the option.

    ``uv`` rejects a repeated ``--custom-compile-command``, so the two
    appearing side by side would fail the run outright.

    :param tox_project: Tox-provided project factory fixture.
    :param config_files: The tox config files to create in the project.
    :param extra_args: Extra CLI arguments to append to the ``tox`` call.
    :param expected_command: The header command the user configured.
    :param env_name: The seeded env whose command is inspected.
    """
    project = tox_project(config_files)
    tox_invocation_result = project.run(
        'config',
        '-e',
        env_name,
        '-k',
        'commands',
        *extra_args,
    )
    tox_invocation_result.assert_success()
    assert _native_paths(expected_command) in tox_invocation_result.out
    assert (
        shell_cmd(('--custom-compile-command', 'tox run -e lock-deps'))
        not in tox_invocation_result.out
    )
    assert tox_invocation_result.out.count('--custom-compile-command') == 1


@pytest.mark.parametrize(
    ('config_files', 'extra_args', 'expected_source'),
    (
        pytest.param(
            {'tox.ini': '[tox]\nlock_options = --output-file mine.txt\n'},
            (),
            '`lock_options`',
            id='long-option-in-lock-options',
        ),
        pytest.param(
            {'tox.ini': '[tox]\nlock_options = --output-file=mine.txt\n'},
            (),
            '`lock_options`',
            id='long-option-glued-to-its-value',
        ),
        pytest.param(
            {'tox.ini': '[tox]\nlock_options = -o mine.txt\n'},
            (),
            '`lock_options`',
            id='short-option-in-lock-options',
        ),
        pytest.param(
            {'tox.ini': '[tox]\nlock_options = -omine.txt\n'},
            (),
            '`lock_options`',
            id='short-option-glued-to-its-value',
        ),
        pytest.param(
            {'tox.ini': '[tox]\n'},
            ('--', '--output-file', 'mine.txt'),
            'the arguments after `--`',
            id='named-in-posargs',
        ),
    ),
)
@pytest.mark.parametrize('env_name', ('lock-deps', 'lock-deps-check'))
def test_a_user_supplied_output_file_is_refused(
    *,
    tox_project: ToxProjectCreator,
    config_files: dict[str, str],
    extra_args: tuple[str, ...],
    expected_source: str,
    env_name: str,
    subtests: SubTests,
) -> None:
    """Naming the output file fails with a pointer to ``lock_files``.

    It is the one option the plugin refuses rather than yields: the
    check env is a check only because its output goes somewhere else.

    :param tox_project: Tox-provided project factory fixture.
    :param config_files: The tox config files to create in the project.
    :param extra_args: Extra CLI arguments to append to the ``tox`` call.
    :param expected_source: The argument source the message must name.
    :param env_name: The seeded env whose command is inspected.
    :param subtests: Pytest's subtest fixture for granular reporting.
    """
    project = tox_project(config_files)
    tox_invocation_result = project.run(
        'config',
        '-e',
        env_name,
        '-k',
        'commands',
        *extra_args,
    )

    with subtests.test(msg='the run fails'):
        assert tox_invocation_result.code != 0

    for expected_text in (
        '`--output-file`',
        expected_source,
        '`lock_files`',
    ):
        with subtests.test(msg=f'the message names {expected_text}'):
            assert expected_text in tox_invocation_result.out


def test_an_output_file_lookalike_option_is_left_alone(
    tox_project: ToxProjectCreator,
) -> None:
    """An option merely resembling the refused one still works.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project(
        {'tox.ini': '[tox]\nlock_options = --no-strip-extras\n'},
    )
    tox_invocation_result = project.run(
        'config',
        '-e',
        'lock-deps',
        '-k',
        'commands',
    )
    tox_invocation_result.assert_success()
    assert '--no-strip-extras' in tox_invocation_result.out


@pytest.mark.parametrize(
    ('platform', 'option', 'expected_args'),
    (
        pytest.param(
            'linux',
            r'--constraint /pins/base.txt',
            ('--constraint', '/pins/base.txt'),
            id='posix-a-path',
        ),
        pytest.param(
            'linux',
            '--custom-compile-command "make lock"',
            ('--custom-compile-command', 'make lock'),
            id='posix-a-quoted-value',
        ),
        pytest.param(
            'linux',
            r'--constraint /pins/escaped\ name.txt',
            ('--constraint', '/pins/escaped name.txt'),
            id='posix-an-escaped-space',
        ),
        pytest.param(
            'win32',
            r'--constraint C:\pins\base.txt',
            ('--constraint', r'C:\pins\base.txt'),
            id='win32-a-path-keeps-its-separators',
        ),
        pytest.param(
            'win32',
            r'--constraint "C:\my pins\base.txt"',
            ('--constraint', r'C:\my pins\base.txt'),
            id='win32-a-quoted-path-loses-its-quotes',
        ),
        pytest.param(
            'win32',
            "--custom-compile-command 'make lock'",
            ('--custom-compile-command', 'make lock'),
            id='win32-single-quotes-too',
        ),
        pytest.param(
            'win32',
            '--generate-hashes',
            ('--generate-hashes',),
            id='win32-a-bare-option',
        ),
        pytest.param(
            'win32',
            '--custom-compile-command ""',
            ('--custom-compile-command', ''),
            id='win32-an-empty-quoted-value',
        ),
    ),
)
def test_an_option_is_split_the_way_the_platform_spells_paths(
    *,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    option: str,
    expected_args: tuple[str, ...],
) -> None:
    """``lock_options`` survives a backslash where one means a path.

    Exercised by calling the splitter rather than by running ``tox``,
    because what is being asserted is the behaviour of a platform the
    suite is not necessarily running on -- and the two branches would
    otherwise each be reachable on one CI runner only.

    :param monkeypatch: Pytest's attribute patching fixture.
    :param platform: The value :data:`sys.platform` is to report.
    :param option: One entry of ``lock_options``, as the user wrote it.
    :param expected_args: The command arguments it must split into.
    """
    monkeypatch.setattr(sys, 'platform', platform)
    assert tuple(_split_option(option)) == expected_args


def test_the_writer_can_be_put_back_on_fail_fast(
    tox_project: ToxProjectCreator,
) -> None:
    """Running every compile is a default, not a fixture of the env.

    A project preferring the first failure to end the run says so in the
    env's own section, which outranks every seed.

    :param tox_project: Tox-provided project factory fixture.
    """
    project = tox_project({
        'tox.ini': '[tox]\n[testenv:lock-deps]\nignore_errors = false\n',
    })
    tox_invocation_result = project.run(
        'config',
        '-e',
        'lock-deps',
        '-k',
        'ignore_errors',
    )
    tox_invocation_result.assert_success()
    assert 'ignore_errors = False' in tox_invocation_result.out
