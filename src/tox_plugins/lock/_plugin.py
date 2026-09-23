"""A tox plugin providing a pre-configured dependency locking environment."""

from __future__ import annotations

import typing as _t
from pathlib import Path

from tox.config.loader.memory import MemoryLoader
from tox.config.loader.replacer import ReplaceReference, replace
from tox.config.types import Command
from tox.plugin import impl


if _t.TYPE_CHECKING:
    from collections import abc as _c  # noqa: WPS347

    from tox.config.loader.api import ConfigLoadArgs, Override
    from tox.config.main import Config
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

_LOCK_COMMAND_PREFIX = (
    *_PYTHON_CLI_OPTIONS,
    '-m',
    'uv',
    'pip',
    'compile',
    '--generate-hashes',
)

# NOTE: Both defaults are relative, and stay relative: the lock env runs
# NOTE: in `change_dir`, which defaults to the tox root -- the same place
# NOTE: the config file naming them is read from.
_DEFAULT_LOCK_INPUT = Path('pyproject.toml')
_DEFAULT_LOCK_FILE = Path('requirements.txt')


class _NoSectionReference(ReplaceReference):
    """A resolver for substitutions naming a config section.

    Stands in for the config file's own resolver when the project has no
    core section for one to be built from.
    """

    def __call__(
        self,
        value: str,  # noqa: ARG002  # pylint: disable=unused-argument
        conf_args: ConfigLoadArgs,  # noqa: ARG002  # pylint: disable=unused-argument
    ) -> None:
        """Decline to resolve the reference.

        :param value: The reference to resolve (unused).
        :param conf_args: The config load arguments (unused).
        :returns: :data:`None` -- tox's cue to leave the text as it is.
        """
        return None


class _SeedLoader(MemoryLoader):
    """A plugin-default loader that still answers to ``-x``.

    ``tox`` hands its override map to every loader it builds out of a
    config file, but extends ``memory_seed_loaders`` with whatever a
    plugin put there, untouched. The env seeded here exists precisely so
    that nobody has to write a ``[testenv:lock-deps]`` section for it --
    so there is no config-file loader to carry the override, and
    ``-x testenv:lock-deps.deps=uv==0.9.2`` lands nowhere. It is dropped
    in silence: ``tox`` exits zero having used the default.
    """

    def add_overrides(self, overrides: _c.Iterable[Override]) -> None:
        """Make this loader honour the given command-line overrides.

        :param overrides: The overrides aimed at the env being seeded.
        """
        for override in overrides:
            self.overrides.setdefault(override.key, []).append(override)

    def substitute(
        self,
        value: str,
        conf: Config,
        args: ConfigLoadArgs,
    ) -> str:
        """Expand the substitutions in an override's raw value.

        An override arrives as the string the user typed, so ``tox``
        runs it through the receiving loader before converting it --
        which is how ``{env:LOCK_PIN}`` and ``{[testenv]deps}`` resolve
        in one. :class:`~tox.config.loader.memory.MemoryLoader` seeds
        ready-made objects and so implements no expansion at all;
        inheriting that would turn every substitution in an override
        into a :exc:`NotImplementedError`. Deferring to the config
        file's own loader gives the value the same treatment it would
        have gotten had the user written the section by hand.

        :param value: The raw string to expand.
        :param conf: The configuration object of this tox session.
        :param args: The config load arguments.
        :returns: The value with every substitution resolved.
        """
        core_loaders = conf.core.loaders
        if core_loaders:
            return core_loaders[0].substitute(value, conf, args)

        # NOTE: A config file with no core section -- a `tox.ini` that
        # NOTE: opens straight on `[testenv]`, say -- leaves nothing to
        # NOTE: defer to. Everything resolvable from the session alone
        # NOTE: (`{env:...}`, `{posargs}`, `{/}`) still is; only a
        # NOTE: reference to a config section comes back verbatim,
        # NOTE: which is what tox does with one it cannot resolve.
        return replace(conf, _NoSectionReference(), value, args)


def _lock_args(state: State) -> tuple[str, ...]:
    """Read the arguments the lock command was handed after ``--``.

    :param state: The tox session state holding the positional args.
    :returns: The arguments ``uv pip compile`` will receive, as typed.
    """
    pos_args = state.conf.pos_args(to_path=None)
    return () if pos_args is None else pos_args


@impl
def tox_extend_envs() -> _c.Iterable[str]:
    """Declare the dependency locking environment.

    :returns: The names of the tox environments this plugin provides.
    """
    return (_ENV_NAME,)


@impl
def tox_add_env_config(env_conf: EnvConfigSet, state: State) -> None:
    """Let the user's own settings override the plugin defaults.

    Two separate ways of saying "not that, this" have to be honoured:

    * a ``[testenv:lock-deps]`` / ``[env.lock-deps]`` section -- tox puts
      ``memory_seed_loaders`` in front of the loaders reading it, so the
      seeded defaults would shadow it; sorting the section's own loader
      back to the front settles that. The seeded ``base=[]`` still keeps
      the ``[testenv]`` base section out.
    * a ``-x`` / ``TOX_OVERRIDE`` override -- carried by the loader of
      the section it names, of which this env has none unless the
      project happens to declare one anyway.

    :param env_conf: The configuration set of the env being built.
    :param state: The tox session state holding the override map.
    """
    if env_conf.name != _ENV_NAME:
        return

    # NOTE: `list.sort()` is stable, so the loaders keep their relative
    # NOTE: order within the user-section and the plugin-default groups.
    env_conf.loaders.sort(
        key=lambda loader: loader.section.name != env_conf.name,
    )

    # NOTE: The override map is keyed by the section key of whichever
    # NOTE: config format the project uses -- `testenv:lock-deps` for
    # NOTE: `tox.ini`, `tool.tox.env.lock-deps` for `pyproject.toml`.
    # NOTE: Spelling one of those out here would quietly ignore the
    # NOTE: overrides of every project written in the other one, so the
    # NOTE: key is taken from the very config set tox is assembling.
    overrides = state.conf.overrides.get(
        env_conf._section.key,  # noqa: SLF001  # pylint: disable=protected-access
        [],
    )
    for loader in env_conf.loaders:
        if isinstance(loader, _SeedLoader):
            loader.add_overrides(overrides)


@impl
def tox_add_core_config(core_conf: ConfigSet, state: State) -> None:
    """Inject default configuration for the locking environment.

    The two file names the lock command is built around are settable
    from the ``[tox]`` core section, so that a project keeping its lock
    somewhere other than ``./requirements.txt`` -- or compiling one out
    of a ``requirements.in`` rather than ``pyproject.toml`` -- does not
    have to restate the whole command to say so. Being core config, both
    are read through the config file's own loader, so ``{tox_root}`` and
    friends expand in them.

    :param core_conf: The core tox configuration set to read from.
    :param state: The tox session state to inject the environment into.
    """
    core_conf.add_config(
        'lock_input',
        of_type=Path,
        default=_DEFAULT_LOCK_INPUT,
        desc='the requirements source `tox-lock` compiles the lock from',
    )
    core_conf.add_config(
        'lock_file',
        of_type=Path,
        default=_DEFAULT_LOCK_FILE,
        desc='the lock file `tox-lock` compiles, hash-pinned',
    )

    lock_cmd = Command([
        *_LOCK_COMMAND_PREFIX,
        '--output-file',
        str(core_conf['lock_file']),
        str(core_conf['lock_input']),
        *_lock_args(state),
    ])

    # NOTE: There is no cleanup counterpart env here on purpose: `uv pip
    # NOTE: compile` writes the output file whole, so a stale lock can
    # NOTE: never survive a successful run the way a stale dist can.
    state.conf.memory_seed_loaders[_ENV_NAME].append(
        _SeedLoader(
            base=[],
            description=(
                f'[tox-lock] Compile the hash-pinned '
                f'{core_conf["lock_file"]} out of '
                f'{core_conf["lock_input"]}; pass extra `uv pip compile` '
                f'arguments after `--`. For example, '
                f'`tox run -e lock-deps -- --upgrade`.'
            ),
            deps=['uv'],
            commands_pre=[],
            commands=[lock_cmd],
            commands_post=[],
            package='skip',
        ),
    )
