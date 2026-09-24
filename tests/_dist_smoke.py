"""Run the plugin out of an installed dist rather than the work tree.

``tests/_dist_contents.py`` proves a dist *carries* every module, and
the suite proves those modules behave -- but it proves it against an
editable install, where the work tree is the package. Nothing between
the two says that installing a dist yields a working plugin: that the
``tox`` entry point resolves from the metadata a build wrote, that a
PEP 420 namespace subpackage imports out of ``site-packages`` next to
whatever else claims ``tox_plugins``, that the hook fires and seeds its
two envs, and that the helper scripts ``lock-deps-check`` runs *by
path* are found at a path under the installation rather than under a
checkout that a user will not have.

Each dist is installed into a throwaway virtual environment of its own,
with its dependencies resolved from its own metadata rather than from
this project's locks -- the declared floor being enough to run under is
part of what an installed dist has to get right.

Where those environments are built is handed in rather than left to
``TMPDIR``: two of them with ``tox`` inside come to a few hundred
megabytes, and the default is a memory-backed filesystem on more than
one Linux distribution -- which fails as a disk full rather than as
anything to do with the dist under test.

Kept out of the shipped package because it checks the packaging rather
than doing any of the plugin's work, and named without the ``_test``
suffix so that ``pytest`` imports it for the tests beside it rather
than collecting it as one.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import typing as _t
import venv
from pathlib import Path


if _t.TYPE_CHECKING:
    from collections import abc as _c


class _Runner(_t.Protocol):
    """How this check reaches a subprocess, injected for the tests."""

    def __call__(
        self,
        command: _c.Sequence[str],
        cwd: Path | None = None,
    ) -> str:
        """Run a command and hand back its standard output.

        :param command: The argument vector to run.
        :param cwd: The directory to run it in.
        :returns: Everything it wrote to its standard output.
        """


_DIST_PATTERNS = ('*.whl', '*.tar.gz')

_SEEDED_ENV_NAMES = ('lock-deps', 'lock-deps-check')
_CHECK_ENV_NAME = _SEEDED_ENV_NAMES[-1]

# NOTE: Naming the plugin in `requires` rather than relying on it being
# NOTE: installed, because that is what the README tells a project to
# NOTE: write -- and an env no section declares falls back to
# NOTE: `[testenv]` instead of failing, so a demo project that left it
# NOTE: out would list two envs that are not the plugin's and pass.
_DEMO_FILES = {
    'tox.ini': '[tox]\nrequires =\n  tox-lock\n',
    'pyproject.toml': (
        '[project]\nname = "demo-pkg"\nversion = "1.0.0"\n'
        'dependencies = []\n'
    ),
}


def _write_demo_project(demo_dir: Path) -> Path:
    """Lay down the smallest project the seeded envs apply to.

    :param demo_dir: Where to write it.
    :returns: That same directory, now populated.
    """
    demo_dir.mkdir(parents=True, exist_ok=True)
    for name, contents in _DEMO_FILES.items():
        (demo_dir / name).write_text(contents, encoding='utf-8')

    return demo_dir


def _create_venv(venv_dir: Path) -> Path:
    """Build an empty virtual environment with a working ``pip``.

    :param venv_dir: Where to build it.
    :returns: The interpreter inside it.
    """
    builder = venv.EnvBuilder(clear=True, with_pip=True)
    context = builder.ensure_directories(venv_dir)
    builder.create(venv_dir)
    # NOTE: `EnvBuilder` hands its context back as a
    # NOTE: `SimpleNamespace`, whose attributes `mypy` can only see
    # NOTE: as `Any`. Asking it anyway rather than rebuilding
    # NOTE: `bin/python` against `Scripts/python.exe` here is the
    # NOTE: point: that spelling is `venv`'s to know, and a copy of
    # NOTE: it is a second thing to keep in step with it.
    return Path(str(context.env_exe))  # type: ignore[misc]


def _run(command: _c.Sequence[str], cwd: Path | None = None) -> str:
    """Run a command to completion, refusing a non-zero exit.

    :param command: The argument vector to run.
    :param cwd: The directory to run it in, the current one if unset.
    :raises subprocess.CalledProcessError: On a non-zero exit.
    :returns: Everything it wrote to its standard output.
    """
    return subprocess.run(  # noqa: S603
        command,
        capture_output=True,
        check=True,
        cwd=cwd,
        encoding='utf-8',
        text=True,
    ).stdout


def _script_paths(config_output: str) -> frozenset[Path]:
    """Pick out the scripts a rendered env config runs by path.

    Derived from the rendering rather than named here, so that a script
    the plugin grows later is checked without anybody remembering to
    add it -- and so that a plugin which stopped running any at all
    fails this check instead of passing it vacuously.

    :param config_output: The output of ``tox config`` for one env.
    :returns: Every argument in it that looks like a Python file.
    """
    return frozenset(
        Path(token)
        for line in config_output.splitlines()
        for token in line.split()
        if token.endswith('.py')
    )


def _missing_envs(listed: str) -> _c.Sequence[str]:
    """Tell which of the seeded envs an install does not offer.

    :param listed: The output of ``tox list --no-desc``.
    :returns: The names that are not there, in the order seeded.
    """
    listed_envs = {line.strip() for line in listed.splitlines()}
    return [name for name in _SEEDED_ENV_NAMES if name not in listed_envs]


def _script_complaints(
    dist_file: Path,
    venv_dir: Path,
    config_output: str,
) -> _c.Iterator[str]:
    """Spell out what a seeded env fails to reach.

    :param dist_file: The dist that was installed, named in complaints.
    :param venv_dir: The environment it was installed into.
    :param config_output: The output of ``tox config`` for the check env.
    :yields: The complaint lines, none at all if every script is there.
    """
    scripts = _script_paths(config_output)
    if not scripts:
        yield (
            f'{dist_file} seeds {_CHECK_ENV_NAME}, but its commands run '
            'no script by path, so this check asserted nothing.'
        )
        return

    installed_root = venv_dir.resolve()
    for script in sorted(scripts):
        resolved = script.resolve()
        if not resolved.is_file():
            yield f'{dist_file} runs {script}, which is not there.'
        elif not resolved.is_relative_to(installed_root):
            yield (
                f'{dist_file} runs {script}, which is outside the '
                f'environment it was installed into.'
            )


def _probe(
    dist_file: Path,
    python: Path,
    venv_dir: Path,
    demo_dir: Path,
    run: _Runner,
) -> _c.Iterator[str]:
    """Install one dist and drive ``tox`` with it.

    :param dist_file: The wheel or sdist to install.
    :param python: The interpreter of the environment to install into.
    :param venv_dir: That environment, for locating what it runs.
    :param demo_dir: The project to run ``tox`` in.
    :param run: How to run a command, injected for the tests.
    :yields: The complaint lines, none at all if the install works.
    """
    run((str(python), '-Im', 'pip', 'install', '--quiet', str(dist_file)))
    listed = run((str(python), '-Im', 'tox', 'list', '--no-desc'), demo_dir)
    missing = _missing_envs(listed)
    if missing:
        # NOTE: Returning rather than going on to render the env:
        # NOTE: asking `tox config` about a name nothing declares is a
        # NOTE: second, noisier failure that arrives first and buries
        # NOTE: the one sentence worth reading.
        yield (
            f'{dist_file} installs, but `tox list` does not offer '
            f'{", ".join(missing)}.'
        )
        return

    config_output = run(
        (str(python), '-Im', 'tox', 'config', '-e', _CHECK_ENV_NAME),
        demo_dir,
    )
    yield from _script_complaints(dist_file, venv_dir, config_output)


def _dists(dist_dir: Path) -> _c.Iterator[tuple[Path | None, str]]:
    """Find the dists to install, complaining about a pattern with none.

    :param dist_dir: The directory the built dists were written to.
    :yields: Each dist found, or ``None`` with a complaint about it.
    """
    for pattern in _DIST_PATTERNS:
        dist_files = sorted(dist_dir.glob(pattern))
        if not dist_files:
            yield None, f'{dist_dir} holds no {pattern} to install.'
            continue

        for dist_file in dist_files:
            yield dist_file, ''


def main(args: _c.Sequence[str]) -> int:
    """Check that every built dist works once installed.

    :param args: The directory of the dists and one to work under.
    :returns: The exit code to leave with.
    """
    dist_dir, scratch_dir = map(Path, args)
    scratch_dir.mkdir(parents=True, exist_ok=True)
    report: list[str] = []
    for dist_file, complaint in _dists(dist_dir):
        if dist_file is None:
            report.append(complaint)
            continue

        with tempfile.TemporaryDirectory(dir=scratch_dir) as work_dir:
            root = Path(work_dir)
            venv_dir = root / 'venv'
            report.extend(
                _probe(
                    dist_file,
                    _create_venv(venv_dir),
                    venv_dir,
                    _write_demo_project(root / 'demo'),
                    _run,
                ),
            )

    if not report:
        return 0

    sys.stderr.writelines(f'{line}\n' for line in report)
    sys.stderr.write(
        'A dist that installs without seeding its envs fails in every '
        'project that depends on it and in none of the checks that run '
        'against this work tree -- rebuild with '
        '`tox run -e build-dists` and check what the packaging config '
        'now declares.\n',
    )
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
