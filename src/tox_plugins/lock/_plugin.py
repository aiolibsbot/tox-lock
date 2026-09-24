"""A tox plugin providing a pre-configured dependency locking environment."""

from __future__ import annotations

import shlex
import typing as _t
from pathlib import Path

from tox.config.loader.memory import MemoryLoader
from tox.config.loader.replacer import ReplaceReference, replace
from tox.config.types import Command
from tox.plugin import impl
from tox.report import HandledError


if _t.TYPE_CHECKING:
    from collections import abc as _c  # noqa: WPS347

    from tox.config.loader.api import ConfigLoadArgs, Loader, Override
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

# NOTE: A mapping rather than a pair of keys because a project's
# NOTE: dependencies rarely come as one set: this very plugin's `tox.ini`
# NOTE: runs its tests, its builds and its metadata checks off three
# NOTE: disjoint ones. `uv pip compile` writes a single output per
# NOTE: invocation, so N sets means N invocations, and what has to be
# NOTE: configurable is the *pairing* -- which sources go into which
# NOTE: lock -- not two independent lists.
#
# NOTE: Keyed by the lock rather than by its sources because only the
# NOTE: lock is unique: one `requirements/base.in` legitimately feeds
# NOTE: both `base.txt` and `test.txt`, and a mapping keyed the other
# NOTE: way would silently drop one of them.
#
# NOTE: The default is relative, and stays relative: the lock envs run
# NOTE: in `change_dir`, which defaults to the tox root -- the same place
# NOTE: the config file naming them is read from.
_DEFAULT_LOCK_FILES = {Path('requirements.txt'): [Path('pyproject.toml')]}

# NOTE: Hash pinning is a default rather than a fixture of the command:
# NOTE: a project depending on a direct URL or an editable checkout
# NOTE: cannot generate hashes at all, and is entitled to say so
# NOTE: without also taking ownership of the rest of the command line.
_DEFAULT_LOCK_OPTIONS = ('--generate-hashes',)

# NOTE: `uv` records the command it was run with in a header comment at
# NOTE: the top of every lock it writes, so that whoever finds the file
# NOTE: later knows how to regenerate it. Left to itself it records the
# NOTE: invocation this plugin builds -- a `python -Werror -m uv pip
# NOTE: compile` line naming paths relative to wherever the env ran --
# NOTE: which is precisely the command nobody should run by hand: it
# NOTE: goes around the pinned `uv`, the passed-through index config
# NOTE: and the settings the rest of this module exists to centralise.
# NOTE: In the check env it is worse than useless, naming the scratch
# NOTE: file under the tox temp dir the check compiles into and then
# NOTE: throws away. The command that actually reproduces the lock is
# NOTE: the env, so that is what the header is made to say.
# NOTE: The one option this plugin refuses rather than yields. Every
# NOTE: other default here steps aside when a project names it -- that
# NOTE: is what a default is -- but `--output-file` is not a default,
# NOTE: it is the argument that tells the two envs apart: the writer
# NOTE: compiles into the lock, the checker into a scratch file it
# NOTE: throws away. A project naming it would point the *check* at the
# NOTE: real lock and so have it silently rewrite the very file it was
# NOTE: asked to confirm was already correct -- the check's one promise
# NOTE: being that it never writes. `uv` would reject the duplicate
# NOTE: anyway, naming an internal invocation nobody typed; refusing it
# NOTE: here instead says which setting to reach for. Both spellings
# NOTE: `uv` takes are covered, the short one included, whether or not
# NOTE: the value is glued on.
_OUTPUT_FILE_OPTION = '--output-file'
_OUTPUT_FILE_SHORT_OPTION = '-o'

_CUSTOM_COMPILE_COMMAND_OPTION = '--custom-compile-command'
_DEFAULT_CUSTOM_COMPILE_COMMAND = f'tox run -e {_ENV_NAME}'

# NOTE: Seeded as a *default* on both envs rather than settled by a
# NOTE: core key of its own: the resolver is one of the lock's inputs as
# NOTE: much as the sources are -- two `uv` releases can pin the same
# NOTE: requirements differently, so a check resolving with a newer one
# NOTE: than the machine that wrote the lock reports drift that is not
# NOTE: there. Which `uv` it should be is the project's call, and the
# NOTE: place it says so is `[testenv:lock-deps]`, from which the check
# NOTE: env inherits it. See `tox_add_env_config` for how.
_LOCK_UV = ('uv',)

# NOTE: `uv` is configured almost entirely through the environment --
# NOTE: `UV_INDEX`, `UV_INDEX_URL`, `UV_KEYRING_PROVIDER`, `UV_NATIVE_TLS`
# NOTE: and friends -- and `tox` passes none of it through: its own
# NOTE: defaults cover `PIP_*`, which is the wrong resolver. A project
# NOTE: locking against a private index therefore resolves against PyPI
# NOTE: instead, and either fails to find its own packages or, worse,
# NOTE: finds public ones under the same names. Globbed rather than
# NOTE: enumerated: `uv` gains variables release to release, and a list
# NOTE: written out here would silently stop covering them.
#
# NOTE: Unconditional, and not the default of the setting below, for
# NOTE: the same reason `PIP_*` is unconditional in tox: it is how the
# NOTE: resolver these envs are built around is configured at all, so a
# NOTE: project naming one more variable to pass is asking to add to
# NOTE: this, never to trade it away. `pass_env` is merged rather than
# NOTE: replaced by tox, so both sit alongside its defaults. This is the
# NOTE: one setting a project cannot move into `[testenv:lock-deps]`
# NOTE: instead: a section wins a key outright, so writing `pass_env`
# NOTE: there would take `UV_*` away along with everything else.
_LOCK_PASS_ENV = ('UV_*',)

# NOTE: Empty, because the variables a lock run needs beyond the
# NOTE: resolver's own are whatever a project's index happens to
# NOTE: authenticate with -- a token under a name nobody else uses.
_DEFAULT_LOCK_PASS_ENV: tuple[str, ...] = ()

# NOTE: The two envs are labelled apart because they are alternatives,
# NOTE: not a pipeline: one writes the lock, the other asserts that
# NOTE: writing it would change nothing. A label naming both selects a
# NOTE: pair whose second half is made vacuous by its first -- and
# NOTE: under `tox run-parallel` the writer is rewriting the very file
# NOTE: the checker is reading. Labels rather than bare env names so
# NOTE: that a project wiring either one into CI or into `depends`
# NOTE: names something it can rename -- in the env's own section,
# NOTE: which wins the key; labels are additive in tox, so one already
# NOTE: in use keeps whatever the project put there.
#
# NOTE: Owned rather than defaulted, unlike `uv` above: the check env
# NOTE: inherits `[testenv:lock-deps]`, and a label the project set on
# NOTE: the writer must *not* follow that inheritance -- that is the
# NOTE: same one-label-two-envs group this pair exists to avoid.
_LOCK_LABELS = ('lock',)
_CHECK_LABELS = ('lock-check',)

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
#
# NOTE: Every configured lock is compared by one invocation, rather
# NOTE: than one per lock, so that a project with several of them
# NOTE: learns about all the drift in a single CI run. `commands` stop
# NOTE: at the first failure, so a comparison per lock would report the
# NOTE: first stale one and say nothing about the rest -- turning one
# NOTE: red build into as many as there are locks behind it.
_CHECK_COMPARE_SCRIPT = """
import difflib, pathlib, sys


def pins(path):
    return [
        line for line in path.read_text(encoding='utf-8').splitlines()
        if not line.lstrip().startswith('#')
    ]


paths = [pathlib.Path(arg) for arg in sys.argv[1:]]
stale = []
for scratch_file, lock_file in zip(paths[::2], paths[1::2]):
    if not lock_file.is_file():
        print(f'{lock_file} does not exist.', file=sys.stderr)
        stale.append(lock_file)
        continue

    locked, compiled = pins(lock_file), pins(scratch_file)
    if locked == compiled:
        continue

    for diff_line in difflib.unified_diff(
            locked,
            compiled,
            fromfile=f'{lock_file} (locked)',
            tofile=f'{lock_file} (recompiled)',
            lineterm='',
    ):
        print(diff_line, file=sys.stderr)
    stale.append(lock_file)

if stale:
    sys.exit(
        f'{", ".join(map(str, stale))} '
        f'{"is" if len(stale) == 1 else "are"} out of date '
        f'-- run `tox run -e lock-deps`.'
    )
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


class _DefaultSeedLoader(_SeedLoader):
    """A seed whose values the writer env's own section may replace.

    The check env exists to answer one question -- would compiling the
    sources again change the lock -- and it can only answer it if it
    resolves the way the writer does. Both therefore read their
    resolver, their interpreter and their environment from one place:
    ``[testenv:lock-deps]``, which the check env takes as its
    :ref:`base <base>`. Inheritance is not transitive in tox, so
    ``[testenv]`` stays out of both regardless.

    That leaves a precedence question the plain seed cannot express.
    What this plugin *owns* -- the commands, the labels telling the two
    envs apart, the description -- has to outrank the inherited section,
    or a project setting ``commands`` on the writer would have the
    checker run them too. What it merely *defaults* -- which ``uv``,
    which interpreter, which variables to pass -- has to fall below it,
    or the inheritance would never be reached. Two loaders, ranked
    either side of the section, rather than one.
    """


def _lock_summary(lock_files: _c.Mapping[Path, _c.Sequence[Path]]) -> str:
    """Spell out which sources each configured lock is compiled from.

    :param lock_files: The configured locks, mapped to their sources.
    :returns: A human-readable rendering of the whole mapping.
    """
    return '; '.join(
        f'{lock_file} out of {", ".join(map(str, lock_inputs))}'
        for lock_file, lock_inputs in lock_files.items()
    )


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


def _names_option(args: _c.Iterable[str], option: str) -> bool:
    """Tell whether an option appears among the given arguments.

    Both spellings a user may reach for are recognised: the option and
    its value as two arguments, and the two glued with an ``=``.

    :param args: The command arguments to look through.
    :param option: The long option to look for, leading dashes included.
    :returns: :data:`True` if the option is named, :data:`False` if not.
    """
    return any(
        arg == option or arg.startswith(f'{option}=')
        for arg in args
    )


def _names_output_file(args: _c.Sequence[str]) -> bool:
    """Tell whether the output file option appears in some arguments.

    :param args: The command arguments to look through.
    :returns: :data:`True` if the option is named, :data:`False` if not.
    """
    return _names_option(args, _OUTPUT_FILE_OPTION) or any(
        arg.startswith(_OUTPUT_FILE_SHORT_OPTION) for arg in args
    )


def _reject_configured_output_file(
    user_options: _c.Sequence[str],
    pos_args: _c.Sequence[str],
) -> None:
    """Refuse a user-supplied output file, naming the setting for it.

    :param user_options: The options read out of ``lock_options``.
    :param pos_args: The arguments the user passed after ``--``.
    :raises HandledError: If either of them names the output file.
    """
    argument_sources = (
        (user_options, '`lock_options`'),
        (pos_args, 'the arguments after `--`'),
    )
    for args, source in argument_sources:
        if not _names_output_file(args):
            continue

        raise HandledError(
            f'`{_OUTPUT_FILE_OPTION}` is `tox-lock`\'s to set and cannot '
            f'come from {source}: it is what makes `{_CHECK_ENV_NAME}` a '
            f'check rather than a second writer, and pointing it at the '
            f'lock would have that env overwrite the very file it was '
            f'asked to confirm. Set the `lock_files` core setting instead.',
        )


def _custom_compile_command(user_args: _c.Sequence[str]) -> tuple[str, ...]:
    """Render the header comment seeded into the compiled lock.

    The seed steps aside entirely when the user names the option
    themselves, anywhere. ``uv`` refuses a repeated
    ``--custom-compile-command`` outright rather than taking the last
    one, so a default appended alongside a user's own would not lose
    quietly -- it would fail the run, which is the one thing a default
    must never do to a project that configured its way past it.

    :param user_args: The arguments the user contributed, in full.
    :returns: The option and its value, or nothing at all.
    """
    if _names_option(user_args, _CUSTOM_COMPILE_COMMAND_OPTION):
        return ()

    return (_CUSTOM_COMPILE_COMMAND_OPTION, _DEFAULT_CUSTOM_COMPILE_COMMAND)


def _compile_command(
    core_conf: ConfigSet,
    lock_inputs: _c.Sequence[Path],
    output_file: Path,
    pos_args: tuple[str, ...],
) -> Command:
    """Build the ``uv pip compile`` invocation writing a given lock.

    :param core_conf: The core tox configuration set to read from.
    :param lock_inputs: The requirement sources compiled into the lock.
    :param output_file: The path the compiled lock is written to.
    :param pos_args: The arguments the user passed after ``--``.
    :returns: The command compiling the configured sources.
    :raises HandledError: If the user named the output file themselves.
    """
    # NOTE: The user options go first so that the settings with a core
    # NOTE: key of their own -- and the arguments passed after `--` --
    # NOTE: come last, which is what `uv` wants for the options it lets
    # NOTE: repeat: `--upgrade-package`, `--extra`, `--constraint` and
    # NOTE: friends accumulate in the order they are given. The ones it
    # NOTE: does not let repeat it rejects outright rather than taking
    # NOTE: the last, so ordering cannot make a duplicate win and the
    # NOTE: plugin does not pretend otherwise: it owns `--output-file`,
    # NOTE: which is the argument that makes the check a check, and it
    # NOTE: withdraws its own header default the moment a project names
    # NOTE: one.
    user_options = list(_lock_options(core_conf))
    _reject_configured_output_file(user_options, pos_args)
    return Command([
        *_LOCK_COMMAND_PREFIX,
        *user_options,
        '--output-file',
        str(output_file),
        *map(str, lock_inputs),
        *pos_args,
        # NOTE: Trailing the user's own arguments rather than leading
        # NOTE: them, so that everything a project wrote reads in the
        # NOTE: order it wrote it. Nothing rides on the position: the
        # NOTE: seed is there only when no user argument claims the
        # NOTE: option, and would be an error rather than a loser if
        # NOTE: one did.
        *_custom_compile_command((*user_options, *pos_args)),
    ])


def _loader_rank(loader: Loader[object], env_name: str) -> int:
    """Say how strongly a loader's values should bind for an env.

    ``tox`` puts ``memory_seed_loaders`` in front of everything read out
    of a config file, which would have the plugin's defaults shadow the
    very sections a user wrote to change them. Ranking them explicitly
    settles that, and makes room for the check env to inherit the
    writer's section in between the two kinds of seed.

    :param loader: The loader being ranked.
    :param env_name: The name of the env whose config is being built.
    :returns: A sort key -- the lower it is, the stronger the loader.
    """
    if loader.section.name == env_name:
        return 0  # the env's own section: always the last word

    if isinstance(loader, _DefaultSeedLoader):
        return 3  # a plugin default the inherited section may replace

    if isinstance(loader, _SeedLoader):
        return 1  # what the plugin owns outright

    return 2  # an inherited section, `[testenv:lock-deps]` in practice


@impl
def tox_extend_envs() -> _c.Iterable[str]:
    """Declare the dependency locking environments.

    :returns: The names of the tox environments this plugin provides.
    """
    return _SEEDED_ENV_NAMES


@impl
def tox_add_env_config(env_conf: EnvConfigSet, state: State) -> None:
    """Let the user's own settings override the plugin defaults.

    Three separate ways of saying "not that, this" have to be honoured:

    * a ``[testenv:lock-deps]`` / ``[env.lock-deps]`` section -- tox puts
      ``memory_seed_loaders`` in front of the loaders reading it, so the
      seeded defaults would shadow it; ranking the loaders explicitly
      settles that, see :func:`_loader_rank`. The seeded ``base``
      still keeps the ``[testenv]`` base section out.
    * that same writer section read as the check env's ``base`` -- which
      is why the ranking has to be finer than "the plugin last": what
      the plugin owns outranks the inherited section, what it merely
      defaults falls below it.
    * a ``-x`` / ``TOX_OVERRIDE`` override -- carried by the loader of
      the section it names, of which this env has none unless the
      project happens to declare one anyway. An override aimed at the
      writer env is *not* inherited: it overrides a loader, and the
      check env inherits a section.

    :param env_conf: The configuration set of the env being built.
    :param state: The tox session state holding the override map.
    """
    if env_conf.name not in _SEEDED_ENV_NAMES:
        return

    # NOTE: `list.sort()` is stable, so the loaders keep their relative
    # NOTE: order within each of the ranks.
    env_conf.loaders.sort(
        key=lambda loader: _loader_rank(loader, env_conf.name),
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
        'lock_files',
        of_type=dict[Path, list[Path]],
        default=dict(_DEFAULT_LOCK_FILES),
        desc='the locks `tox-lock` compiles, each mapped to its sources',
    )
    core_conf.add_config(
        'lock_pass_env',
        of_type=list[str],
        default=list(_DEFAULT_LOCK_PASS_ENV),
        desc='the extra environment variables the `tox-lock` envs pass through',
    )
    core_conf.add_config(
        'lock_options',
        of_type=list[str],
        default=list(_DEFAULT_LOCK_OPTIONS),
        desc='the `uv pip compile` options `tox-lock` locks with',
    )

    lock_files = core_conf['lock_files']
    if not lock_files:
        raise HandledError(
            '`lock_files` names no lock at all, which would leave '
            f'`{_ENV_NAME}` compiling nothing and `{_CHECK_ENV_NAME}` '
            'passing without having checked anything. A project that '
            'wants neither env drops `tox-lock` from its `requires` '
            'instead.',
        )

    lock_pass_env = [*_LOCK_PASS_ENV, *core_conf['lock_pass_env']]
    lock_summary = _lock_summary(lock_files)
    pos_args = _lock_args(state)

    # NOTE: There is no cleanup counterpart env here on purpose: `uv pip
    # NOTE: compile` writes the output file whole, so a stale lock can
    # NOTE: never survive a successful run the way a stale dist can.
    state.conf.memory_seed_loaders[_ENV_NAME].append(
        _SeedLoader(
            base=[],
            description=(
                f'[tox-lock] Compile {lock_summary} using `uv pip compile '
                f'{" ".join(_lock_options(core_conf))}`; pass extra '
                f'arguments after `--`. For example, '
                f'`tox run -e {_ENV_NAME} -- --upgrade`.'
            ),
            labels=list(_LOCK_LABELS),
            pass_env=list(lock_pass_env),
            deps=list(_LOCK_UV),
            commands_pre=[],
            commands=[
                _compile_command(core_conf, lock_inputs, lock_file, pos_args)
                for lock_file, lock_inputs in lock_files.items()
            ],
            commands_post=[],
            package='skip',
        ),
    )

    # NOTE: The scratch locks go under the session's own temp dir so
    # NOTE: that a check run leaves the work tree exactly as it found
    # NOTE: it -- the point of the env being to say whether the locks
    # NOTE: are stale, not to quietly fix them on the machine that
    # NOTE: asked. One numbered directory each, rather than the lock's
    # NOTE: bare file name, because two locks in different directories
    # NOTE: may well share one: `requirements/base.txt` next to
    # NOTE: `constraints/base.txt` would otherwise have the second
    # NOTE: compile overwrite the first's scratch and both comparisons
    # NOTE: read the same file.
    #
    # NOTE: The lock's own file name is kept rather than replaced by
    # NOTE: something tidier, because `uv` reads the *format* off it:
    # NOTE: an output named `pylock.toml` or `pylock.<name>.toml` is
    # NOTE: written as a PEP 751 lock, anything else as a
    # NOTE: `requirements.txt` one. A scratch named `lock.txt` would
    # NOTE: therefore have the check compile a different format from
    # NOTE: the one the writer produced, and the comparison would
    # NOTE: report every line of a perfectly current lock as drift.
    # NOTE: That inference is also why this plugin needs no setting for
    # NOTE: the format: naming the lock picks it.
    scratch_root = core_conf['temp_dir'] / _CHECK_ENV_NAME
    scratch_files = [
        scratch_root / str(lock_index) / lock_file.name
        for lock_index, lock_file in enumerate(lock_files)
    ]
    # NOTE: The check env takes `[testenv:lock-deps]` as its base so
    # NOTE: that a project pinning the resolver, naming an interpreter
    # NOTE: or passing a token writes it once, on the env it thinks of
    # NOTE: as "the lock env", and the check follows. Both have to
    # NOTE: resolve alike or the check reports its own configuration as
    # NOTE: drift in the project's lock. `base` is not transitive, so
    # NOTE: this inherits the section and not `[testenv]` behind it.
    #
    # NOTE: Named without a section prefix because that is the one
    # NOTE: spelling both config formats read: `tox.ini` takes the bare
    # NOTE: env name as readily as `testenv:lock-deps`, while
    # NOTE: `tox.toml` resolves nothing else -- neither `env.lock-deps`
    # NOTE: nor the ini spelling, and silently, without an error to say
    # NOTE: the base went unread.
    state.conf.memory_seed_loaders[_CHECK_ENV_NAME].append(
        _SeedLoader(
            base=[_ENV_NAME],
            description=(
                f'[tox-lock] Check that every lock is what compiling its '
                f'sources produces -- {lock_summary} -- and fail if it is '
                f'not, without writing to it. Meant for CI; pass extra '
                f'arguments after `--`, as with `{_ENV_NAME}`.'
            ),
            labels=list(_CHECK_LABELS),
            commands_pre=[
                _python_script_command(
                    _CHECK_SEED_SCRIPT,
                    str(lock_file),
                    str(scratch_file),
                )
                for lock_file, scratch_file in zip(
                    lock_files,
                    scratch_files,
                    strict=True,
                )
            ],
            commands=[
                *(
                    _compile_command(
                        core_conf,
                        lock_inputs,
                        scratch_file,
                        pos_args,
                    )
                    for (_, lock_inputs), scratch_file
                    in zip(lock_files.items(), scratch_files, strict=True)
                ),
                _python_script_command(
                    _CHECK_COMPARE_SCRIPT,
                    *(
                        str(path)
                        for lock_file, scratch_file
                        in zip(lock_files, scratch_files, strict=True)
                        for path in (scratch_file, lock_file)
                    ),
                ),
            ],
            commands_post=[],
            package='skip',
        ),
    )

    # NOTE: Ranked below the inherited section rather than alongside the
    # NOTE: settings above it -- see `_DefaultSeedLoader`. These are the
    # NOTE: defaults a project replaces by writing `[testenv:lock-deps]`;
    # NOTE: everything in the loader above is the plugin's own doing and
    # NOTE: must not follow that inheritance.
    state.conf.memory_seed_loaders[_CHECK_ENV_NAME].append(
        _DefaultSeedLoader(
            pass_env=list(lock_pass_env),
            deps=list(_LOCK_UV),
        ),
    )
