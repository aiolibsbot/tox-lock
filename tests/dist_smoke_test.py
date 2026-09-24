"""Behavioral tests for the installed-dist smoke check."""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import typing as _t
from pathlib import Path

import pytest

import _dist_smoke


if _t.TYPE_CHECKING:
    from collections import abc as _c


_CHECK_ENV = 'lock-deps-check'
_DIST_NAMES = ('demo.whl', 'demo.tar.gz')
_LISTED = f'py\nlock-deps\n{_CHECK_ENV}\n'


class _CheckResult(_t.NamedTuple):
    """What running the check leaves behind."""

    returncode: int
    stderr: str


class _FakeRun:
    """A stand-in for running a command, answering from a script."""

    def __init__(self, listed: str, config_output: str) -> None:
        """Record what ``tox`` should be made to say.

        :param listed: What ``tox list`` answers.
        :param config_output: What ``tox config`` answers.
        """
        self._answers = {'list': listed, 'config': config_output}
        self.commands: list[tuple[str, ...]] = []

    def __call__(
        self,
        command: _c.Sequence[str],
        cwd: Path | None = None,  # noqa: ARG002
    ) -> str:
        """Answer as the command it was handed would.

        :param command: The argument vector that would have been run.
        :param cwd: Where it would have run, which nothing here reads.
        :returns: The canned output for that command.
        """
        self.commands.append(tuple(command))
        return next(
            (
                answer
                for verb, answer in self._answers.items()
                if verb in command
            ),
            '',
        )


def _make_dists(dist_dir: Path, *names: str) -> Path:
    """Lay down empty files standing in for built dists.

    :param dist_dir: The directory to write them into.
    :param names: The dist file names to create.
    :returns: That same directory.
    """
    dist_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        (dist_dir / name).write_bytes(b'')

    return dist_dir


def _installed_script(venv_dir: Path, name: str) -> Path:
    """Put a helper script where an installed plugin would keep one.

    :param venv_dir: The environment the dist was installed into.
    :param name: The script's file name.
    :returns: The path it was written to.
    """
    package_dir = venv_dir / 'lib' / 'site-packages' / 'tox_plugins' / 'lock'
    package_dir.mkdir(parents=True, exist_ok=True)
    script = package_dir / name
    script.write_text('', encoding='utf-8')
    return script


def _run_check(dist_dir: Path) -> _CheckResult:
    """Run the check over a directory and capture its complaints.

    :param dist_dir: The directory of dists to hand it.
    :returns: Its exit code and everything it wrote to standard error.
    """
    stderr = io.StringIO()
    scratch_dir = dist_dir.parent / 'scratch'
    with contextlib.redirect_stderr(stderr):
        returncode = _dist_smoke.main([str(dist_dir), str(scratch_dir)])

    return _CheckResult(returncode, stderr.getvalue())


def test_the_demo_project_names_the_plugin_it_needs(tmp_path: Path) -> None:
    """Check that the throwaway project requires the plugin by name.

    An env no section declares falls back to ``[testenv]`` rather than
    failing, so a demo project that did not name the plugin would list
    two envs that are not the plugin's and pass.

    :param tmp_path: Pytest's per-test directory fixture.
    """
    demo_dir = _dist_smoke._write_demo_project(tmp_path / 'demo')  # noqa: SLF001

    assert 'tox-lock' in (demo_dir / 'tox.ini').read_text(encoding='utf-8')
    assert (demo_dir / 'pyproject.toml').is_file()


def test_a_created_venv_has_an_interpreter(tmp_path: Path) -> None:
    """Check that the environment factory hands back a usable Python.

    :param tmp_path: Pytest's per-test directory fixture.
    """
    python = _dist_smoke._create_venv(tmp_path / 'venv')  # noqa: SLF001

    assert python.is_file()


def test_a_command_answers_with_its_output() -> None:
    """Check that the runner hands back what a command printed."""
    printed = _dist_smoke._run((sys.executable, '-Ic', 'print("hi")'))  # noqa: SLF001

    assert printed.strip() == 'hi'


def test_a_failing_command_is_refused() -> None:
    """Check that the runner raises rather than returning quietly."""
    with pytest.raises(subprocess.CalledProcessError):
        _dist_smoke._run((sys.executable, '-Ic', 'raise SystemExit(3)'))  # noqa: SLF001


def test_an_installed_dist_that_seeds_its_envs_passes(tmp_path: Path) -> None:
    """Check that a working install draws no complaint.

    :param tmp_path: Pytest's per-test directory fixture.
    """
    venv_dir = tmp_path / 'venv'
    script = _installed_script(venv_dir, '_check_seed.py')
    fake_run = _FakeRun(_LISTED, f'commands = python {script}\n')

    complaints = list(
        _dist_smoke._probe(  # noqa: SLF001
            tmp_path / 'demo.whl',
            Path(sys.executable),
            venv_dir,
            tmp_path / 'demo',
            fake_run,
        ),
    )

    assert not complaints
    assert any('install' in command for command in fake_run.commands[0])


def test_an_install_that_seeds_no_envs_is_caught(tmp_path: Path) -> None:
    """Check that a dist whose hook never fires is named, and only once.

    Rendering the check env is skipped once the envs are known to be
    missing: asking ``tox config`` about a name nothing declares fails
    on its own terms, noisily, and arrives before the one sentence
    worth reading.

    :param tmp_path: Pytest's per-test directory fixture.
    """
    fake_run = _FakeRun('py\n', 'commands = python x.py\n')

    complaints = list(
        _dist_smoke._probe(  # noqa: SLF001
            tmp_path / 'demo.whl',
            Path(sys.executable),
            tmp_path / 'venv',
            tmp_path / 'demo',
            fake_run,
        ),
    )

    assert len(complaints) == 1
    assert 'lock-deps' in complaints[0]
    assert not any('config' in command for command in fake_run.commands)


def test_an_env_running_no_script_is_caught(tmp_path: Path) -> None:
    """Check that a rendered config with no script fails rather than passes.

    :param tmp_path: Pytest's per-test directory fixture.
    """
    complaints = list(
        _dist_smoke._script_complaints(  # noqa: SLF001
            tmp_path / 'demo.whl',
            tmp_path / 'venv',
            'commands = python -m uv pip compile\n',
        ),
    )

    assert len(complaints) == 1
    assert 'asserted nothing' in complaints[0]


def test_a_script_the_install_does_not_carry_is_caught(tmp_path: Path) -> None:
    """Check that a command pointing at a missing script is named.

    :param tmp_path: Pytest's per-test directory fixture.
    """
    missing = tmp_path / 'venv' / 'gone.py'

    complaints = list(
        _dist_smoke._script_complaints(  # noqa: SLF001
            tmp_path / 'demo.whl',
            tmp_path / 'venv',
            f'commands = python {missing}\n',
        ),
    )

    assert len(complaints) == 1
    assert 'not there' in complaints[0]


def test_a_script_outside_the_install_is_caught(tmp_path: Path) -> None:
    """Check that a script reached in the work tree rather than the install.

    This is the failure the check exists for: the plugin locates its
    helpers relative to its own ``__file__``, and every other env here
    runs against an editable install where that resolves into the
    checkout a user will not have.

    :param tmp_path: Pytest's per-test directory fixture.
    """
    venv_dir = tmp_path / 'venv'
    venv_dir.mkdir()
    elsewhere = tmp_path / 'work-tree' / '_check_seed.py'
    elsewhere.parent.mkdir()
    elsewhere.write_text('', encoding='utf-8')

    complaints = list(
        _dist_smoke._script_complaints(  # noqa: SLF001
            tmp_path / 'demo.whl',
            venv_dir,
            f'commands = python {elsewhere}\n',
        ),
    )

    assert len(complaints) == 1
    assert 'outside the environment' in complaints[0]


def test_a_missing_dist_is_reported(tmp_path: Path) -> None:
    """Check that a directory holding no wheel is a failure.

    :param tmp_path: Pytest's per-test directory fixture.
    """
    result = _run_check(_make_dists(tmp_path / 'dist'))

    assert result.returncode == 1
    assert 'no *.whl' in result.stderr
    assert 'no *.tar.gz' in result.stderr


def test_every_dist_found_is_installed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check that the whole directory is covered, not just one dist.

    :param tmp_path: Pytest's per-test directory fixture.
    :param monkeypatch: Pytest's attribute-patching fixture.
    """
    dist_dir = _make_dists(tmp_path / 'dist', *_DIST_NAMES)
    installed: list[str] = []

    def fake_run(command: _c.Sequence[str], cwd: Path | None = None) -> str:  # noqa: ARG001
        installed.extend(
            arg for arg in command if arg.endswith(('.whl', '.gz'))
        )
        return _LISTED if 'list' in command else 'commands = python x.py\n'

    def fake_create_venv(venv_dir: Path) -> Path:
        return venv_dir / 'python'

    monkeypatch.setattr(_dist_smoke, '_run', fake_run)
    monkeypatch.setattr(_dist_smoke, '_create_venv', fake_create_venv)

    result = _run_check(dist_dir)

    assert len(installed) == len(_DIST_NAMES)
    assert result.returncode == 1
    assert 'x.py' in result.stderr
    assert 'rebuild with' in result.stderr


def test_a_working_pair_of_dists_leaves_nothing_to_say(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Check that the check is capable of passing at all.

    :param tmp_path: Pytest's per-test directory fixture.
    :param monkeypatch: Pytest's attribute-patching fixture.
    """
    dist_dir = _make_dists(tmp_path / 'dist', *_DIST_NAMES)
    scripts: dict[Path, Path] = {}

    def fake_create_venv(venv_dir: Path) -> Path:
        scripts[venv_dir] = _installed_script(venv_dir, '_check_seed.py')
        return venv_dir / 'python'

    def fake_run(command: _c.Sequence[str], cwd: Path | None = None) -> str:  # noqa: ARG001
        if 'list' in command:
            return _LISTED

        script = tuple(scripts.values())[-1]
        return f'commands = python {script}\n'

    monkeypatch.setattr(_dist_smoke, '_run', fake_run)
    monkeypatch.setattr(_dist_smoke, '_create_venv', fake_create_venv)

    result = _run_check(dist_dir)

    assert result == _CheckResult(0, '')
