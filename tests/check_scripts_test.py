"""Behavioral tests for the drift-check helper snippets."""

from __future__ import annotations

import subprocess
import sys
import typing as _t

import pytest

from tox_plugins.lock._plugin import (
    _CHECK_COMPARE_SCRIPT,
    _CHECK_SEED_SCRIPT,
)


if _t.TYPE_CHECKING:
    from pathlib import Path


def _run(script: str, *args: Path) -> subprocess.CompletedProcess[str]:
    """Run one of the plugin's snippets the way the env would.

    :param script: The Python source to run.
    :param args: The paths to pass to the snippet.
    :returns: The completed process, with its output captured.
    """
    return subprocess.run(  # noqa: S603
        [sys.executable, '-c', script, *map(str, args)],
        capture_output=True,
        check=False,
        text=True,
    )


def test_seed_copies_the_lock_into_a_missing_directory(tmp_path: Path) -> None:
    """The scratch copy brings its parent directory along.

    :param tmp_path: Pytest's temporary directory fixture.
    """
    lock_file = tmp_path / 'requirements.txt'
    lock_file.write_text('attrs==1.0\n', encoding='utf-8')
    scratch_file = tmp_path / 'nested' / 'scratch' / 'requirements.txt'

    assert _run(_CHECK_SEED_SCRIPT, lock_file, scratch_file).returncode == 0
    assert scratch_file.read_text(encoding='utf-8') == 'attrs==1.0\n'


def test_seed_clears_a_scratch_file_left_by_an_earlier_run(
    tmp_path: Path,
) -> None:
    """A lock that is not there yet leaves no stale scratch to compare.

    :param tmp_path: Pytest's temporary directory fixture.
    """
    scratch_file = tmp_path / 'requirements.txt'
    scratch_file.write_text('attrs==1.0\n', encoding='utf-8')

    seed_result = _run(
        _CHECK_SEED_SCRIPT,
        tmp_path / 'absent.txt',
        scratch_file,
    )

    assert seed_result.returncode == 0
    assert not scratch_file.exists()


@pytest.mark.parametrize(
    ('scratch_text', 'lock_text', 'expected_failure'),
    (
        pytest.param('attrs==1.0\n', 'attrs==1.0\n', False, id='in-sync'),
        pytest.param('attrs==2.0\n', 'attrs==1.0\n', True, id='pin-moved'),
        pytest.param(
            'attrs==1.0\nidna==3.0\n',
            'attrs==1.0\n',
            True,
            id='dependency-added',
        ),
        pytest.param(
            '# uv pip compile -o /tmp/scratch.txt\nattrs==1.0\n',
            '# uv pip compile -o requirements.txt\nattrs==1.0\n',
            False,
            id='headers-naming-different-outputs-are-ignored',
        ),
        pytest.param(
            'attrs==1.0\n    # via nothing\n',
            'attrs==1.0\n    # via myproject\n',
            False,
            id='indented-annotations-are-ignored',
        ),
    ),
)
def test_compare_reports_drift(
    *,
    tmp_path: Path,
    scratch_text: str,
    lock_text: str,
    expected_failure: bool,
) -> None:
    """Only a change in the pins themselves fails the check.

    :param tmp_path: Pytest's temporary directory fixture.
    :param scratch_text: The contents of the freshly compiled lock.
    :param lock_text: The contents of the lock the project committed.
    :param expected_failure: Whether the comparison should fail.
    """
    scratch_file = tmp_path / 'scratch.txt'
    scratch_file.write_text(scratch_text, encoding='utf-8')
    lock_file = tmp_path / 'requirements.txt'
    lock_file.write_text(lock_text, encoding='utf-8')

    compare_result = _run(_CHECK_COMPARE_SCRIPT, scratch_file, lock_file)

    assert bool(compare_result.returncode) is expected_failure
    if expected_failure:
        assert 'out of date' in compare_result.stderr


def test_compare_fails_when_there_is_no_lock_to_compare(
    tmp_path: Path,
) -> None:
    """A project that never locked gets told so, not a traceback.

    :param tmp_path: Pytest's temporary directory fixture.
    """
    scratch_file = tmp_path / 'scratch.txt'
    scratch_file.write_text('attrs==1.0\n', encoding='utf-8')

    compare_result = _run(
        _CHECK_COMPARE_SCRIPT,
        scratch_file,
        tmp_path / 'requirements.txt',
    )

    assert compare_result.returncode
    assert 'does not exist' in compare_result.stderr
    assert 'Traceback' not in compare_result.stderr


def test_compare_shows_which_pins_moved(tmp_path: Path) -> None:
    """A failing check names the drift instead of merely asserting it.

    :param tmp_path: Pytest's temporary directory fixture.
    """
    scratch_file = tmp_path / 'scratch.txt'
    scratch_file.write_text(
        '# uv pip compile -o scratch.txt\nattrs==2.0\nidna==3.0\n',
        encoding='utf-8',
    )
    lock_file = tmp_path / 'requirements.txt'
    lock_file.write_text(
        '# uv pip compile -o requirements.txt\nattrs==1.0\n',
        encoding='utf-8',
    )

    compare_result = _run(_CHECK_COMPARE_SCRIPT, scratch_file, lock_file)

    assert compare_result.returncode
    assert '-attrs==1.0' in compare_result.stderr
    assert '+attrs==2.0' in compare_result.stderr
    assert '+idna==3.0' in compare_result.stderr
    # NOTE: The diff covers what was compared -- the pins -- so the
    # NOTE: headers the check deliberately ignores stay out of it.
    assert 'uv pip compile' not in compare_result.stderr


def test_compare_reports_every_stale_lock_in_one_run(tmp_path: Path) -> None:
    """One invocation covers all the locks, not just the first one.

    ``commands`` stop at the first failure, so a comparison per lock
    would report the earliest stale one and say nothing about the rest
    -- turning a single red build into as many as there are locks
    behind it.

    :param tmp_path: Pytest's temporary directory fixture.
    """
    pairs: list[Path] = []
    lock_files: list[Path] = []
    for lock_name, pin in (('base.txt', 'attrs'), ('test.txt', 'idna')):
        scratch_file = tmp_path / f'scratch-{lock_name}'
        scratch_file.write_text(f'{pin}==2.0\n', encoding='utf-8')
        lock_file = tmp_path / lock_name
        lock_file.write_text(f'{pin}==1.0\n', encoding='utf-8')
        pairs += [scratch_file, lock_file]
        lock_files.append(lock_file)

    compare_result = _run(_CHECK_COMPARE_SCRIPT, *pairs)

    assert compare_result.returncode
    assert '-attrs==1.0' in compare_result.stderr
    assert '-idna==1.0' in compare_result.stderr
    both_locks = ', '.join(map(str, lock_files))
    assert f'{both_locks} are out of date' in compare_result.stderr


def test_compare_leaves_the_locks_that_are_current_out_of_it(
    tmp_path: Path,
) -> None:
    """A lock still matching its sources is not named as drifted.

    :param tmp_path: Pytest's temporary directory fixture.
    """
    current_scratch = tmp_path / 'scratch-current.txt'
    current_scratch.write_text('attrs==1.0\n', encoding='utf-8')
    current_lock = tmp_path / 'current.txt'
    current_lock.write_text('attrs==1.0\n', encoding='utf-8')
    stale_scratch = tmp_path / 'scratch-stale.txt'
    stale_scratch.write_text('idna==2.0\n', encoding='utf-8')
    stale_lock = tmp_path / 'stale.txt'
    stale_lock.write_text('idna==1.0\n', encoding='utf-8')

    compare_result = _run(
        _CHECK_COMPARE_SCRIPT,
        current_scratch,
        current_lock,
        stale_scratch,
        stale_lock,
    )

    assert compare_result.returncode
    assert f'{stale_lock} is out of date' in compare_result.stderr
    assert 'current.txt' not in compare_result.stderr
