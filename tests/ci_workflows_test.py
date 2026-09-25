"""Tests that the CI workflows and ``tox.ini`` agree with each other."""

from __future__ import annotations

import configparser
import re
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).parents[1]
_TOX_INI = _REPO_ROOT / 'tox.ini'
_WORKFLOWS_DIR = _REPO_ROOT / '.github' / 'workflows'
_CI_WORKFLOW = _WORKFLOWS_DIR / 'ci.yml'

# NOTE: A text scan for a fixed string rather than a YAML parse, for
# NOTE: the same reason `_ci_matrix` scans `pyproject.toml` rather than
# NOTE: parsing it: there is no YAML reader in the standard library, and
# NOTE: taking a dependency to read one command out of one file this
# NOTE: repository writes itself buys nothing.
#
# NOTE: Whitespace is flattened before the scan rather than the file
# NOTE: being read a line at a time, because `.yamllint` holds the
# NOTE: workflows to seventy-nine columns and a `run:` naming several
# NOTE: envs runs past that. Folding it onto a second line is what a
# NOTE: contributor does next, and a line scan stops seeing the whole
# NOTE: job at exactly that point -- silently, which is the one thing a
# NOTE: check on whether a gate is reachable must not do.
_TOX_RUN_MARKER = 'python -Im tox run -e '
_WHITESPACE = re.compile(r'\s+')


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


def _default_envs(tox_ini: Path) -> frozenset[str]:
    """Read the envs ``tox`` runs when asked for nothing in particular.

    :param tox_ini: The ``tox.ini`` holding the ``tox`` core section.
    :returns: The names in ``env_list``.
    :raises KeyError: If the section or its ``env_list`` key is missing.
    """
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(tox_ini.read_text(encoding='utf-8'))
    return frozenset(parser['tox']['env_list'].split())


def _gating_envs(ci_workflow: Path) -> frozenset[str]:
    """List the envs the pull request gate runs.

    :param ci_workflow: The ``ci.yml`` whose jobs invoke them.
    :returns: Every env named after ``tox run -e`` there, one entry per
        name in a comma-separated list.
    """
    folded = _WHITESPACE.sub(' ', ci_workflow.read_text(encoding='utf-8'))
    return frozenset(
        env
        for invocation in folded.split(_TOX_RUN_MARKER)[1:]
        for env in invocation.split()[0].split(',')
    )


def test_ci_gates_run_by_default() -> None:
    """Check that ``env_list`` covers every env ``ci.yml`` runs.

    A contributor runs ``tox``; a pull request runs eight jobs. When the
    first is a subset of the second by accident rather than by
    construction, the answer to "is this ready to push" is a different
    question from the one CI asks, and a gate added to the workflow
    without a local runner is one nobody meets until the push.

    A subset rather than an equality: the default set legitimately holds
    more. ``ci.yml`` starts from a fresh checkout and a work tree does
    not, so ``cleanup-dists`` runs here and not there.
    """
    assert _gating_envs(_CI_WORKFLOW) <= _default_envs(_TOX_INI)


def test_a_folded_invocation_is_still_read(tmp_path: Path) -> None:
    """Check that an env list wrapped onto a second line is seen.

    ``.yamllint`` holds the workflows to seventy-nine columns, so a job
    running several envs has to fold its ``run:``. A scan that read the
    file a line at a time found the marker and then took the rest of
    that line -- an empty one -- as the whole list, and the job's envs
    went unchecked without the check saying so.

    :param tmp_path: Pytest's per-test directory fixture.
    """
    ci_workflow = tmp_path / 'ci.yml'
    ci_workflow.write_text(
        '    - run: >-\n'
        '        python -Im tox run -e\n'
        '        lint,type-check\n',
        encoding='utf-8',
    )

    assert _gating_envs(ci_workflow) == {'lint', 'type-check'}


def test_a_gate_missing_from_the_default_set_is_caught(
    tmp_path: Path,
) -> None:
    """Check that a gate absent from ``env_list`` fails the comparison.

    :param tmp_path: Pytest's per-test directory fixture.
    """
    ci_workflow = tmp_path / 'ci.yml'
    ci_workflow.write_text(
        '    - run: python -Im tox run -e lint,type-check\n',
        encoding='utf-8',
    )
    tox_ini = tmp_path / 'tox.ini'
    tox_ini.write_text('[tox]\nenv_list =\n  lint\n', encoding='utf-8')

    assert not _gating_envs(ci_workflow) <= _default_envs(tox_ini)


def test_the_default_set_is_required_to_be_stated(tmp_path: Path) -> None:
    """Check that a missing ``env_list`` is an error rather than empty.

    :param tmp_path: Pytest's per-test directory fixture.
    """
    tox_ini = tmp_path / 'tox.ini'
    tox_ini.write_text('[tox]\n', encoding='utf-8')

    with pytest.raises(KeyError):
        _default_envs(tox_ini)
