"""Behavioral tests for the dist-contents check."""

from __future__ import annotations

import contextlib
import io
import tarfile
import typing as _t
import zipfile
from pathlib import Path

import pytest

from _dist_contents import main as verify_dist_contents


if _t.TYPE_CHECKING:
    from collections import abc as _c


_MODULES = ('_plugin.py', '_check_seed.py', '_check_compare.py')


class _CheckResult(_t.NamedTuple):
    """What running the check leaves behind."""

    returncode: int
    stderr: str


def _make_package(tmp_path: Path, *modules: str) -> Path:
    """Lay out a source tree the check can read its expectations off.

    :param tmp_path: The directory to build the tree under.
    :param modules: The module file names to put in the package.
    :returns: The top-level package directory, as ``src/`` holds it.
    """
    package_dir = tmp_path / 'src' / 'tox_plugins' / 'lock'
    package_dir.mkdir(parents=True)
    for module in modules:
        (package_dir / module).write_text('', encoding='utf-8')

    return package_dir.parent


def _make_dists(dist_dir: Path, *members: str) -> None:
    """Build a wheel and an sdist holding the given members.

    The two are written with the prefixes the real ones carry -- a
    wheel names a module from the import root, an sdist from a
    versioned directory -- because telling those apart is most of what
    the check does.

    :param dist_dir: The directory to write the dists into.
    :param members: The module paths, relative to the import root.
    """
    dist_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dist_dir / 'tox_lock-1.0-py3-none-any.whl', 'w') as w:
        for member in members:
            w.writestr(member, '')

    with tarfile.open(dist_dir / 'tox_lock-1.0.tar.gz', 'w:gz') as sdist:
        for member in members:
            source = dist_dir / Path(member).name
            source.write_text('', encoding='utf-8')
            sdist.add(source, arcname=f'tox_lock-1.0/src/{member}')
            source.unlink()


def _run(*args: Path) -> _CheckResult:
    """Run the check the way the ``verify-dists`` env would.

    :param args: The paths to pass to it.
    :returns: The exit code it left with and what it wrote to stderr.
    """
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        returncode = verify_dist_contents([str(arg) for arg in args])

    return _CheckResult(returncode, stderr.getvalue())


def _shipped(*modules: str) -> _c.Iterator[str]:
    """Name some package modules the way a dist's members name them.

    :param modules: The module file names.
    :yields: Each of them, relative to the import root.
    """
    for module in modules:
        yield f'tox_plugins/lock/{module}'


def test_whole_dists_pass(tmp_path: Path) -> None:
    """Dists carrying every module of the package are accepted.

    :param tmp_path: Pytest's temporary directory fixture.
    """
    package_dir = _make_package(tmp_path, *_MODULES)
    dist_dir = tmp_path / 'dist'
    _make_dists(dist_dir, *_shipped(*_MODULES))

    assert _run(package_dir, dist_dir) == _CheckResult(0, '')


def test_a_dropped_module_is_named(tmp_path: Path) -> None:
    """A dist built without one of the modules fails, naming it.

    :param tmp_path: Pytest's temporary directory fixture.
    """
    package_dir = _make_package(tmp_path, *_MODULES)
    dist_dir = tmp_path / 'dist'
    _make_dists(dist_dir, *_shipped('_plugin.py'))

    check_result = _run(package_dir, dist_dir)

    assert check_result.returncode == 1
    assert '_check_seed.py' in check_result.stderr
    assert '_check_compare.py' in check_result.stderr
    assert '.whl is missing' in check_result.stderr
    assert '.tar.gz is missing' in check_result.stderr


def test_a_similarly_named_member_does_not_count(tmp_path: Path) -> None:
    """A member whose name merely ends the same way is not the module.

    :param tmp_path: Pytest's temporary directory fixture.
    """
    package_dir = _make_package(tmp_path, '_plugin.py')
    dist_dir = tmp_path / 'dist'
    _make_dists(dist_dir, 'elsewhere/lock/_plugin.py')

    assert _run(package_dir, dist_dir).returncode == 1


@pytest.mark.parametrize(
    'kept',
    ('*.whl', '*.tar.gz'),
    ids=('only-a-wheel', 'only-an-sdist'),
)
def test_a_missing_dist_kind_fails(tmp_path: Path, kept: str) -> None:
    """Half a build is a failure, not a check of the half that is there.

    :param tmp_path: Pytest's temporary directory fixture.
    :param kept: The glob of the dist kind left in place.
    """
    package_dir = _make_package(tmp_path, '_plugin.py')
    dist_dir = tmp_path / 'dist'
    _make_dists(dist_dir, *_shipped('_plugin.py'))
    for dist_file in dist_dir.iterdir():
        if not dist_file.match(kept):
            dist_file.unlink()

    check_result = _run(package_dir, dist_dir)

    assert check_result.returncode == 1
    assert 'holds no ' in check_result.stderr


def test_an_empty_package_is_not_silently_whole(tmp_path: Path) -> None:
    """Nothing to look for means the check proved nothing.

    :param tmp_path: Pytest's temporary directory fixture.
    """
    package_dir = _make_package(tmp_path)
    dist_dir = tmp_path / 'dist'
    _make_dists(dist_dir)

    check_result = _run(package_dir, dist_dir)

    assert check_result.returncode == 1
    assert 'nothing was checked' in check_result.stderr
