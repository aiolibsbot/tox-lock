"""Tests pinning every restatement of the supported Python floor.

``requires-python`` in ``pyproject.toml`` is the floor an installer
enforces, and four other files in this tree say the same number again:
the oldest trove classifier, ``python_version`` in ``.mypy.ini``,
``target-version`` in ``.ruff.toml`` and the ``--python-version`` that
``lock_options`` hands ``uv``. None of them was read by anything, which
is the mechanism :mod:`_ci_matrix` was written to remove one noun over
-- its own NOTE says outright that the floor it line-scans for is "the
floor ``.mypy.ini`` and ``.ruff.toml`` both analyse for", and then
leaves both unchecked.

Restating a fact is only a defect when the copies can disagree in
silence, so the two tools were asked which of them reads the authority
for itself:

* ``ruff`` does. With ``target-version`` unset it resolves the floor
  out of ``requires-python``, standalone ``.ruff.toml`` and all --
  ``ruff check --show-settings`` reports ``3.12`` the moment the
  authority says ``>= 3.12``. That copy was deleted rather than gated:
  the cheapest restatement to keep honest is the one that is not made.
* ``mypy`` does not. Left unset, ``python_version`` is the version of
  the interpreter ``mypy`` happens to run under -- 3.13 in CI -- so
  dropping the line would silently stop analysing for the floor
  altogether. It stays, and is checked here.

``uv`` is the third case and sits with ``ruff``, though it took this
plugin to put it there. ``uv`` itself reads no floor: compiled under
3.13 and under 3.10 the same sources come out differently, and they do
so even when the ``pyproject.toml`` declaring ``requires-python`` is
the very file being compiled. What changed is that ``tox-lock`` now
reads that declaration and hands ``uv`` a ``--python-version`` off it,
so the copy in ``tox.ini`` went the way ``.ruff.toml``'s did: deleted
rather than gated. The line is still matched here, because a project
that puts one back has overridden the floor rather than restated it,
and the two are worth telling apart.
"""

from __future__ import annotations

import re
import typing as _t
from pathlib import Path

import pytest

from _ci_matrix import supported_pythons


if _t.TYPE_CHECKING:
    from collections import abc as _c


_ROOT = Path(__file__).parents[1]
_PYPROJECT = _ROOT / 'pyproject.toml'

# NOTE: A line scan rather than a parse, for the reason `_ci_matrix`
# NOTE: gives: `tomllib` arrived in 3.11 and the floor being read is
# NOTE: 3.10. Two of the four files are not TOML anyway.
_REQUIRES_PYTHON_RE = re.compile(
    r"""^requires-python = ['"]>= 3\.(?P<minor>\d+)['"]$""",
)


class _Restatement(_t.NamedTuple):
    """One file repeating the floor, and what happens without it."""

    config: str
    pattern: re.Pattern[str]
    inferred: bool
    why: str


_RESTATEMENTS = (
    _Restatement(
        config='.mypy.ini',
        pattern=re.compile(r'^python_version = 3\.(?P<minor>\d+)$'),
        inferred=False,
        why=(
            'unset, `python_version` is whichever interpreter `mypy` runs '
            'under, so the line has to be there and has to agree'
        ),
    ),
    _Restatement(
        config='.ruff.toml',
        pattern=re.compile(
            r"""^target-version = ['"]py3(?P<minor>\d+)['"]$""",
        ),
        inferred=True,
        why=(
            '`ruff` resolves `target-version` out of `requires-python` when '
            'it is unset, so saying nothing is right and disagreeing is not'
        ),
    ),
    _Restatement(
        config='tox.ini',
        pattern=re.compile(r'^  --python-version 3\.(?P<minor>\d+)$'),
        inferred=True,
        why=(
            '`tox-lock` seeds `--python-version` off `requires-python` when '
            '`lock_options` names no target, so saying nothing is right and '
            'disagreeing is not'
        ),
    ),
)


def _stated_floor(config: Path, pattern: re.Pattern[str]) -> str | None:
    """Read back the floor a config file states, if it states one.

    :param config: The file to scan.
    :param pattern: The pattern matching its way of stating the floor.
    :returns: The floor as ``3.x``, or :data:`None` if it is not stated.
    """
    for line in config.read_text(encoding='utf-8').splitlines():
        if (match := pattern.match(line)) is not None:
            return f'3.{match["minor"]}'

    return None


@pytest.fixture(name='floor', scope='session')
def _floor() -> str:
    """Read the floor every other file in the tree has to match.

    :returns: The ``requires-python`` floor, as ``3.x``.
    """
    floor = _stated_floor(_PYPROJECT, _REQUIRES_PYTHON_RE)
    assert floor is not None, (
        f'{_PYPROJECT.name} states no `requires-python = ">= 3.x"`, which '
        'is the authority the rest of this module compares against. A '
        'floor written as a range or with the operator spelled differently '
        'has to be taught to `_REQUIRES_PYTHON_RE` rather than left '
        'unread, or every check below passes by finding nothing.'
    )
    return floor


@pytest.mark.parametrize(
    'restatement',
    _RESTATEMENTS,
    ids=[restatement.config for restatement in _RESTATEMENTS],
)
def test_a_restated_floor_is_the_declared_one(
    restatement: _Restatement,
    floor: str,
) -> None:
    """Check that a file repeating the floor repeats this one.

    :param restatement: The file being checked, and its pattern.
    :param floor: The ``requires-python`` floor to agree with.
    """
    stated = _stated_floor(_ROOT / restatement.config, restatement.pattern)
    permitted: tuple[str | None, ...] = (
        (floor, None) if restatement.inferred else (floor,)
    )

    assert stated in permitted, (
        f'{restatement.config} states the supported Python floor as '
        f'{stated}, while `requires-python` declares {floor}. The '
        f'declaration is the one an installer enforces, so it is the one '
        f'to follow: {restatement.why}.'
    )


def test_the_oldest_claim_is_the_declared_floor(floor: str) -> None:
    """Check that the trove classifiers start at the declared floor.

    A classifier is the promise a human reads and ``requires-python`` is
    the rule an installer applies, so a gap between them is a lie in one
    direction or the other: a missing ``:: 3.10`` hides a version that
    installs, and an extra one advertises a version that cannot.

    :param floor: The ``requires-python`` floor to agree with.
    """
    claimed: _c.Sequence[str] = supported_pythons(_PYPROJECT)

    assert claimed[0] == floor


def test_a_file_stating_no_floor_reads_back_as_none(tmp_path: Path) -> None:
    """Check that a silent config file is reported as silent.

    :param tmp_path: Pytest's per-test temporary directory.
    """
    silent = tmp_path / '.mypy.ini'
    silent.write_text('[mypy]\nstrict = true\n', encoding='utf-8')

    assert _stated_floor(silent, _RESTATEMENTS[0].pattern) is None
