"""Verify the built dists ship every module the plugin executes.

``twine check`` reads a dist's metadata and never opens the package
inside it, and the sdist smoke test in CI imports one module out of
three. Neither notices a dist that dropped the two helper scripts
``lock-deps-check`` runs -- and those are the ones at risk, because
they are reached through the filesystem rather than through an import,
so the failure is a traceback in a user's CI rather than an
``ImportError`` anywhere here. The suite cannot catch it either: it
runs against an editable install, where the work tree *is* the
package.

Kept out of the shipped package because it checks the packaging rather
than doing any of the plugin's work, and named without the ``_test``
suffix so that ``pytest`` imports it for the tests beside it rather
than collecting it as one.
"""

from __future__ import annotations

import sys
import tarfile
import typing as _t
import zipfile
from pathlib import Path


if _t.TYPE_CHECKING:
    from collections import abc as _c


# NOTE: Patterns rather than a pair of file names because the version
# NOTE: is `setuptools-scm`'s to decide, and a `dist{/}` left over from
# NOTE: an earlier build legitimately holds several of each. Every dist
# NOTE: found is checked: one of them is what gets uploaded, and which
# NOTE: is not this script's business to guess.
_DIST_PATTERNS = ('*.whl', '*.tar.gz')


def _expected_modules(package_dir: Path) -> frozenset[str]:
    """List the modules a dist has to carry, as it would name them.

    Read off the work tree rather than enumerated here, so that a
    module extracted out of the plugin later is covered by this check
    without anybody remembering to add it.

    :param package_dir: The top-level package directory under ``src/``.
    :returns: Every module in it, named relative to the import root.
    """
    import_root = package_dir.parent
    return frozenset(
        module.relative_to(import_root).as_posix()
        for module in package_dir.rglob('*.py')
    )


def _members(dist_file: Path) -> _c.Sequence[str]:
    """Read the names of everything inside a dist.

    :param dist_file: The wheel or sdist to look into.
    :returns: The archive member names, as the archive spells them.
    """
    if dist_file.suffix == '.whl':
        with zipfile.ZipFile(dist_file) as wheel:
            return wheel.namelist()

    with tarfile.open(dist_file) as sdist:
        return sdist.getnames()


def _missing_from(dist_file: Path, modules: _c.Iterable[str]) -> list[str]:
    """Tell which of the given modules a dist does not carry.

    Matched on the tail of each member name rather than on the whole of
    it: a wheel names a module from the import root down, an sdist from
    a versioned directory holding the whole source tree, and neither
    prefix says anything about whether the module is there.

    :param dist_file: The wheel or sdist to look into.
    :param modules: The modules the dist is expected to carry.
    :returns: Those it does not, in a stable order.
    """
    members = _members(dist_file)
    return sorted(
        module
        for module in modules
        if not any(
            member == module or member.endswith(f'/{module}')
            for member in members
        )
    )


def _report(package_dir: Path, dist_dir: Path) -> _c.Iterator[str]:
    """Spell out what the dists in a directory fail to ship.

    :param package_dir: The top-level package directory under ``src/``.
    :param dist_dir: The directory the built dists were written to.
    :yields: The complaint lines, none at all if every dist is whole.
    """
    modules = _expected_modules(package_dir)
    if not modules:
        yield f'{package_dir} holds no module, so nothing was checked.'
        return

    for pattern in _DIST_PATTERNS:
        dist_files = sorted(dist_dir.glob(pattern))
        if not dist_files:
            yield f'{dist_dir} holds no {pattern} to check.'
            continue

        for dist_file in dist_files:
            missing = _missing_from(dist_file, modules)
            if missing:
                yield f'{dist_file} is missing {", ".join(missing)}.'


def main(args: _c.Sequence[str]) -> int:
    """Check that the built dists carry the whole package.

    :param args: The package directory and the directory of the dists.
    :returns: The exit code to leave with.
    """
    package_dir, dist_dir = map(Path, args)
    report = list(_report(package_dir, dist_dir))
    if not report:
        return 0

    sys.stderr.writelines(f'{line}\n' for line in report)
    sys.stderr.write(
        'A dist that drops a module the plugin runs by path fails only '
        'in a project that installed it -- rebuild with '
        '`tox run -e build-dists` and check what the packaging config '
        'now leaves out.\n',
    )
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
