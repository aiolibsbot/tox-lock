"""Tests pinning what a lock does not cover while the package is built.

``tox`` installs a packaged project in two ``pip`` invocations, and a
lock governs the first of them -- that much the README already says.
There is a third, and it runs before either: the packaging env
installs whatever ``[build-system] requires`` names, so that the
backend the other two depend on exists at all.

Nothing this plugin writes reaches it. ``constrain_package_deps`` is
read only where the *package's* metadata dependencies are installed,
and ``deps`` -- the key a lock is ordinarily carried on -- ``tox``
refuses outright on a PEP-517 packaging env, because the requirements
there are the backend's to declare. So a project whose every lock is
hash-pinned still resolves its build backend against the index, on
every machine, with nothing said about it.

``constraints`` is the way in, and it is the same way in the ``pylock``
section already documents: applied wherever a list of requirements is
installed, which includes this one. Every claim here is about ``tox``
rather than about this plugin, which is why they are worth pinning --
the README's advice is only true while they hold, and nothing in this
suite reads the README.
"""

from __future__ import annotations

import typing as _t


if _t.TYPE_CHECKING:
    from tox.execute.request import ExecuteRequest
    from tox.pytest import ToxProject, ToxProjectCreator

import pytest


# NOTE: What `[build-system] requires` names, and the pin a constraint
# NOTE: would hold it to. Never actually installed: the invocation that
# NOTE: would is the one under test, and it is reported as having
# NOTE: succeeded rather than run -- the backend below imports nothing
# NOTE: but the standard library, so its declared requirement exists to
# NOTE: be constrained and for no other reason. Nothing here reaches an
# NOTE: index.
_BUILD_REQUIREMENT = 'attrs'
_CONSTRAINED_VERSION = '25.3.0'
_CONSTRAINTS = f'{_BUILD_REQUIREMENT}=={_CONSTRAINED_VERSION}\n'
_CONSTRAINTS_NAME = 'constraints.txt'

_PACKAGE_NAME = 'demo_pkg'
_PACKAGE_VERSION = '1.0.0'
_DIST_INFO = f'{_PACKAGE_NAME}-{_PACKAGE_VERSION}.dist-info'
_BACKEND_MODULE = 'demo_backend'

# NOTE: A build backend written out here rather than a real one
# NOTE: installed from an index, so that the test costs a `zipfile`
# NOTE: write instead of a download. It is reached through
# NOTE: `backend-path`, which puts the project root on the backend's
# NOTE: import path, and it uses the standard library alone -- which is
# NOTE: what lets the install of its declared requirement be skipped
# NOTE: while every backend hook still runs for real.
_BACKEND = f'''\
"""A PEP 517 backend that needs nothing but the standard library."""

from __future__ import annotations

import zipfile


_WHEEL_NAME = '{_PACKAGE_NAME}-{_PACKAGE_VERSION}-py3-none-any.whl'


def get_requires_for_build_wheel(config_settings=None):
    """Report that building needs nothing beyond `[build-system]`."""
    return []


def build_wheel(
    wheel_directory, config_settings=None, metadata_directory=None
):
    """Write the smallest wheel `pip` will install."""
    with zipfile.ZipFile(f'{{wheel_directory}}/{{_WHEEL_NAME}}', 'w') as whl:
        whl.writestr(
            '{_DIST_INFO}/METADATA',
            'Metadata-Version: 2.1\\n'
            'Name: {_PACKAGE_NAME}\\n'
            'Version: {_PACKAGE_VERSION}\\n',
        )
        whl.writestr(
            '{_DIST_INFO}/WHEEL',
            'Wheel-Version: 1.0\\n'
            'Generator: tests.build_requires_test\\n'
            'Root-Is-Purelib: true\\n'
            'Tag: py3-none-any\\n',
        )
        whl.writestr('{_DIST_INFO}/RECORD', '')

    return _WHEEL_NAME
'''

_PYPROJECT = f"""\
[build-system]
requires = ["{_BUILD_REQUIREMENT}"]
backend-path = ["."]
build-backend = "{_BACKEND_MODULE}"

[project]
name = "{_PACKAGE_NAME}"
version = "{_PACKAGE_VERSION}"
dependencies = []
"""

_TOX_INI = """\
[testenv]
package = wheel
constrain_package_deps = true
commands =
"""

_PKGENV_CONSTRAINED = f"""\

[pkgenv]
constraints = {{tox_root}}/{_CONSTRAINTS_NAME}
"""

# NOTE: A requirement `tox` can parse, so that the refusal under test
# NOTE: is its own rather than a parse error on the way to it.
_PKGENV_DEPS = f"""\

[pkgenv]
deps = {_BUILD_REQUIREMENT}
"""

# NOTE: The `run_id` tox gives the invocation that installs
# NOTE: `[build-system] requires` into the packaging env.
_BUILD_REQUIRES_RUN_ID = 'install_requires'

_CONSTRAINT_OPTION = '-c'

# NOTE: `tox`'s own wording, quoted so that a rewrite of it here reads
# NOTE: as the upstream change it would be.
_PKGENV_DEPS_REFUSED = 'does not support the deps configuration'


@pytest.fixture
def build_project(
    tox_project: ToxProjectCreator,
) -> _t.Callable[[str], ToxProject]:
    """Hand back a factory for projects differing only in `[pkgenv]`.

    A factory rather than a project because ``pkgenv`` configures the
    one packaging env a run has, so the shapes under test cannot be
    envs of a single project.

    :param tox_project: Tox-provided project factory fixture.
    :returns: A callable taking the ``[pkgenv]`` section to append.
    """

    def make(pkgenv_section: str = '') -> ToxProject:
        """Write a project whose backend declares one requirement.

        :param pkgenv_section: Extra ``tox.ini`` text, appended as-is.
        :returns: The project, ready to run.
        """
        return tox_project({
            'tox.ini': _TOX_INI + pkgenv_section,
            'pyproject.toml': _PYPROJECT,
            f'{_BACKEND_MODULE}.py': _BACKEND,
            _CONSTRAINTS_NAME: _CONSTRAINTS,
        })

    return make


def _build_requires_command(project: ToxProject) -> list[str]:
    """Run a project and hand back how it installed its build requires.

    Only that one invocation is replaced; every backend hook and the
    install of the wheel it produces run for real, so the command
    asserted on is the one ``tox`` assembles on a working run rather
    than one salvaged from a failure.

    :param project: The project to run in.
    :returns: The arguments of the build-requirement install.
    """
    requests: list[ExecuteRequest] = []

    def record(request: ExecuteRequest) -> int | None:
        """Note the install down and report it as having succeeded.

        :param request: The command ``tox`` asked to run.
        :returns: Zero to stand in for the install, else :data:`None`.
        """
        if request.run_id != _BUILD_REQUIRES_RUN_ID:
            return None

        requests.append(request)
        return 0

    project.patch_execute(record)

    tox_invocation_result = project.run('run', '-e', 'py')

    tox_invocation_result.assert_success()
    return next(list(request.cmd) for request in requests)


def _names_a_constraint(command: list[str]) -> bool:
    """Tell whether a ``pip`` invocation was given a constraints file.

    Both spellings ``tox`` produces count: the option glued to the path
    it writes itself, and the two as separate arguments, which is what
    a configured ``constraints`` entry arrives as.

    :param command: The command arguments to look through.
    :returns: :data:`True` if a constraint is named, :data:`False` if not.
    """
    return any(arg.startswith(_CONSTRAINT_OPTION) for arg in command)


def test_the_guard_does_not_reach_a_build_requirement(
    build_project: _t.Callable[[str], ToxProject],
) -> None:
    """Check that ``constrain_package_deps`` still misses the backend.

    The hazard the README documents. The env under test has the guard
    switched on, and the invocation installing the backend is still
    handed nothing: the guard is read where the *package's* metadata
    dependencies are installed, and this runs before the package
    exists.

    :param build_project: A factory for projects differing in `[pkgenv]`.
    """
    command = _build_requires_command(build_project(''))

    assert _BUILD_REQUIREMENT in command
    assert not _names_a_constraint(command)


def test_constraints_reach_a_build_requirement(
    build_project: _t.Callable[[str], ToxProject],
) -> None:
    """Check that the documented way in still works.

    ``constraints`` is applied wherever a list of requirements is
    installed, and the packaging env's own requirements are such a
    list, which is why a lock named there pins the backend.

    :param build_project: A factory for projects differing in `[pkgenv]`.
    """
    command = _build_requires_command(build_project(_PKGENV_CONSTRAINED))

    assert _BUILD_REQUIREMENT in command
    assert _names_a_constraint(command)


def test_deps_are_refused_on_the_packaging_env(
    build_project: _t.Callable[[str], ToxProject],
) -> None:
    """Check that the packaging env still has no ``deps`` of its own.

    Which is why the section is worth writing at all: the key every
    other env carries its lock on is not available here, so a project
    cannot arrive at a pinned backend the ordinary way.

    :param build_project: A factory for projects differing in `[pkgenv]`.
    """
    tox_invocation_result = build_project(_PKGENV_DEPS).run('run', '-e', 'py')

    tox_invocation_result.assert_failed()
    assert _PKGENV_DEPS_REFUSED in tox_invocation_result.out
