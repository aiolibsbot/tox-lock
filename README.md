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


## Keeping the lock honest

A lock is only worth as much as the last time somebody remembered to
recompile it. The plugin exposes a second env for CI to say so out
loud:

```console
$ tox run -q -e lock-deps-check
```

It recompiles the same sources with the same options into a scratch
file under the tox temp dir, compares the result against your lock,
and exits non-zero if they differ. Your lock file is never written to,
so a failing check tells you to run `lock-deps` -- it does not quietly
do it for you on a machine that was only meant to be looking.

The comparison ignores comment lines, `uv`'s header among them: it
names the command that produced the file, `--output-file` included,
which is the one argument the check is obliged to change.

A failing check prints a unified diff of the pins that moved, so the
CI log that reports the staleness also says what it consists of:

```diff
--- requirements.txt (locked)
+++ requirements.txt (recompiled)
@@ -1,2 +1,3 @@
-attrs==24.2.0
+attrs==25.1.0
 idna==3.10
+sniffio==1.3.1
```

The recompile starts from a copy of the current lock, so the check
reports *drift* -- your lock no longer matching the sources it claims
to come from -- rather than the mere existence of a newer release
upstream. To ask that other question, pass the arguments for it:

```console
$ tox run -q -e lock-deps-check -- --upgrade   # would upgrading change anything?
```


## Using the lock

Installing from the lock needs nothing from this plugin -- `tox` already
takes a requirements file, and the path is the one you configured:

```ini
[testenv]
deps = -r {[tox]lock_file}
```

The reference resolves whether or not the project ever wrote
`lock_file` down, so an env installing from the default lock names it
once, here, instead of owning `requirements.txt` in two places.

An env that would rather not run against a stale lock at all says so
the ordinary way:

```ini
[testenv]
depends = lock-deps-check
deps = -r {[tox]lock_file}
```


## Configuration

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

The resolver itself is an input to the lock as much as the sources
are: two `uv` releases can pin the same requirements differently, and
a check running a newer `uv` than the machine that wrote the lock
reports drift that is not there. Projects that would rather decide
when that happens pin it once, for both envs:

```ini
[tox]
lock_uv = uv == 0.9.2
```

The interpreter is an input of the same kind. `uv pip compile`
resolves for the Python it runs under, so the same sources compiled on
3.11 and on 3.13 legitimately differ, and a check run under one while
the lock was written under the other reports drift that is not there.
Left unset, both envs use whichever Python is running `tox`; naming it
fixes both at once:

```ini
[tox]
lock_python = py312
```

Substitutions work in all five, as in any other core setting -- for
instance, `lock_file = {env:LOCK_FILE:requirements.txt}`.

One-off options do not need a config change at all -- pass them after
`--`, where they are appended last and so win over `lock_options`.

Both envs read the same five core settings, so a project configures
its lock once and the check follows.

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
