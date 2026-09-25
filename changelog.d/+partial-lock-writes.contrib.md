The `lock-deps` env now writes every lock it can compile instead of
abandoning the rest at the first failure -- `uv pip compile` writes
one output per invocation, so a project with several locks was losing
every one after an unresolvable source, and a scheduled refresh job
could report a single failure while renewing nothing.

`lock-deps-check` keeps stopping there, and no longer inherits the
writer's `ignore_errors`: it recompiles into a copy of the lock, so
carrying on past a failed recompile would have it report the one lock
it could not recompile as current.
