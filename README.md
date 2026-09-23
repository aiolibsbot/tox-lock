[![SWUbanner]][SWUdocs]

[![tox-dev badge]][tox-dev]
[![GH Sponsors badge]][GH Sponsors URL]

[SWUbanner]:
https://raw.githubusercontent.com/vshymanskyy/StandWithUkraine/main/banner-direct-single.svg
[SWUdocs]:
https://github.com/vshymanskyy/StandWithUkraine/blob/main/docs/README.md

[tox-dev]: https://github.com/tox-dev
[tox-dev badge]:
https://img.shields.io/badge/project-yellow?label=tox-dev&labelColor=c3cc39&color=7f833e

[GH Sponsors badge]:
https://img.shields.io/badge/%40webknjaz-transparent?logo=githubsponsors&logoColor=%23EA4AAA&label=Sponsor&color=2a313c
[GH Sponsors URL]:
https://github.com/sponsors/webknjaz


# tox-lock

A tox plugin providing a pre-configured dependency locking toxenv,
backed by [uv].

[uv]: https://docs.astral.sh/uv


## Usage

Add `tox-lock` to your project's `tox` requirements -- either
in `tox.toml`:

```toml
requires = [
  "tox-lock",
]
```

...or in `tox.ini`:

```ini
[tox]
requires =
  tox-lock
```

Then invoke the env the plugin exposes:

```console
$ tox run -q -e lock-deps                     # write a hash-pinned requirements.txt
$ tox run -q -e lock-deps -- --upgrade        # pass args through to `uv pip compile`
$ tox run -q -e lock-deps -- --python 3.10    # lock for a specific interpreter
```

The lock is hash-pinned (`--generate-hashes`) and written whole on
every run, so there is no stale-artifact cleanup step to remember.

By default the lock is compiled out of `pyproject.toml` into
`requirements.txt`, both relative to the tox root. Projects that keep
theirs elsewhere say so in the core section rather than restating the
whole command:

```ini
[tox]
lock_input = requirements/base.in
lock_file = requirements/base.txt
```

`uv pip compile` compiles the union of any number of sources into one
lock, so a project splitting its requirements across several files
lists them all -- one per line in `tox.ini`, as an array in
`tox.toml`:

```ini
[tox]
lock_input =
  requirements/base.in
  requirements/test.in
```

The options `uv pip compile` is invoked with are settable the same
way. They default to `--generate-hashes`; a project that cannot pin
hashes -- one depending on a direct URL or an editable checkout --
opts out by emptying the setting rather than by rewriting the command:

```ini
[tox]
lock_options =
```

...and one wanting more of them lists them, one per line, value
included:

```ini
[tox]
lock_options =
  --generate-hashes
  --universal
  --custom-compile-command "tox run -e lock-deps"
```

Substitutions work in all three, as in any other core setting -- for
instance, `lock_file = {env:LOCK_FILE:requirements.txt}`.

One-off options do not need a config change at all -- pass them after
`--`, where they are appended last and so win over `lock_options`.

The plugin's defaults sit between the `[testenv]` base section and
your own env section: `[testenv]` settings never leak into this env,
while anything set in `[testenv:lock-deps]` (`[env.lock-deps]` in
`tox.toml`) wins, as does `-x testenv:lock-deps.<key>=...` -- whether
or not the project declares that section at all. Keys left unset keep
the plugin's defaults:

```ini
[testenv:lock-deps]
deps = pip-tools
commands = pip-compile --generate-hashes -o requirements.txt pyproject.toml
```
