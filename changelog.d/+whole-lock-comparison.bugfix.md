`lock-deps-check` compared the pins alone, skipping every comment
line. So a lock could be reported as current while `lock-deps` went on
to rewrite it: move a requirement between two sources of the same lock
and every pin lands where it was, only `uv`'s `# via` annotation
beside it changing. A CI job whose whole purpose is to say the lock
matches its sources said so of a lock that did not.

The comparison now reads the whole file. Skipping comments was there
for `uv`'s header, which names the command that wrote the file --
`--output-file` included, the one argument the check has to change --
and that reason expired when both envs began seeding the same
`--custom-compile-command`. The header in your lock is now the header
a recompile produces, so there is nothing left to excuse.

Expect a check that was green to go red once, on a lock that was
already stale in a way nothing was reporting. `tox run -e lock-deps`
is the fix, the same as for any other drift -- and the diff the check
prints now names the comments that moved along with the pins.
