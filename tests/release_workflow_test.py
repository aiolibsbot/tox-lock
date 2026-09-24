"""Tests that the release workflow gates its one irreversible step.

``release.yml`` publishes to PyPI, and a filename taken there is never
given back. So every check that can fail a release for a reason already
knowable from the tag and the tree has to run *before* that upload --
which is a claim about the job graph, not about any one job's steps, and
so is checked here rather than read off the file by whoever edits it.

Kept out of the shipped package, like the rest of ``tests{/}``: it
describes this project's own release process rather than any of the
plugin's work.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).parents[1]
_RELEASE_WORKFLOW = _REPO_ROOT / '.github' / 'workflows' / 'release.yml'

_PUBLISH_JOB = 'publish-to-pypi'

# NOTE: The gate is found by the script it runs rather than by the job
# NOTE: name it happens to carry, so that renaming the job -- or moving
# NOTE: the step into another one -- keeps meaning the same thing here.
_NOTES_MARKER = '_changelog.py'

# NOTE: A hand-rolled read rather than a YAML parse, for the reason
# NOTE: `tests{/}ci_workflows_test.py` gives: there is no YAML reader in
# NOTE: the standard library. That file gets away with scanning for a
# NOTE: fixed marker because the claim it checks is about one command;
# NOTE: this one is about which job runs before which, so the nesting
# NOTE: has to be read. Only as much of it as `needs` and a job body
# NOTE: need: job names sit at two spaces, their keys at four, and a
# NOTE: `needs` list is written unindented under its key throughout
# NOTE: this repository's workflows -- which `yamllint` enforces.
_JOB_RE = re.compile(r'^ {2}(?P<job>[\w-]+):$')
_KEY_RE = re.compile(r'^ {4}(?P<key>[\w-]+):(?P<inline>.*)$')
_ITEM_RE = re.compile(r'^ {4}- (?P<item>[\w-]+)$')


def _group(match: re.Match[str], name: str) -> str:
    """Read one named group of a match as the string it is.

    ``re.Match.__getitem__`` is typed as returning ``str | Any`` --
    ``Any`` covering the group that did not participate -- and this
    repository's ``mypy`` configuration refuses an expression carrying
    one. The optional groups here are spelled to match empty rather
    than to be absent, so the narrowing is sound.

    :param match: The match to read from.
    :param name: The name of the group wanted.
    :returns: What that group captured.
    """
    return str(match[name])


def _job_graph(workflow: Path) -> dict[str, tuple[frozenset[str], str]]:
    """Read a workflow's jobs, what each waits for and what each runs.

    The scan starts at the top-level ``jobs:`` key rather than at the
    first line, because ``on:`` nests to the same depths: a ``push``
    trigger reads as a job and the ``tags`` under it as that job's key.

    :param workflow: The workflow definition to read.
    :returns: Each job name, mapped to the jobs it names in ``needs``
        and to the rest of its definition as text.
    """
    jobs: dict[str, tuple[set[str], list[str]]] = {}
    job: str | None = None
    in_needs = reached_jobs = False

    for line in workflow.read_text(encoding='utf-8').splitlines():
        if not reached_jobs:
            reached_jobs = line == 'jobs:'
            continue

        job_match = _JOB_RE.match(line)
        if job_match is not None:
            job, in_needs = _group(job_match, 'job'), False
            jobs[job] = (set(), [])
            continue

        if job is None:
            continue

        needs, body = jobs[job]
        body.append(line)

        item_match = _ITEM_RE.match(line)
        if in_needs and item_match is not None:
            needs.add(_group(item_match, 'item'))
            continue

        key_match = _KEY_RE.match(line)
        if key_match is None:
            continue

        in_needs = _group(key_match, 'key') == 'needs'
        inline_need = _group(key_match, 'inline').strip()
        if in_needs and inline_need:
            needs.add(inline_need)
            in_needs = False

    return {
        name: (frozenset(needs), '\n'.join(body))
        for name, (needs, body) in jobs.items()
    }


def _ancestors(
    graph: dict[str, tuple[frozenset[str], str]],
    job: str,
) -> frozenset[str]:
    """List every job that has to finish before a given one starts.

    :param graph: The job graph to walk, as :func:`_job_graph` reads it.
    :param job: The job whose ancestry is wanted.
    :returns: The names of its transitive dependencies.
    :raises KeyError: If the workflow declares no such job.
    """
    reached: set[str] = set()
    pending = set(graph[job][0])
    while pending:
        reached |= pending
        pending = {
            need for name in pending for need in graph[name][0]
        } - reached

    return frozenset(reached)


def _notes_jobs(graph: dict[str, tuple[frozenset[str], str]]) -> set[str]:
    """Name the jobs that read a release's notes out of the changelog.

    :param graph: The job graph to look through.
    :returns: The names of the jobs running that check.
    """
    return {
        name for name, (_, body) in graph.items() if _NOTES_MARKER in body
    }


def test_the_notes_gate_runs_before_the_upload() -> None:
    """Check that a tag with no changelog section fails before PyPI.

    ``_changelog.py notes`` refuses two mistakes that are both made
    before the tag is pushed: fragments no ``towncrier build`` has
    collected, and a version the changelog says nothing about. Both are
    recoverable right up to the upload and not one moment after it, so
    the job running that check has to be one the upload waits for.
    """
    graph = _job_graph(_RELEASE_WORKFLOW)
    notes_jobs = _notes_jobs(graph)

    assert notes_jobs
    assert notes_jobs <= _ancestors(graph, _PUBLISH_JOB)


def test_a_gate_behind_the_upload_is_caught(tmp_path: Path) -> None:
    """Check that a notes gate downstream of PyPI fails the comparison.

    :param tmp_path: Pytest's per-test directory fixture.
    """
    workflow = tmp_path / 'release.yml'
    workflow.write_text(
        'jobs:\n'
        '\n'
        '  ci:\n'
        '    uses: ./.github/workflows/ci.yml\n'
        '\n'
        f'  {_PUBLISH_JOB}:\n'
        '    needs: ci\n'
        '\n'
        '  github-release:\n'
        '    needs:\n'
        '    - ci\n'
        f'    - {_PUBLISH_JOB}\n'
        '    steps:\n'
        f'    - run: python tests{_NOTES_MARKER} notes\n',
        encoding='utf-8',
    )
    graph = _job_graph(workflow)

    assert _notes_jobs(graph) == {'github-release'}
    assert not _notes_jobs(graph) <= _ancestors(graph, _PUBLISH_JOB)


def test_both_spellings_of_needs_are_read(tmp_path: Path) -> None:
    """Check that an inline ``needs`` counts the same as a list one.

    A job waiting on one other names it on the ``needs`` line itself; a
    job waiting on two writes a list under it. A reader seeing only the
    second form would find the upload unguarded whenever its single
    gate was spelled the short way.

    :param tmp_path: Pytest's per-test directory fixture.
    """
    workflow = tmp_path / 'release.yml'
    workflow.write_text(
        'on:\n'
        '  push:\n'
        '    tags:\n'
        '    - v*\n'
        '\n'
        'jobs:\n'
        '\n'
        '  ci:\n'
        '    runs-on: ubuntu-latest\n'
        '\n'
        '  notes:\n'
        '    needs: ci\n'
        '\n'
        '  publish:\n'
        '    needs:\n'
        '    - ci\n'
        '    - notes\n',
        encoding='utf-8',
    )

    assert _ancestors(_job_graph(workflow), 'publish') == {'ci', 'notes'}


def test_a_trigger_is_not_read_as_a_job(tmp_path: Path) -> None:
    """Check that the ``on:`` block above ``jobs:`` is skipped.

    ``push`` sits at a job's indentation and ``tags`` at a job key's, so
    a reader starting from the first line finds a ``push`` job and, the
    ``v*`` under it being no identifier, an empty graph past it.

    :param tmp_path: Pytest's per-test directory fixture.
    """
    workflow = tmp_path / 'release.yml'
    workflow.write_text(
        'on:\n'
        '  push:\n'
        '    tags:\n'
        '    - v*\n'
        '  workflow_dispatch:\n'
        '\n'
        'jobs:\n'
        '\n'
        '  ci:\n'
        '    runs-on: ubuntu-latest\n',
        encoding='utf-8',
    )

    assert set(_job_graph(workflow)) == {'ci'}


def test_a_missing_upload_job_is_an_error(tmp_path: Path) -> None:
    """Check that a renamed upload job is an error, not a vacuous pass.

    :param tmp_path: Pytest's per-test directory fixture.
    """
    workflow = tmp_path / 'release.yml'
    workflow.write_text(
        'jobs:\n\n  ci:\n    needs: nothing\n', encoding='utf-8',
    )

    with pytest.raises(KeyError):
        _ancestors(_job_graph(workflow), _PUBLISH_JOB)
