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


## Requirements

`tox >= 4.55.1`. The plugin is built on the `tox_extend_envs` hook
(v4.30) and on core config declared as a mapping of lists (v4.31), but
it reads `tox`'s override map through the accessor that became public in
v4.55.1 -- which is how `-x testenv:lock-deps.deps=...` reaches an env
nobody wrote a section for.

One thing arrives later still: `tox` only began expanding the
substitutions inside an override's *value* in v4.62.0, so
`-x testenv:lock-deps.deps={env:LOCK_PIN}` keeps its braces under
anything older. That is `tox`'s own behaviour for every env rather than
this plugin's, so it is not part of the requirement above -- a project
meets it the same way whichever env it overrides.

CI runs the whole test suite against that floor, not just against
whatever `tox` is newest, in an `oldest-tox` env that pins it.


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

Naming it there rather than only installing it matters: `tox` does not
refuse a config whose plugin is missing. It ignores the core settings it
does not recognise and, for an env no section declares, runs `[testenv]`
under that name instead -- so `tox run -e lock-deps-check` would report
success having run whatever the default env does.

Then invoke the env the plugin exposes:

```console
$ tox run -q -e lock-deps                     # write a hash-pinned requirements.txt
$ tox run -q -e lock-deps -- --upgrade        # pass args through to `uv pip compile`
$ tox run -q -e lock-deps -- --python 3.10    # lock for a specific interpreter
$ tox run -q -e lock-deps --lock-file requirements/test.txt   # just the one lock
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

Each env carries a label of its own -- `lock` and `lock-check` -- so a
CI job or a `depends` line names something renameable rather than an
env name it has to keep in step with this plugin:

```console
$ tox run -q -m lock-check
```

The two are deliberately *not* grouped under one label: one writes the
lock and the other asserts that writing it would change nothing, so a
label selecting both picks a pair whose second half its first has
already made vacuous -- and under `tox run-parallel` the writer would
be rewriting the file the checker is reading.

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

Every configured lock is compared by one invocation rather than one
each, so a project with several of them learns about all the drift in
a single run -- `commands` stop at the first failure, and a comparison
per lock would report the earliest stale one and say nothing about the
rest.

A lock that will not compile at all is a different matter, and the two
envs part company over it. `lock-deps` carries on: the locks are
independent artefacts, so a source `uv` cannot resolve fails the run
without costing you the ones after it -- otherwise a scheduled
`lock-deps -- --upgrade` job would report one failure a week and
quietly renew nothing. `lock-deps-check` stops instead. It recompiles
into a copy of your lock, so a compile that never ran leaves a scratch
file identical to the lock it was copied from, and carrying on would
have the comparison report the one lock it could not recompile as
current. A source that will not compile is a broken configuration
rather than drift, `uv` names the file, and the check declines to
vouch for what it did not check.

That asymmetry is a seeded default on the writer and a fixture of the
checker. A project preferring the first failure to end the run says
so the ordinary way:

```ini
[testenv:lock-deps]
ignore_errors = false
```

...and saying the opposite there does not reach the check, which
inherits that section for everything except what this plugin owns.

The recompile starts from a copy of the current lock, so the check
reports *drift* -- your lock no longer matching the sources it claims
to come from -- rather than the mere existence of a newer release
upstream. To ask that other question, pass the arguments for it:

```console
$ tox run -q -e lock-deps-check -- --upgrade   # would upgrading change anything?
```


## What the lock says about itself

`uv` opens every lock it writes with a header naming the command that
produced it, so that whoever finds the file later knows how to
regenerate it. Left to itself it would name the invocation this plugin
builds -- a `python -Werror -m uv pip compile` line, going around the
pinned `uv`, the passed-through index configuration and every setting
above -- and, in the check env, one pointed at a scratch file under the
tox temp dir. Both envs therefore name the env instead:

```python
# This file was autogenerated by uv via the following command:
#    tox run -e lock-deps
```

A project that regenerates its lock through something else of its own
says so, and the seeded header steps aside rather than duplicating the
option, which `uv` refuses outright:

```ini
[tox]
lock_options = --custom-compile-command "make lock"
```


## Using the lock

Installing from a lock needs nothing from this plugin -- `tox` already
takes a requirements file:

```ini
[testenv]
deps = -r requirements.txt
```

A project that would rather name the path once gives it a section of
its own and references it from both ends, which is stock tox:

```ini
[tox]
lock_files = {[lock]test} = requirements/test.in

[lock]
test = requirements/test.txt

[testenv]
deps = -r {[lock]test}
```

An env that would rather not run against a stale lock at all says so
the ordinary way:

```ini
[testenv]
depends = lock-deps-check
deps = -r {[lock]test}
```


## Configuration

By default the lock is compiled out of `pyproject.toml` into
`requirements.txt`, both relative to the tox root. Projects that keep
theirs elsewhere say so in the core section rather than restating the
whole command:

```ini
[tox]
lock_files = requirements/base.txt = requirements/base.in
```

`lock_files` maps each lock to the sources it is compiled from, so a
project whose dependencies do not come as one set gets a lock per set
rather than a single lock that is the union of all of them. This
plugin's own [`tox.ini`] names one per env it installs anything into.
That list is not reproduced here: a copy of it in this file went stale
the first time an env was added, and the file it was copied from is
one click away.

[`tox.ini`]: https://github.com/tox-dev/tox-lock/blob/main/tox.ini

`uv pip compile` writes one output per invocation, so `lock-deps` runs
one per entry -- and compiles the union of however many sources an
entry names. They are comma-separated in `tox.ini`, an array in
`tox.toml`:

```ini
[tox]
lock_files =
  requirements/base.txt = requirements/base.in
  requirements/test.txt = requirements/base.in, requirements/test.in
```

```toml
lock_files = { "requirements/base.txt" = ["requirements/base.in"] }
```

The mapping is keyed by the lock rather than by its sources because
only the lock is unique -- one `requirements/base.in` legitimately
feeds both `base.txt` and `test.txt` above, and a mapping keyed the
other way would silently drop one of them.

A project with several of them rarely wants to recompile all of them at
once. `--lock-file` names the ones an invocation is about, and takes
the path exactly as `lock_files` spells it:

```console
$ tox run -q -e lock-deps --lock-file requirements/test.txt -- --upgrade-package attrs
$ tox run -q -e lock-deps-check --lock-file requirements/test.txt
```

It is repeatable, and every configured lock is the default -- so a
plain `tox run -e lock-deps` keeps doing what it did. Both envs read
it: narrowing a check is how CI asks about one lock without waiting on
the resolution of the rest.

A command-line option rather than a setting, because it says nothing
about the project -- `lock_files` has already said which locks there
are. And a name that setting does not declare is refused rather than
quietly matching nothing, which would have `lock-deps-check` pass
without having compared a single lock:

```console
$ tox run -q -e lock-deps --lock-file requirements/dev.txt
ROOT: HandledError| `--lock-file` names requirements/dev.txt, which
`lock_files` does not declare. It declares requirements/base.txt,
requirements/test.txt. [...]
```

The selection is compiled in the order `lock_files` declares, not the
order it is typed in: that order is the project's, and a lock compiled
under a `--constraint` naming another has to be written after it.

`uv` reads the lock's *format* off its file name, so naming it is
also how a project picks one. A lock called `pylock.toml` -- or
`pylock.<name>.toml` -- is written as a [PEP 751] document; anything
else is written as a `requirements.txt` one:

```ini
[tox]
lock_files = pylock.toml = pyproject.toml
```

Both envs work the same way on either, `lock-deps-check` included: it
compiles into a scratch file that keeps the lock's own name, so it
produces the same format it is comparing against. There is no format
setting here to keep in step with the file name, because there is
nothing a format setting could say that the name does not.

[PEP 751]: https://peps.python.org/pep-0751/

Emptying the setting is refused rather than obeyed: it would leave
`lock-deps` compiling nothing and `lock-deps-check` passing every time
without having checked anything, which is a green CI job asserting
that no lock is stale by virtue of there being none. A project that
wants neither env drops `tox-lock` from its `requires` instead.

The options `uv pip compile` is invoked with are settable the same
way. The setting names what your project *adds*, one option per line,
value included:

```ini
[tox]
lock_options =
  --universal
  --no-annotate
```

`--generate-hashes` is not among them and does not have to be:
`tox-lock` seeds it, and adding an option of your own no longer costs
you it. A project that cannot pin hashes -- one depending on a direct
URL or an editable checkout -- declines it in `uv`'s own spelling:

```ini
[tox]
lock_options =
  --no-generate-hashes
```

...which says which option is being turned off, and leaves every other
one in the list where it was. Naming `--generate-hashes` outright
works too, and is not read as a duplicate: the seed withdraws the
moment either spelling appears, in this setting or after `--`.

Each line is split the way the platform's own shell splits a command
line, so a value quoted for the space in it keeps that space -- and a
Windows path keeps its backslashes rather than losing them to an
escape nobody wrote.

`lock_options` says how this *project* resolves, so every lock is
compiled with it. An option that belongs to one lock alone goes in
`lock_file_options`, keyed by the lock the way `lock_files` is:

```ini
[tox]
lock_files =
  requirements/base.txt = pyproject.toml
  requirements/test.txt = pyproject.toml
lock_file_options =
  requirements/test.txt = --extra test
```

Two locks out of the same `pyproject.toml`, one of them carrying the
test extra, is the ordinary shape of a project that keeps its
dependencies in metadata rather than in `requirements/*.in` -- and
`--extra test` in `lock_options` would put `pytest` and everything
under it into the lock a deployment installs from.

An entry is added to whatever `lock_options` already asked for, and
read after it, so an option `uv` lets repeat accumulates with the
narrower say last. That also makes a seeded default declinable for one
lock alone -- the single dependency reachable only by URL costs that
lock its hashes and leaves the rest of the project pinned:

```ini
[tox]
lock_file_options =
  requirements/dev.txt = --no-generate-hashes
```

Both envs read it, and that is the point of it being a setting.
Saying the same thing per invocation -- `--lock-file requirements/test.txt
-- --extra test` -- writes the right lock and leaves `lock-deps-check`
recompiling it without the extra ever after, so the check reports
drift that a plain `tox run -e lock-deps` then "fixes" by throwing the
extra away.

A key naming a lock `lock_files` does not declare is refused rather
than ignored, for the same reason `--lock-file` refuses one: the
option would go nowhere, the lock it was meant for would compile
without it, and the run those two settings disagree in would exit
zero.

Every setting above is a default, and a default steps aside when a
project names the same option for itself. `--output-file` is the one
exception -- it is not a default but the argument that tells the two
envs apart, the writer compiling into your lock and the check into a
scratch file it throws away. Naming it would point the *check* at the
real lock and have it rewrite the very file it was asked to confirm
was already correct. So it is refused, in either spelling, wherever it
comes from:

```console
$ tox run -q -e lock-deps-check -- -o requirements.txt
ROOT: HandledError| `--output-file` is `tox-lock`'s to set and cannot
come from the arguments after `--`: [...] Set the `lock_files` core
setting instead.
```

The resolver itself is an input to the lock as much as the sources
are: two `uv` releases can pin the same requirements differently, and
a check running a newer `uv` than the machine that wrote the lock
reports drift that is not there. It is settled in the env's own
section, and the check env inherits it:

```ini
[testenv:lock-deps]
deps = uv == 0.9.2
```

That is stock tox configuration, not a setting this plugin invented:
`lock-deps-check` takes `[testenv:lock-deps]` as its
[`base`](https://tox.wiki/en/stable/config.html#base), so anything a
project sets on the env it thinks of as "the lock env" -- the
resolver, the interpreter, `set_env`, `pass_env` -- is set for the
check as well. `base` is not chained in tox, so `[testenv]` stays out
of both regardless. What the plugin owns is not inherited: the
commands, the description and the labels telling the two envs apart
stay as seeded however the writer is configured, and the check env's
own `[testenv:lock-deps-check]` section still has the last word over
both.

One thing does not follow the inheritance: a `-x` override. `-x
testenv:lock-deps.deps=uv==0.9.4` reaches the writer alone, because
the check env inherits a config *section* and an override is not one.
Run both envs off a one-off pin and the pin needs naming twice.

Pinning the resolver settles what a lock records; it does not make
that lock installable anywhere else. A project whose CI matrix
installs *one* lock on several platforms wants the resolution to cover
all of them, which is `uv`'s job rather than tox's:

```ini
[tox]
lock_options =
  --universal
```

`--universal` resolves across platforms and interpreters and writes
the environment markers that sort the result back out at install time.

The Python floor that resolution stops at does not have to be said.
`tox-lock` reads `requires-python` out of the project's
`pyproject.toml` and hands `uv` a `--python-version` off it, because
`uv` will not: left alone it resolves for whichever interpreter
`lock-deps` happened to run under -- and it does that even when the
`pyproject.toml` declaring `requires-python` is the file being
compiled. The lock is otherwise an artefact of the machine that wrote
it, and `lock-deps-check` reports drift on every machine whose Python
differs from that one.

Like every other default here it withdraws when contradicted: name
`--python-version`, `--python` or `-p` in `lock_options` or after `--`
and the seeded floor is not added. A project that declares no
`requires-python` gets no option seeded either.

The platform axis is deliberately left alone. `--universal` changes
what a lock *contains* -- pins for machines the project may never
deploy to -- and a lock aimed at a single target is a legitimate thing
to want. A Python floor is the other kind of question: the project had
already answered it, and nothing was reading the answer.

`uv` reads its own configuration -- the index to resolve against,
how to authenticate to it, which certificates to trust -- out of the
environment, and `tox` passes none of it through by default: its
allowlist covers `PIP_*`, which is the wrong resolver. Both lock envs
therefore pass `UV_*` unconditionally, so a project locking against a
private index does not have to say so. Whatever else the index
authenticates with is named alongside it:

```ini
[tox]
lock_pass_env = MY_INDEX_TOKEN
```

That setting adds to `UV_*` rather than replacing it, the way
`pass_env` adds to tox's own defaults -- and so does a `pass_env` of
your own, wherever you write it. A section wins a config key outright
in tox, so `[testenv:lock-deps]` with a `pass_env` in it would
otherwise take the resolver's environment away along with everything
else: a lock run that has quietly stopped seeing `UV_INDEX` resolves
against PyPI having been asked for a private index, and says nothing
about it. Both names come back through the same `post_process` hook
tox appends its own `PIP_*` with, after every section and every `-x`
override has had its say, so neither can be replaced by accident.

The labels are settable too, in each env's own section -- renamed to
fit a project's existing scheme, or emptied to opt out of labelling
altogether:

```ini
[testenv:lock-deps]
labels = pins

[testenv:lock-deps-check]
labels = pins-audit
```

Labels are the one env setting deliberately left out of the
inheritance above: a single label over a writer and a check selects a
pair whose second half is made vacuous by its first, and under `tox
run-parallel` the writer rewrites the very file the check is reading.
A project that wants them as one group says so by naming the same
label in both sections -- that choice is just not the default.

Substitutions work in all of these, core settings and env sections
alike -- for instance, `lock_files = {env:LOCK_FILE:requirements.txt}
= pyproject.toml`.

One-off options do not need a config change at all -- pass them after
`--`, where they are appended last. `uv` accumulates the options it
lets repeat -- `--upgrade-package`, `--extra`, `--constraint` -- and
rejects the ones it does not rather than taking the last, so an option
already named in `lock_options` is changed there rather than argued
with on the command line.

Both envs read the same settings for what the lock is made of, so a
project configures its lock once and the check follows.

The plugin's settings sit either side of your own env section, by what
they are. What it owns -- the commands, the labels, the description --
outranks the section it inherits; what it merely defaults -- the
resolver, the interpreter, the environment to pass -- falls below it.
Either way, `[testenv]` never leaks in, an `[testenv:lock-deps]`
section wins the keys it names, and `-x testenv:lock-deps.<key>=...`
wins over both -- whether or not the project declares that section at
all. Keys left unset keep the plugin's defaults:

```ini
[testenv:lock-deps]
deps = pip-tools
commands = pip-compile --generate-hashes -o requirements.txt pyproject.toml
```
