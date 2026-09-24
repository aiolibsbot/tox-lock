The `lock_options` core setting now names what a project *adds* to the
`uv pip compile` invocation rather than replacing everything
`tox-lock` would have passed. `--generate-hashes` is seeded into the
command alongside the interpreter floor and the header comment, so
reaching for `--universal` -- or any other option -- no longer costs
you the hash pinning, and a restated default can no longer go on
saying what it said the day it was copied.

The seed withdraws whenever the project names either spelling of the
option itself, in `lock_options` or after `--`, so asking for
`--generate-hashes` outright is not read as a duplicate.
