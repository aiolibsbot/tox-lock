`tox.ini` now names the plugin in `requires` and lists every CI gate in
`env_list`, so `tox` with no arguments runs what a pull request runs --
and `tox run -e lock-deps-check` on a `tox` without the plugin loaded
fails instead of running the test suite and reporting the locks current.
