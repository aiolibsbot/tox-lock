"""Derive the CI test matrix from the project's trove classifiers.

``pyproject.toml`` has claimed ``Programming Language :: Python ::
3.14`` and ``:: 3.15`` since the initial commit, while the workflow
matrix listed 3.10 through 3.13. A trove classifier is a public promise
an installer acts on, so two of them were promises nothing had ever
tested -- the same shape as the ``.mypy.ini`` nothing invoked and the
``# noqa`` codes no linter read.

Correcting the list by hand would leave the mechanism that let it drift
exactly where it was. So the workflow asks this module instead, and the
claim and the proof cannot disagree: adding a classifier adds a job.

Kept out of the shipped package because it describes this project's own
CI rather than doing any of the plugin's work, and named without the
``_test`` suffix so that ``pytest`` imports it for the tests beside it
rather than collecting it as one.
"""

from __future__ import annotations

import json
import re
import sys
import typing as _t
from pathlib import Path


if _t.TYPE_CHECKING:
    from collections import abc as _c


# NOTE: A line scan rather than `tomllib`, which the floor this project
# NOTE: supports does not have -- and which is the floor `.mypy.ini`
# NOTE: and `.ruff.toml` both analyse for. What is being read is a
# NOTE: fixed trove string rather than arbitrary TOML, and
# NOTE: `Programming Language :: Python :: 3 :: Only` deliberately does
# NOTE: not match it.
_CLASSIFIER_RE = re.compile(
    r'^\s*[\'"]Programming Language :: Python :: '
    r'(?P<version>3\.(?P<minor>\d+))[\'"],?\s*$',
)

# NOTE: The platform the whole claimed range runs on. The other two
# NOTE: take the ends of it only: what they are here to catch is this
# NOTE: project's path and shell-quoting assumptions, which do not turn
# NOTE: over between Python releases.
_PRIMARY_RUNNER = 'ubuntu-latest'
_CROSS_PLATFORM_RUNNERS = ('windows-latest', 'macos-latest')


def supported_pythons(pyproject: Path) -> tuple[str, ...]:
    """List the Python versions the project claims to support.

    :param pyproject: The ``pyproject.toml`` holding the classifiers.
    :returns: The claimed versions, oldest first.
    """
    claimed: set[tuple[int, str]] = {
        (int(match['minor']), match['version'])
        for line in pyproject.read_text(encoding='utf-8').splitlines()
        if (match := _CLASSIFIER_RE.match(line)) is not None
    }
    # NOTE: Sorted on the minor as a number rather than on the version
    # NOTE: as text, which would put 3.10 before 3.9 and hand the
    # NOTE: cross-platform jobs the wrong ends of the range.
    return tuple(version for _, version in sorted(claimed))


def ci_matrix(versions: _c.Sequence[str]) -> dict[str, list[dict[str, str]]]:
    """Pair every claimed version with the runners that will test it.

    :param versions: The claimed versions, oldest first.
    :returns: A GitHub Actions ``matrix`` mapping, ready to serialise.
    """
    # NOTE: Spelled out rather than de-duplicated through a set, so
    # NOTE: that a project claiming a single version gets two
    # NOTE: cross-platform jobs rather than four, and so that the order
    # NOTE: of the jobs stays the order of the claims.
    oldest, newest = versions[0], versions[-1]
    ends = (oldest,) if newest == oldest else (oldest, newest)
    return {
        'include': [
            {'python-version': version, 'runner': _PRIMARY_RUNNER}
            for version in versions
        ]
        + [
            {'python-version': version, 'runner': runner}
            for version in ends
            for runner in _CROSS_PLATFORM_RUNNERS
        ],
    }


def main(args: _c.Sequence[str]) -> int:
    """Print the derived matrix as a GitHub Actions step output.

    :param args: The ``pyproject.toml`` holding the classifiers.
    :returns: The exit code to leave with.
    """
    (pyproject,) = map(Path, args)
    versions = supported_pythons(pyproject)
    if not versions:
        sys.stderr.write(
            f'{pyproject} declares no `Programming Language :: Python '
            ':: 3.x` classifier, so there is nothing to test. The '
            'matrix is derived from those claims -- restore them '
            'rather than listing the versions in the workflow.\n',
        )
        return 1

    matrix = json.dumps(ci_matrix(versions), separators=(',', ':'))
    sys.stdout.write(f'matrix={matrix}\n')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
