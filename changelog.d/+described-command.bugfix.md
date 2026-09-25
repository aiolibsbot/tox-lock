The `lock-deps` and `lock-deps-check` descriptions `tox list -v` prints
are now rendered off the arguments the compile command is built out of,
rather than off the settings behind them. They used to restate a part of
the command by hand, which said `--generate-hashes` for a lock whose
`lock_file_options` declined it and never mentioned the seeded
`--python-version` or `--custom-compile-command` at all.
