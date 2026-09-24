"""Tests that the linters are pointed at every CI workflow."""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).parents[1]
_TOX_INI = _REPO_ROOT / 'tox.ini'
_WORKFLOWS_DIR = _REPO_ROOT / '.github' / 'workflows'


def _linted_workflows(tox_ini: Path) -> frozenset[str]:
    """Read the workflow list the ``lint`` env is handed.

    :param tox_ini: The ``tox.ini`` holding the ``ci-workflows`` section.
    :returns: The paths named there, relative to the repository root.
    :raises KeyError: If the section or its ``files`` key is missing.
    """
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(tox_ini.read_text(encoding='utf-8'))
    return frozenset(parser['ci-workflows']['files'].split())


def _present_workflows(workflows_dir: Path) -> frozenset[str]:
    """List the workflow definitions the repository actually holds.

    :param workflows_dir: The ``.github/workflows`` directory to list.
    :returns: The paths found there, relative to the repository root.
    """
    return frozenset(
        path.relative_to(workflows_dir.parents[1]).as_posix()
        for path in sorted(workflows_dir.iterdir())
        if path.suffix in {'.yaml', '.yml'}
    )


def test_every_workflow_is_linted() -> None:
    """Check that ``[ci-workflows]files`` lists every workflow.

    ``check-jsonschema`` takes files rather than a directory and
    ``commands`` are run without a shell, so the list is written out by
    hand. This is what keeps writing it out from being optional.
    """
    assert _linted_workflows(_TOX_INI) == _present_workflows(_WORKFLOWS_DIR)


def test_an_unlisted_workflow_is_caught(tmp_path: Path) -> None:
    """Check that a workflow missing from the list fails the comparison.

    :param tmp_path: Pytest's per-test directory fixture.
    """
    workflows_dir = tmp_path / '.github' / 'workflows'
    workflows_dir.mkdir(parents=True)
    for name in ('ci.yml', 'release.yml'):
        (workflows_dir / name).write_text('---\n', encoding='utf-8')
    tox_ini = tmp_path / 'tox.ini'
    tox_ini.write_text(
        '[ci-workflows]\nfiles = .github/workflows/ci.yml\n',
        encoding='utf-8',
    )

    assert _linted_workflows(tox_ini) != _present_workflows(workflows_dir)


def test_a_missing_section_is_not_silently_empty(tmp_path: Path) -> None:
    """Check that a list that has gone missing is an error, not a pass.

    :param tmp_path: Pytest's per-test directory fixture.
    """
    tox_ini = tmp_path / 'tox.ini'
    tox_ini.write_text('[testenv]\n', encoding='utf-8')

    with pytest.raises(KeyError):
        _linted_workflows(tox_ini)


def test_only_yaml_is_expected_to_be_linted(tmp_path: Path) -> None:
    """Check that a stray non-workflow file is not demanded of the list.

    :param tmp_path: Pytest's per-test directory fixture.
    """
    workflows_dir = tmp_path / '.github' / 'workflows'
    workflows_dir.mkdir(parents=True)
    (workflows_dir / 'ci.yml').write_text('---\n', encoding='utf-8')
    (workflows_dir / 'README.md').write_text('', encoding='utf-8')

    assert _present_workflows(workflows_dir) == frozenset(
        {'.github/workflows/ci.yml'},
    )
