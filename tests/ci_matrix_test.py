"""Behavioral tests for the CI matrix derivation."""

from __future__ import annotations

import json
import typing as _t
from pathlib import Path

import pytest

from _ci_matrix import ci_matrix, supported_pythons
from _ci_matrix import main as derive_matrix


if _t.TYPE_CHECKING:
    from collections import abc as _c


_PYPROJECT = Path(__file__).parents[1] / 'pyproject.toml'

_CLASSIFIER_LINES = (
    '  "Programming Language :: Python :: 3 :: Only",',
    "  'Programming Language :: Python :: 3.12',",
    '  "Programming Language :: Python :: 3.9",',
    "  'Programming Language :: Python :: 3.10',",
)


def _write_pyproject(tmp_path: Path, *lines: str) -> Path:
    """Lay out a ``pyproject.toml`` holding the given lines.

    :param tmp_path: The directory to write the file into.
    :param lines: The body lines to put between the two markers.
    :returns: The path of the file that was written.
    """
    pyproject = tmp_path / 'pyproject.toml'
    pyproject.write_text(
        '\n'.join(('[project]', 'classifiers = [', *lines, ']', '')),
        encoding='utf-8',
    )
    return pyproject


def test_the_versions_come_back_oldest_first(tmp_path: Path) -> None:
    """Check that the claims are ordered by number, not by text.

    :param tmp_path: Pytest's per-test temporary directory.
    """
    assert supported_pythons(
        _write_pyproject(tmp_path, *_CLASSIFIER_LINES),
    ) == ('3.9', '3.10', '3.12')


def test_the_bare_major_claim_is_not_a_version(tmp_path: Path) -> None:
    """Check that ``:: 3 :: Only`` does not become a test job.

    :param tmp_path: Pytest's per-test temporary directory.
    """
    assert supported_pythons(
        _write_pyproject(tmp_path, _CLASSIFIER_LINES[0]),
    ) == ()


def test_a_classifier_free_project_claims_nothing(tmp_path: Path) -> None:
    """Check that a file with no claims in it yields no versions.

    :param tmp_path: Pytest's per-test temporary directory.
    """
    assert supported_pythons(_write_pyproject(tmp_path)) == ()


def test_this_project_claims_its_own_floor() -> None:
    """Check the derivation against the file the workflow reads."""
    versions = supported_pythons(_PYPROJECT)

    assert versions[0] == '3.10'
    assert '3' not in versions


@pytest.mark.parametrize(
    ('versions', 'expected'),
    (
        pytest.param(
            ('3.10', '3.11', '3.12'),
            (
                ('3.10', 'ubuntu-latest'),
                ('3.11', 'ubuntu-latest'),
                ('3.12', 'ubuntu-latest'),
                ('3.10', 'windows-latest'),
                ('3.10', 'macos-latest'),
                ('3.12', 'windows-latest'),
                ('3.12', 'macos-latest'),
            ),
            id='the-ends-of-the-range-cross-platform',
        ),
        pytest.param(
            ('3.10',),
            (
                ('3.10', 'ubuntu-latest'),
                ('3.10', 'windows-latest'),
                ('3.10', 'macos-latest'),
            ),
            id='a-single-claim-is-not-tested-twice',
        ),
    ),
)
def test_the_matrix_pairs_versions_with_runners(
    versions: _c.Sequence[str],
    expected: _c.Sequence[tuple[str, str]],
) -> None:
    """Check which interpreter and runner pairs get a job.

    :param versions: The claimed versions handed to the derivation.
    :param expected: The version and runner pairs it should produce.
    """
    assert tuple(
        (entry['python-version'], entry['runner'])
        for entry in ci_matrix(versions)['include']
    ) == tuple(expected)


def test_the_output_is_a_github_step_output(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Check that the matrix is printed as ``name=value`` JSON.

    :param capsys: Pytest's captured-output fixture.
    :param tmp_path: Pytest's per-test temporary directory.
    """
    pyproject = _write_pyproject(tmp_path, *_CLASSIFIER_LINES)

    assert derive_matrix((str(pyproject),)) == 0

    name, _, value = capsys.readouterr().out.strip().partition('=')

    parsed: object = json.loads(value)

    assert name == 'matrix'
    assert parsed == ci_matrix(('3.9', '3.10', '3.12'))


def test_claiming_nothing_fails_the_derivation(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Check that an empty claim list stops CI instead of skipping it.

    :param capsys: Pytest's captured-output fixture.
    :param tmp_path: Pytest's per-test temporary directory.
    """
    pyproject = _write_pyproject(tmp_path)

    assert derive_matrix((str(pyproject),)) == 1

    captured = capsys.readouterr()

    assert not captured.out
    assert str(pyproject) in captured.err
