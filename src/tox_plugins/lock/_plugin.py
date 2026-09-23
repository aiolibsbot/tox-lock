"""A tox plugin providing a pre-configured dependency locking environment."""

from __future__ import annotations

import shlex
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
_CHECK_ENV_NAME = f'{_ENV_NAME}-check'
_SEEDED_ENV_NAMES = (_ENV_NAME, _CHECK_ENV_NAME)

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
)

# NOTE: Both defaults are relative, and stay relative: the lock env runs
# NOTE: in `change_dir`, which defaults to the tox root -- the same place
# NOTE: the config file naming them is read from.
_DEFAULT_LOCK_INPUTS = (Path('pyproject.toml'),)
_DEFAULT_LOCK_FILE = Path('requirements.txt')

# NOTE: Hash pinning is a default rather than a fixture of the command:
# NOTE: a project depending on a direct URL or an editable checkout
# NOTE: cannot generate hashes at all, and is entitled to say so
# NOTE: without also taking ownership of the rest of the command line.
_DEFAULT_LOCK_OPTIONS = ('--generate-hashes',)

# NOTE: Both envs install `uv` from the same setting on purpose. The
# NOTE: resolver is part of the lock's inputs as much as the sources
# NOTE: are -- two `uv` releases can pin the same requirements
# NOTE: differently -- so a check running a newer one than the machine
# NOTE: that wrote the lock reports drift that is not there. Pinning it
# NOTE: is the project's call; pinning it *twice*, once per env, is not
# NOTE: something the project should have to remember.
_DEFAULT_LOCK_UV = ('uv',)

# NOTE: Empty rather than a spelling of "whatever runs tox", which is
# NOTE: what tox falls back to on its own when the key is left unseeded.
# NOTE: Naming that fallback here would mean seeding `base_python` on
# NOTE: every project, and a seeded key is one the env section and `-x`
# NOTE: have to fight past rather than simply fill in.
_DEFAULT_LOCK_PYTHON: tuple[str, ...] = ()

# NOTE: `uv pip compile` seeds its resolution from the output file when
# NOTE: one is already there, leaving every pin that does not have to
# NOTE: move exactly where it is. The check recompiles into a copy of
# NOTE: the lock rather than into an empty file so that it reports
# NOTE: *drift* -- the lock no longer matching the sources it claims to
# NOTE: come from -- and not the mere existence of a newer release
# NOTE: upstream, which is what `-- --upgrade` is for.
_CHECK_SEED_SCRIPT = """
import pathlib, shutil, sys

lock_file, scratch_file = map(pathlib.Path, sys.argv[1:])
scratch_file.parent.mkdir(parents=True, exist_ok=True)
scratch_file.unlink(missing_ok=True)
if lock_file.is_file():
    shutil.copyfile(lock_file, scratch_file)
"""

# NOTE: Comment lines are left out of the comparison because `uv`
# NOTE: opens the file it writes with a header naming the command that
# NOTE: produced it -- `--output-file` included, which is the one
# NOTE: argument the check is obliged to change. The `# via ...`
# NOTE: annotations trailing each pin go the same way; they restate the
# NOTE: dependency graph the pins themselves encode.
#
# NOTE: The diff is printed over the same filtered lines rather than
# NOTE: over the files, so that what a reader is shown is exactly what
# NOTE: was compared -- a diff full of header and `# via` noise would
# NOTE: invite the conclusion that the check is tripping over comments
# NOTE: it in fact ignores. CI is usually the only place this ever
# NOTE: runs, and a log saying nothing but "out of date" sends whoever
# NOTE: reads it to recompile locally just to find out what moved.
_CHECK_COMPARE_SCRIPT = """
import difflib, pathlib, sys


def pins(path):
    return [
        line for line in path.read_text(encoding='utf-8').splitlines()
        if not line.lstrip().startswith('#')
    ]


scratch_file, lock_file = map(pathlib.Path, sys.argv[1:])
if not lock_file.is_file():
    sys.exit(f'{lock_file} does not exist -- run `tox run -e lock-deps`.')

locked, compiled = pins(lock_file), pins(scratch_file)
if locked == compiled:
    sys.exit(0)

for diff_line in difflib.unified_diff(
        locked,
        compiled,
        fromfile=f'{lock_file} (locked)',
        tofile=f'{lock_file} (recompiled)',
        lineterm='',
):
    print(diff_line, file=sys.stderr)
sys.exit(f'{lock_file} is out of date -- run `tox run -e lock-deps`.')
"""


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


def _lock_inputs(core_conf: ConfigSet) -> _c.Iterator[str]:
    """Render the configured requirement sources as command arguments.

    ``uv pip compile`` takes any number of them and compiles the union
    into one lock, which is how a project splitting its requirements
    across several ``*.in`` files produces a single pinned set. Keeping
    the setting singular would have made that project rewrite the whole
    command to add its second file -- the one thing the surrounding
    settings exist to avoid.

    :param core_conf: The core tox configuration set to read from.
    :yields: The requirement sources, one command argument at a time.
    """
    for lock_input in core_conf['lock_input']:
        yield str(lock_input)


def _lock_options(core_conf: ConfigSet) -> _c.Iterator[str]:
    """Split the configured lock options into command arguments.

    ``tox`` hands back a list holding one entry per line the user wrote,
    so an option and the value it takes -- ``--python-version 3.9`` --
    arrive glued into a single string. Passing that on unsplit would
    hand ``uv`` one argument it has never heard of, so each entry is
    parsed the way a shell would parse it; quoting works accordingly.

    :param core_conf: The core tox configuration set to read from.
    :yields: The lock options, one command argument at a time.
    """
    for option in core_conf['lock_options']:
        yield from shlex.split(option)


def _seeded_base_python(core_conf: ConfigSet) -> dict[str, list[str]]:
    """Render the configured lock interpreter as a seeded env setting.

    :param core_conf: The core tox configuration set to read from.
    :returns: The ``base_python`` seed, empty when none was configured.
    """
    lock_python = core_conf['lock_python']
    return {'base_python': list(lock_python)} if lock_python else {}


def _lock_args(state: State) -> tuple[str, ...]:
    """Read the arguments the lock command was handed after ``--``.

    :param state: The tox session state holding the positional args.
    :returns: The arguments ``uv pip compile`` will receive, as typed.
    """
    pos_args = state.conf.pos_args(to_path=None)
    return () if pos_args is None else pos_args


def _python_script_command(script: str, *args: str) -> Command:
    """Build a command running an in-process Python snippet.

    :param script: The Python source to run.
    :param args: The arguments to pass to the snippet.
    :returns: The command running the snippet under the env's Python.
    """
    return Command([*_PYTHON_CLI_OPTIONS, '-c', script, *args])


def _compile_command(
    core_conf: ConfigSet,
    output_file: Path,
    pos_args: tuple[str, ...],
) -> Command:
    """Build the ``uv pip compile`` invocation writing a given lock.

    :param core_conf: The core tox configuration set to read from.
    :param output_file: The path the compiled lock is written to.
    :param pos_args: The arguments the user passed after ``--``.
    :returns: The command compiling the configured sources.
    """
    # NOTE: The user options go first so that the settings with a core
    # NOTE: key of their own -- and the arguments passed after `--` --
    # NOTE: stay the last word on the subject. `uv` takes the last
    # NOTE: occurrence of a repeated option, so a stray `--output-file`
    # NOTE: in `lock_options` loses to `lock_file`, where it belongs.
    return Command([
        *_LOCK_COMMAND_PREFIX,
        *_lock_options(core_conf),
        '--output-file',
        str(output_file),
        *_lock_inputs(core_conf),
        *pos_args,
    ])


@impl
def tox_extend_envs() -> _c.Iterable[str]:
    """Declare the dependency locking environments.

    :returns: The names of the tox environments this plugin provides.
    """
    return _SEEDED_ENV_NAMES


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
    if env_conf.name not in _SEEDED_ENV_NAMES:
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

    The file names the lock command is built around are settable from
    the ``[tox]`` core section, so that a project keeping its lock
    somewhere other than ``./requirements.txt`` -- or compiling one out
    of a couple of ``requirements/*.in`` rather than ``pyproject.toml``
    -- does not have to restate the whole command to say so. Being core
    config, they are read through the config file's own loader, so
    ``{tox_root}`` and friends expand in them.

    :param core_conf: The core tox configuration set to read from.
    :param state: The tox session state to inject the envs into.
    """
    core_conf.add_config(
        'lock_input',
        of_type=list[Path],
        default=list(_DEFAULT_LOCK_INPUTS),
        desc='the requirements sources `tox-lock` compiles the lock from',
    )
    core_conf.add_config(
        'lock_file',
        of_type=Path,
        default=_DEFAULT_LOCK_FILE,
        desc='the lock file `tox-lock` compiles',
    )
    core_conf.add_config(
        'lock_uv',
        of_type=list[str],
        default=list(_DEFAULT_LOCK_UV),
        desc='the `uv` requirements the `tox-lock` envs are run with',
    )
    core_conf.add_config(
        'lock_python',
        of_type=list[str],
        default=list(_DEFAULT_LOCK_PYTHON),
        desc='the interpreter the `tox-lock` envs resolve the lock with',
    )
    core_conf.add_config(
        'lock_options',
        of_type=list[str],
        default=list(_DEFAULT_LOCK_OPTIONS),
        desc='the `uv pip compile` options `tox-lock` locks with',
    )

    lock_file = core_conf['lock_file']
    lock_uv = core_conf['lock_uv']
    # NOTE: The interpreter is an input to the lock in the same way the
    # NOTE: resolver is: `uv pip compile` resolves for the Python it runs
    # NOTE: under unless told otherwise, so the same sources compiled on
    # NOTE: 3.11 and on 3.13 legitimately differ -- and a check running
    # NOTE: one while the lock was written by the other reports drift
    # NOTE: that is not there. Which interpreter it should be is the
    # NOTE: project's call; saying it twice, once per env, is not.
    lock_python = _seeded_base_python(core_conf)
    lock_inputs = ', '.join(_lock_inputs(core_conf))
    pos_args = _lock_args(state)

    # NOTE: There is no cleanup counterpart env here on purpose: `uv pip
    # NOTE: compile` writes the output file whole, so a stale lock can
    # NOTE: never survive a successful run the way a stale dist can.
    state.conf.memory_seed_loaders[_ENV_NAME].append(
        _SeedLoader(
            base=[],
            description=(
                f'[tox-lock] Compile {lock_file} out of '
                f'{lock_inputs} using `uv pip compile '
                f'{" ".join(_lock_options(core_conf))}`; pass extra '
                f'arguments after `--`. For example, '
                f'`tox run -e {_ENV_NAME} -- --upgrade`.'
            ),
            **lock_python,
            deps=list(lock_uv),
            commands_pre=[],
            commands=[_compile_command(core_conf, lock_file, pos_args)],
            commands_post=[],
            package='skip',
        ),
    )

    # NOTE: The scratch lock goes under the session's own temp dir so
    # NOTE: that a check run leaves the work tree exactly as it found
    # NOTE: it -- the point of the env being to say whether the lock is
    # NOTE: stale, not to quietly fix it on the machine that asked.
    scratch_file = core_conf['temp_dir'] / _CHECK_ENV_NAME / lock_file.name
    state.conf.memory_seed_loaders[_CHECK_ENV_NAME].append(
        _SeedLoader(
            base=[],
            description=(
                f'[tox-lock] Check that {lock_file} is what compiling '
                f'{lock_inputs} produces, and fail if it is not, without '
                f'writing to it. Meant for CI; pass extra arguments after '
                f'`--`, as with `{_ENV_NAME}`.'
            ),
            **lock_python,
            deps=list(lock_uv),
            commands_pre=[
                _python_script_command(
                    _CHECK_SEED_SCRIPT,
                    str(lock_file),
                    str(scratch_file),
                ),
            ],
            commands=[
                _compile_command(core_conf, scratch_file, pos_args),
                _python_script_command(
                    _CHECK_COMPARE_SCRIPT,
                    str(scratch_file),
                    str(lock_file),
                ),
            ],
            commands_post=[],
            package='skip',
        ),
    )
