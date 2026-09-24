A new `lock_file_options` core setting names the `uv pip compile`
options one lock alone is compiled with, keyed by that lock the way
`lock_files` is. Both `lock-deps` and `lock-deps-check` read it, and an
entry is added to whatever `lock_options` already asked for rather than
replacing it.

`lock_options` says how the whole project resolves and so reaches every
lock. Two locks compiled out of one `pyproject.toml` -- the ordinary
shape of a project keeping its dependencies in metadata -- had nowhere
to put the `--extra test` that tells them apart: in `lock_options` it
put `pytest` and everything under it into the lock a deployment
installs from. Saying it per invocation instead wrote the right lock
and left `lock-deps-check` recompiling it without the extra ever after,
so the check reported drift that running the writer again "fixed" by
throwing the extra away.

A key naming a lock `lock_files` does not declare is refused rather
than dropped in silence, which would leave that lock compiled without
the options it was given and the run exiting zero anyway.
