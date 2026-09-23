"""A tox plugin providing a pre-configured dependency locking environment."""

from __future__ import annotations

import typing as _t
from shlex import join as shlex_join

from tox.config.loader.memory import MemoryLoader
from tox.plugin import impl


if _t.TYPE_CHECKING:
    from collections import abc as _c  # noqa: WPS347

    from tox.config.sets import ConfigSet, EnvConfigSet
    from tox.session.state import State


_ENV_NAME = 'lock-deps'

_PYTHON_CLI_OPTIONS = (
    'python',
    '-bb',
    '-E',
    '-s',
    '-I',
    '-Werror',
)

# NOTE: `MemoryLoader` values are not subjected to substitutions, so the
# NOTE: paths are relative to `change_dir` that defaults to the tox root --
# NOTE: the same place the input `pyproject.toml` is read from.
_LOCK_COMMAND_PREFIX = (
    *_PYTHON_CLI_OPTIONS,
    '-m',
    'uv',
    'pip',
    'compile',
    '--generate-hashes',
    '--output-file',
    'requirements.txt',
    'pyproject.toml',
)


@impl
def tox_extend_envs() -> _c.Iterable[str]:
    """Declare the dependency locking environment.

    :returns: The names of the tox environments this plugin provides.
    """
    return (_ENV_NAME,)


@impl
def tox_add_env_config(
    env_conf: EnvConfigSet,
    state: State,  # noqa: ARG001  # pylint: disable=unused-argument
) -> None:
    """Let the user's own env section override the plugin defaults.

    tox puts ``memory_seed_loaders`` in front of the loaders reading
    ``[testenv:<name>]`` / ``[env.<name>]``, which would silently shadow
    explicit settings and ``-x`` overrides targeting those sections. The
    seeded ``base=[]`` still keeps the ``[testenv]`` base section out.

    :param env_conf: The configuration set of the env being built.
    :param state: The tox session state (unused).
    """
    if env_conf.name != _ENV_NAME:
        return

    # NOTE: `list.sort()` is stable, so the loaders keep their relative
    # NOTE: order within the user-section and the plugin-default groups.
    env_conf.loaders.sort(
        key=lambda loader: loader.section.name != env_conf.name,
    )


@impl
def tox_add_core_config(
    core_conf: ConfigSet,  # noqa: ARG001  # pylint: disable=unused-argument
    state: State,
) -> None:
    """Inject default configuration for the locking environment.

    :param core_conf: The core tox configuration set (unused).
    :param state: The tox session state to inject the environment into.
    """
    pos_args = state.conf.pos_args(to_path=None)
    lock_cmd = (
        *_LOCK_COMMAND_PREFIX,
        *(() if pos_args is None else pos_args),
    )

    # NOTE: There is no cleanup counterpart env here on purpose: `uv pip
    # NOTE: compile` writes the output file whole, so a stale lock can
    # NOTE: never survive a successful run the way a stale dist can.
    state.conf.memory_seed_loaders[_ENV_NAME].append(
        MemoryLoader(
            base=[],
            description=(
                '[tox-lock] Compile a hash-pinned requirements.txt from '
                'pyproject.toml; pass extra `uv pip compile` arguments '
                'after `--`. For example, '
                '`tox run -e lock-deps -- --upgrade`.'
            ),
            deps=['uv'],
            commands_pre=[],
            commands=[shlex_join(lock_cmd)],
            commands_post=[],
            package='skip',
        ),
    )
