This project now pins its own build backend. `setuptools` and
`setuptools-scm` were resolved from the index on every run, in a tree
whose every other install is hash-pinned; they are compiled into
`requirements/build-backend.txt` like everything else and handed to
the packaging env through `constraints` on `[pkgenv]`.

The lock's source is a copy of `[build-system] requires` -- `uv pip
compile` has no option for that table -- so a test compares the two,
a requirement added to one file and not the other being exactly how
the pin would come undone without saying anything.
