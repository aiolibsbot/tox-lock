"""Behavioral tests for the changelog fragment check."""

from __future__ import annotations

import contextlib
import io
import typing as _t

import pytest

from _changelog import main as changelog_main


if _t.TYPE_CHECKING:
    from collections import abc as _c
    from pathlib import Path


# NOTE: `0` and `1` read as themselves; this one is the exit code the
# NOTE: module leaves with when it was called wrongly rather than when
# NOTE: it found something.
_USAGE_ERROR = 2


_PYPROJECT = """\
[tool.towncrier]
name = "tox-lock"
type = [
  { directory = "feature", name = "Features", showcontent = true },
  { directory = "bugfix", name = "Bug fixes", showcontent = true },
]
"""

_CHANGELOG = """\
# Changelog

<!-- towncrier release notes start -->

## 1.1.0 (2026-09-24)

### Features

- Something new.

## 1.0.0 (2026-01-01)

### Bug fixes

- Something old.
"""


def _project(tmp_path: Path) -> Path:
    """Lay out a project with a changelog and an empty fragment dir.

    :param tmp_path: The directory to build it under.
    :returns: The project root.
    """
    (tmp_path / 'pyproject.toml').write_text(
        _PYPROJECT,
        encoding='utf-8',
    )
    (tmp_path / 'CHANGELOG.md').write_text(_CHANGELOG, encoding='utf-8')
    (tmp_path / 'changelog.d').mkdir()
    return tmp_path


def _run(args: _c.Sequence[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with (
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(err),
    ):
        exit_code = changelog_main(args)
    return exit_code, out.getvalue(), err.getvalue()


def _validate(project: Path) -> tuple[int, str, str]:
    return _run(
        (
            'validate',
            str(project / 'pyproject.toml'),
            str(project / 'changelog.d'),
        ),
    )


def _notes(project: Path, version: str) -> tuple[int, str, str]:
    return _run(
        (
            'notes',
            str(project / 'pyproject.toml'),
            str(project / 'CHANGELOG.md'),
            str(project / 'changelog.d'),
            version,
        ),
    )


@pytest.mark.parametrize(
    'name',
    (
        pytest.param('42.feature.md', id='issue'),
        pytest.param('42.feature.2.md', id='second-note-on-one-issue'),
        pytest.param('+rename-a-local.bugfix.md', id='orphan'),
    ),
)
def test_validate_accepts_a_well_named_fragment(
    tmp_path: Path,
    name: str,
) -> None:
    """Accept the names ``towncrier`` renders.

    :param tmp_path: Pytest's temporary directory fixture.
    :param name: The fragment file name under test.
    """
    project = _project(tmp_path)
    (project / 'changelog.d' / name).write_text('Note.', encoding='utf-8')

    assert _validate(project)[0] == 0


@pytest.mark.parametrize(
    'name',
    (
        pytest.param('42.wat.md', id='unknown-category'),
        pytest.param('notanumber.md', id='no-category'),
        pytest.param('42.feature', id='no-suffix'),
        pytest.param('42.feature.rst', id='wrong-suffix'),
    ),
)
def test_validate_refuses_a_fragment_towncrier_would_drop(
    tmp_path: Path,
    name: str,
) -> None:
    """Refuse, by name, what would silently vanish.

    :param tmp_path: Pytest's temporary directory fixture.
    :param name: The fragment file name under test.
    """
    project = _project(tmp_path)
    (project / 'changelog.d' / name).write_text('Note.', encoding='utf-8')

    exit_code, _, err = _validate(project)

    assert exit_code == 1
    assert name in err


def test_validate_ignores_the_instructions_beside_the_fragments(
    tmp_path: Path,
) -> None:
    """Pass over the ``README.md`` explaining the naming.

    :param tmp_path: Pytest's temporary directory fixture.
    """
    project = _project(tmp_path)
    (project / 'changelog.d' / 'README.md').write_text(
        '# Changelog fragments',
        encoding='utf-8',
    )

    assert _validate(project)[0] == 0


def test_validate_refuses_a_config_declaring_no_categories(
    tmp_path: Path,
) -> None:
    """Refuse a config under which every name would be wrong.

    :param tmp_path: Pytest's temporary directory fixture.
    """
    project = _project(tmp_path)
    (project / 'pyproject.toml').write_text(
        '[tool.towncrier]\nname = "tox-lock"\n',
        encoding='utf-8',
    )

    exit_code, _, err = _validate(project)

    assert exit_code == 1
    assert 'no `[tool.towncrier]` categories' in err


def test_notes_prints_only_the_requested_version(tmp_path: Path) -> None:
    """Stop the section at the next version's heading.

    :param tmp_path: Pytest's temporary directory fixture.
    """
    project = _project(tmp_path)
    exit_code, out, _ = _notes(project, '1.1.0')

    assert exit_code == 0
    assert 'Something new.' in out
    assert 'Something old.' not in out
    assert '1.0.0' not in out


def test_notes_refuses_a_version_the_changelog_never_mentions(
    tmp_path: Path,
) -> None:
    """Refuse to publish a release the changelog does not describe.

    :param tmp_path: Pytest's temporary directory fixture.
    """
    project = _project(tmp_path)
    exit_code, out, err = _notes(project, '2.0.0')

    assert exit_code == 1
    assert not out
    assert 'towncrier build --version 2.0.0' in err


def test_notes_refuses_while_a_fragment_is_still_uncollected(
    tmp_path: Path,
) -> None:
    """Refuse notes that would be missing an uncollected change.

    :param tmp_path: Pytest's temporary directory fixture.
    """
    project = _project(tmp_path)
    (project / 'changelog.d' / '42.feature.md').write_text(
        'Never collected.',
        encoding='utf-8',
    )

    exit_code, out, err = _notes(project, '1.1.0')

    assert exit_code == 1
    assert not out
    assert '42.feature.md' in err


def test_an_unknown_subcommand_is_a_usage_error() -> None:
    """Leave with 2, not with a traceback, on a bad invocation."""
    exit_code, _, err = _run(('rebuild',))

    assert exit_code == _USAGE_ERROR
    assert 'usage:' in err
