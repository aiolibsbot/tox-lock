"""Check the changelog fragments and read a version's notes back out.

``towncrier`` ignores a fragment whose name it does not recognise. It
does not warn, and it leaves nothing behind: ``build --draft`` over a
directory holding ``14.wat.md`` and ``notanumber.md`` renders neither
and exits zero. So the obvious gate -- render the draft and see whether
it works -- is a check that cannot fail, of the same kind as the
``.mypy.ini`` nothing invoked and the ``# noqa`` codes no linter read.
The consequence is worse than a missing gate, though: the change is
already made, the contributor did write the note, and it disappears
between the pull request and the release page. This module refuses the
name instead.

It also reads a released version's section back out of
``CHANGELOG.md``, which is what ``.github/workflows/release.yml``
publishes as that release's notes. Both halves live here because they
are the two ends of one claim -- that what a fragment says is what a
user ends up reading -- and neither is worth much without the other.

Kept out of the shipped package because it describes this project's own
release process rather than doing any of the plugin's work, and named
without the ``_test`` suffix so that ``pytest`` imports it for the
tests beside it rather than collecting it as one.
"""

from __future__ import annotations

import re
import sys
import typing as _t
from pathlib import Path


if _t.TYPE_CHECKING:
    from collections import abc as _c


# NOTE: A line scan rather than `tomllib`, which the floor this project
# NOTE: supports does not have -- the same reasoning, and the same
# NOTE: shape, as `tests{/}_ci_matrix.py` reading the trove
# NOTE: classifiers. `directory` appears in `pyproject.toml` only
# NOTE: inside `[tool.towncrier]`'s category table, so the key alone is
# NOTE: unambiguous without tracking which section is open.
_CATEGORY_RE = re.compile(
    r'^\s*\{\s*directory = [\'"](?P<category>[a-z]+)[\'"],',
)

# NOTE: `towncrier`'s own fragment grammar, narrowed to Markdown. The
# NOTE: `+` alternative is its `orphan_prefix`: a change with no issue
# NOTE: and no pull request behind it still deserves a line, and is
# NOTE: rendered without a link. The optional counter is what lets one
# NOTE: issue carry two notes in different words.
_FRAGMENT_RE = re.compile(
    r'^(?P<issue>\d+|\+[^.]+)'
    r'\.(?P<category>[a-z]+)'
    r'(?:\.\d+)?'
    r'\.md$',
)

# NOTE: Not a fragment, and deliberately not hidden: the instructions
# NOTE: for writing one belong next to where they are written, and a
# NOTE: contributor who opens this directory should find them without
# NOTE: being told the file is there.
_NOT_A_FRAGMENT = 'README.md'


def known_categories(pyproject: Path) -> frozenset[str]:
    """List the fragment categories the changelog config declares.

    :param pyproject: The ``pyproject.toml`` holding the config.
    :returns: The category names, unordered.
    """
    return frozenset(
        match['category']
        for line in pyproject.read_text(encoding='utf-8').splitlines()
        if (match := _CATEGORY_RE.match(line)) is not None
    )


def unrecognised_fragments(
    fragment_dir: Path,
    categories: _c.Collection[str],
) -> tuple[str, ...]:
    """Find the files ``towncrier`` would pass over in silence.

    :param fragment_dir: The directory the fragments live in.
    :param categories: The category names that are allowed.
    :returns: The offending file names, sorted.
    """
    return tuple(
        sorted(
            entry.name
            for entry in fragment_dir.iterdir()
            if entry.is_file()
            and entry.name != _NOT_A_FRAGMENT
            and (
                (match := _FRAGMENT_RE.match(entry.name)) is None
                or match['category'] not in categories
            )
        ),
    )


def pending_fragments(
    fragment_dir: Path,
    categories: _c.Collection[str],
) -> tuple[str, ...]:
    """Find the fragments no version has collected yet.

    :param fragment_dir: The directory the fragments live in.
    :param categories: The category names that are allowed.
    :returns: The uncollected file names, sorted.
    """
    return tuple(
        sorted(
            entry.name
            for entry in fragment_dir.iterdir()
            if entry.is_file()
            and (match := _FRAGMENT_RE.match(entry.name)) is not None
            and match['category'] in categories
        ),
    )


def release_notes(changelog: Path, version: str) -> str:
    """Read one version's section out of the changelog.

    :param changelog: The ``CHANGELOG.md`` to read.
    :param version: The version whose section is wanted, unprefixed.
    :returns: The section body, without its heading; empty if absent.
    """
    # NOTE: Matched against `title_format` in `pyproject.toml` rather
    # NOTE: than against any `##` heading: the date in parentheses is
    # NOTE: what distinguishes a version's section from a heading a
    # NOTE: fragment happened to write, and pinning the shape here is
    # NOTE: what makes changing it over there a test failure.
    heading = re.compile(
        rf'^## {re.escape(version)} \(.*\)\s*$',
    )
    next_heading = re.compile(r'^## ')

    lines = changelog.read_text(encoding='utf-8').splitlines()
    for index, line in enumerate(lines):
        if heading.match(line) is None:
            continue
        rest = lines[index + 1:]
        body = rest[: next(
            (
                offset
                for offset, later in enumerate(rest)
                if next_heading.match(later) is not None
            ),
            len(rest),
        )]
        return '\n'.join(body).strip()

    return ''


def _validate(pyproject: Path, fragment_dir: Path) -> int:
    categories = known_categories(pyproject)
    if not categories:
        sys.stderr.write(
            f'{pyproject} declares no `[tool.towncrier]` categories, '
            'so every fragment name would be refused. Restore the '
            '`type` table rather than relaxing this check.\n',
        )
        return 1

    offenders = unrecognised_fragments(fragment_dir, categories)
    if offenders:
        sys.stderr.write(
            '`towncrier` would ignore these files without saying so, '
            'and the changes they describe would be missing from the '
            'release notes:\n'
            + ''.join(f'  {name}\n' for name in offenders)
            + 'A fragment is named `<issue>.<category>.md`, where '
            '`<issue>` is a number or `+` and something unique, and '
            '`<category>` is one of: '
            + ', '.join(sorted(categories))
            + f'. See {fragment_dir / _NOT_A_FRAGMENT}.\n',
        )
        return 1

    return 0


def _notes(
    pyproject: Path,
    changelog: Path,
    fragment_dir: Path,
    version: str,
) -> int:
    pending = pending_fragments(fragment_dir, known_categories(pyproject))
    if pending:
        sys.stderr.write(
            f'{fragment_dir} still holds fragments that no version '
            f'has collected, so the notes for {version} would be '
            'missing them:\n'
            + ''.join(f'  {name}\n' for name in pending)
            + 'Run `towncrier build` and commit the result before '
            'tagging.\n',
        )
        return 1

    notes = release_notes(changelog, version)
    if not notes:
        sys.stderr.write(
            f'{changelog} has no section for {version}. A release '
            'publishes what the changelog says about it, so there is '
            'nothing here to publish -- run `towncrier build '
            f'--version {version}` and commit the result before '
            'tagging.\n',
        )
        return 1

    sys.stdout.write(f'{notes}\n')
    return 0


def main(args: _c.Sequence[str]) -> int:
    """Validate the fragments, or print a version's release notes.

    :param args: ``validate <pyproject> <dir>``, or
        ``notes <pyproject> <changelog> <dir> <version>``.
    :returns: The exit code to leave with.
    """
    match args:
        case ['validate', pyproject, fragment_dir]:
            return _validate(Path(pyproject), Path(fragment_dir))
        case ['notes', pyproject, changelog, fragment_dir, version]:
            return _notes(
                Path(pyproject),
                Path(changelog),
                Path(fragment_dir),
                version,
            )
        case _:
            sys.stderr.write(
                'usage: _changelog.py validate <pyproject> <dir>\n'
                '       _changelog.py notes <pyproject> <changelog> '
                '<dir> <version>\n',
            )
            return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
