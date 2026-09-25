"""Tests pinning what a lock does not cover.

The README tells a project installing from a lock that ``deps`` is not
the whole install: ``tox`` resolves the ``dependencies`` a packaged
project's own metadata declares in a second ``pip`` invocation, against
the index, with neither the lock's pins nor its hashes in hand. That
advice rests on one claim about ``tox`` and one about this project.

The ``tox`` claim is that the guard for it ships off. It is the kind
that flips without anyone noticing here -- a default changed upstream
leaves the README warning about a hazard that no longer exists, and
nothing in this suite reads the README.

The claim about this project is that the guard is on. Its own locks
cover ``tox`` and ``packaging`` today only because ``requirements/*.in``
happen to name them; the pin that matters most is ``oldest-tox``'s,
whose whole purpose is to hold ``tox`` at the declared floor while
``pyproject.toml`` asks for at least it. An unconstrained second
invocation is free to step over that, and a suite running against a
newer ``tox`` than the env promises is green.
"""

from __future__ import annotations

import configparser
import typing as _t
from pathlib import Path

import pytest


if _t.TYPE_CHECKING:
    from tox.pytest import ToxProjectCreator


_REPO_ROOT = Path(__file__).parents[1]
_TOX_INI = _REPO_ROOT / 'tox.ini'

_SETTING = 'constrain_package_deps'

# NOTE: The section every env installing this package inherits. The
# NOTE: plugin's own envs do not: they are seeded with `package = skip`
# NOTE: and an empty `base`, so `[testenv]` never reaches them and there
# NOTE: is no second invocation there to constrain.
_INHERITED_SECTION = 'testenv'


def _own_settings(tox_ini: Path) -> dict[str, bool | None]:
    """Read every section's own say on constraining package deps.

    Sections that leave the key unset are left out rather than reported
    as :data:`False`: not saying is how an env inherits the answer, and
    a scan that conflated the two would read the whole file as one long
    refusal.

    The value is typed as optional because ``getboolean`` reports a
    missing key that way; the filter above means it never is.

    :param tox_ini: The ``tox.ini`` to read.
    :returns: The value each section that names the setting gives it.
    """
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(tox_ini.read_text(encoding='utf-8'))
    return {
        section: parser[section].getboolean(_SETTING, fallback=None)
        for section in parser.sections()
        if parser.has_option(section, _SETTING)
    }


def test_the_guard_ships_off(tox_project: ToxProjectCreator) -> None:
    """Check that ``tox`` still leaves package deps unconstrained.

    The hazard the README documents exists only while this is so. If a
    later ``tox`` turns the setting on by default, the warning is
    describing a version nobody runs and the section saying to write the
    line by hand should go with it.

    Asserted through ``config`` rather than an install, so nothing here
    reaches an index.

    :param tox_project: Tox-provided project factory fixture.
    """
    config_files: dict[str, str] = {
        'tox.ini': '[testenv:app]\n',
        'pyproject.toml': '[project]\nname = "demo"\nversion = "1.0.0"\n',
    }
    project = tox_project(config_files)

    tox_invocation_result = project.run('config', '-e', 'app')

    tox_invocation_result.assert_success()
    assert f'{_SETTING} = False' in tox_invocation_result.out


def test_this_project_constrains_its_package_deps() -> None:
    """Check that the env every installing env inherits sets the guard.

    Without it, the second invocation resolves this plugin's own
    ``tox``, ``packaging`` and ``tomli`` requirements against the index
    and may satisfy them with something no lock here names.
    """
    assert _own_settings(_TOX_INI).get(_INHERITED_SECTION) is True


def test_no_env_takes_the_guard_back_off() -> None:
    """Check that no env section undoes what ``[testenv]`` settled.

    A section wins a key outright in tox, so one env opting out is one
    env installing past its lock -- and it would read as a local detail
    rather than the hole it is.
    """
    assert all(_own_settings(_TOX_INI).values())


@pytest.mark.parametrize('value', ('false', 'False', '0', 'no'))
def test_an_env_opting_out_is_seen(tmp_path: Path, value: str) -> None:
    """Check that the scan notices a section turning the guard off.

    The two assertions above are satisfied by a file this reader cannot
    read, so it is made to fail on one that says the wrong thing --
    every spelling ``configparser`` takes for it, since the boolean is
    the whole subject.

    :param tmp_path: Pytest's per-test directory fixture.
    :param value: The falsy spelling the env section uses.
    """
    tox_ini = tmp_path / 'tox.ini'
    tox_ini.write_text(
        f'[testenv]\n{_SETTING} = true\n'
        f'[testenv:lax]\n{_SETTING} = {value}\n',
        encoding='utf-8',
    )

    assert not all(_own_settings(tox_ini).values())


def test_an_unset_key_is_not_read_as_a_refusal(tmp_path: Path) -> None:
    """Check that an env inheriting the guard is not reported as off.

    Most sections in this project's ``tox.ini`` never name the setting.
    A reader that returned :data:`False` for them would redden
    everything and stop telling anyone anything.

    :param tmp_path: Pytest's per-test directory fixture.
    """
    tox_ini = tmp_path / 'tox.ini'
    tox_ini.write_text(
        f'[testenv]\n{_SETTING} = true\n[testenv:quiet]\ndeps =\n',
        encoding='utf-8',
    )

    assert _own_settings(tox_ini) == {'testenv': True}
