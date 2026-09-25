"""Tests pinning what a lock does not cover on the PEP 751 path.

``tox-lock`` writes a `PEP 751`_ lock whenever the name in
``lock_files`` asks for one, and a project installing from it does not
use ``deps`` -- ``tox`` has a key of its own, and refuses an env naming
both. That second install path is where the guard the README tells
every project to write stops working.

``constrain_package_deps`` is read at the moment the *package's* own
metadata dependencies are installed, and what it reads is a constraints
file ``tox`` writes while installing ``deps``. A ``pylock`` env never
installs ``deps``, so the file is never there, so the option is a no-op
that says nothing about being one. The env resolves the project's own
``dependencies`` against the index with the lock in hand and unread.

Every claim here is about ``tox`` rather than about this plugin, which
is why they are worth pinning: the README's advice is only true while
they hold, and nothing in this suite reads the README. The remedy it
documents -- a requirements-format lock compiled beside the
``pylock.toml`` and named in ``constraints`` -- is pinned alongside
them, because it is the half a reader is asked to act on.

.. _PEP 751: https://peps.python.org/pep-0751/
"""

from __future__ import annotations

import typing as _t
import zipfile
from pathlib import Path


if _t.TYPE_CHECKING:
    from tox.execute.request import ExecuteRequest
    from tox.pytest import ToxProject, ToxProjectCreator

import pytest


# NOTE: A pin no source in this project could produce, standing in for
# NOTE: a lock written before the package's metadata moved past it. The
# NOTE: hash is real -- `uv` writes one for every pin by default -- so
# NOTE: that the lock read here is the shape this plugin produces.
_LOCKED_VERSION = '25.3.0'
_HASH_ALGORITHM = 'sha256'
_LOCKED_DIGEST = (
    '427318ce031701fea540783410126f03899a97ffc6f61596ad581ac2e40e3bc3'
)
_REQUIREMENTS_LOCK = (
    f'attrs=={_LOCKED_VERSION} \\\n'
    f'    --hash={_HASH_ALGORITHM}:{_LOCKED_DIGEST}\n'
)

# NOTE: What the package's own metadata asks for, chosen to exclude the
# NOTE: pin above: an unconstrained second invocation resolves this and
# NOTE: installs something the lock does not name, which is the whole
# NOTE: subject. Never actually resolved -- execution is mocked -- so
# NOTE: nothing here reaches an index.
_PACKAGE_REQUIREMENT = 'attrs>=26'

# NOTE: The smallest document `packaging` accepts as a PEP 751 lock,
# NOTE: holding the same pin as the requirements lock above so that the
# NOTE: two envs differ in nothing but how they install it. Written in
# NOTE: TOML's expanded table form rather than the inline one `uv`
# NOTE: emits, because an inline table may not span lines and a wheel
# NOTE: URL beside a hash does not fit on one. The URL points nowhere:
# NOTE: the install command is captured rather than run.
_PYLOCK = f"""\
lock-version = "1.0"
created-by = "uv"
requires-python = ">=3.10"

[[packages]]
name = "attrs"
version = "{_LOCKED_VERSION}"

[[packages.wheels]]
url = "https://example.invalid/attrs-{_LOCKED_VERSION}-py3-none-any.whl"

[packages.wheels.hashes]
{_HASH_ALGORITHM} = "{_LOCKED_DIGEST}"
"""

_REQUIREMENTS_LOCK_NAME = 'requirements.txt'
_PYLOCK_NAME = 'pylock.toml'

_TOX_INI = f"""\
[testenv:from-requirements]
deps = -r {_REQUIREMENTS_LOCK_NAME}
constrain_package_deps = true

[testenv:from-pylock]
pylock = {_PYLOCK_NAME}
constrain_package_deps = true

[testenv:from-pylock-constrained]
pylock = {_PYLOCK_NAME}
constrain_package_deps = true
constraints = {{tox_root}}/{_REQUIREMENTS_LOCK_NAME}

[testenv:both]
deps = -r {_REQUIREMENTS_LOCK_NAME}
pylock = {_PYLOCK_NAME}
"""

# NOTE: The `run_id` tox gives the invocation installing the package's
# NOTE: own metadata dependencies -- the second of the two, and the one
# NOTE: the guard is about.
_PACKAGE_DEPS_RUN_ID = 'install_package_deps'

_CONSTRAINT_OPTION = '-c'

# NOTE: `tox`'s own wording, quoted so that a rewrite of it here reads
# NOTE: as the upstream change it would be.
_BOTH_KEYS_REFUSED = (
    "cannot use both 'deps' and 'pylock' in the same environment"
)

_PACKAGE_NAME = 'demo_pkg'
_PACKAGE_VERSION = '1.0.0'
_DIST_INFO = f'{_PACKAGE_NAME}-{_PACKAGE_VERSION}.dist-info'
_WHEEL_NAME = f'{_PACKAGE_NAME}-{_PACKAGE_VERSION}-py3-none-any.whl'


@pytest.fixture
def lock_project(tox_project: ToxProjectCreator) -> ToxProject:
    """Build a project holding the same pins in both lock formats.

    :param tox_project: Tox-provided project factory fixture.
    :returns: A project with an env per install shape under test.
    """
    return tox_project({
        'tox.ini': _TOX_INI,
        _REQUIREMENTS_LOCK_NAME: _REQUIREMENTS_LOCK,
        _PYLOCK_NAME: _PYLOCK,
    })


def _prebuilt_wheel(at: Path) -> Path:
    """Write a wheel declaring one dependency and nothing else.

    Handed to ``tox`` as ``--installpkg`` rather than built from a
    source tree, and assembled with :mod:`zipfile` rather than by a
    build backend. Both follow from execution being mocked: a real
    build needs a backend installed into the packaging env by the very
    ``pip`` invocations this test replaces, and what is under test is
    how the *metadata* dependency of an already-built distribution is
    installed. A hand-written ``METADATA`` is the whole input.

    :param at: The directory to write the wheel into.
    :returns: The path of the wheel written.
    """
    wheel = at / _WHEEL_NAME
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.writestr(
            f'{_DIST_INFO}/METADATA',
            f'Metadata-Version: 2.1\n'
            f'Name: {_PACKAGE_NAME}\n'
            f'Version: {_PACKAGE_VERSION}\n'
            f'Requires-Dist: {_PACKAGE_REQUIREMENT}\n',
        )
        archive.writestr(
            f'{_DIST_INFO}/WHEEL',
            'Wheel-Version: 1.0\n'
            'Generator: tests.pylock_install_test\n'
            'Root-Is-Purelib: true\n'
            'Tag: py3-none-any\n',
        )
        archive.writestr(f'{_DIST_INFO}/RECORD', '')

    return wheel


def _package_deps_command(project: ToxProject, env_name: str) -> list[str]:
    """Run one env and hand back how it installed the package's deps.

    Every command the env would run is captured instead of run, so the
    assertion is about the ``pip`` invocation ``tox`` assembles and
    nothing is installed or downloaded.

    :param project: The project to run in.
    :param env_name: The name of the env to run.
    :returns: The arguments of the package-dependency install.
    """
    requests: list[ExecuteRequest] = []

    def record(request: ExecuteRequest) -> int:
        """Note one command down and report it as having succeeded.

        :param request: The command ``tox`` asked to run.
        :returns: The exit code the mocked execution reports.
        """
        requests.append(request)
        return 0

    project.patch_execute(record)

    tox_invocation_result = project.run(
        'run',
        '-e',
        env_name,
        '--installpkg',
        str(_prebuilt_wheel(Path(project.path))),
    )

    tox_invocation_result.assert_success()
    return next(
        list(request.cmd)
        for request in requests
        if request.run_id == _PACKAGE_DEPS_RUN_ID
    )


def _names_a_constraint(command: list[str]) -> bool:
    """Tell whether a ``pip`` invocation was given a constraints file.

    Both spellings ``tox`` produces count: the option glued to the path
    it writes itself, and the two as separate arguments, which is what
    a configured ``constraints`` entry arrives as.

    :param command: The command arguments to look through.
    :returns: :data:`True` if a constraint is named, :data:`False` if not.
    """
    return any(arg.startswith(_CONSTRAINT_OPTION) for arg in command)


def test_the_guard_reaches_a_requirements_install(
    lock_project: ToxProject,
) -> None:
    """Check that the guard still constrains a ``deps`` env.

    The control for the two below, and the claim the previous README
    section rests on: the lock's own pins reach the second invocation,
    so metadata that has outgrown them is a resolution error.

    :param lock_project: A project with a lock in either format.
    """
    command = _package_deps_command(lock_project, 'from-requirements')

    assert _PACKAGE_REQUIREMENT in command
    assert _names_a_constraint(command)


def test_the_guard_does_not_reach_a_pylock_install(
    lock_project: ToxProject,
) -> None:
    """Check that the guard is still inert on a ``pylock`` env.

    The hazard the README documents. It exists only while this holds:
    if ``tox`` starts writing the constraints file on this path too,
    the section saying to reach for ``constraints`` instead is
    describing a version nobody runs.

    :param lock_project: A project with a lock in either format.
    """
    command = _package_deps_command(lock_project, 'from-pylock')

    assert _PACKAGE_REQUIREMENT in command
    assert not _names_a_constraint(command)


def test_constraints_reach_a_pylock_install(
    lock_project: ToxProject,
) -> None:
    """Check that the documented way in still works.

    ``constraints`` is applied wherever a list of requirements is
    installed, the package's own metadata dependencies included, which
    is why a requirements-format lock compiled beside the
    ``pylock.toml`` closes the hole the test above leaves open.

    :param lock_project: A project with a lock in either format.
    """
    command = _package_deps_command(lock_project, 'from-pylock-constrained')

    assert _PACKAGE_REQUIREMENT in command
    assert _names_a_constraint(command)


def test_naming_both_deps_and_a_pylock_is_refused(
    lock_project: ToxProject,
) -> None:
    """Check that the two install keys are still mutually exclusive.

    Which is why the section is worth writing at all: a project moving
    to a ``pylock.toml`` cannot keep the ``deps`` line that used to
    carry its lock, so it cannot arrive at the guarded shape by
    accident.

    :param lock_project: A project with a lock in either format.
    """
    tox_invocation_result = lock_project.run('run', '-e', 'both')

    tox_invocation_result.assert_failed()
    assert _BOTH_KEYS_REFUSED in tox_invocation_result.out
