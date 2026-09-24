A new `--lock-file` command-line option names the locks one invocation
is about, out of those the `lock_files` core setting declares. It is
repeatable, defaults to every configured lock, and both `lock-deps` and
`lock-deps-check` read it.

Until now the smallest thing a project with several locks could do was
all of them: `tox run -e lock-deps -- --upgrade-package attrs`
recompiled every entry and landed a diff in each when one had been
asked about, and the way around it was to run `uv pip compile` by hand
-- going past the pinned resolver, the passed-through index
configuration, the seeded interpreter floor and the hash pinning.

A name `lock_files` does not declare is refused rather than matched
against nothing, which would leave `lock-deps-check` passing without
having compared a single lock. The selection compiles in the order the
setting declares rather than the order it was typed, because a lock
compiled under a `--constraint` naming another has to be written after
it.
