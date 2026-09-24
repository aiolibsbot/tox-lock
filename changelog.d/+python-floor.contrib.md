The supported Python floor is now stated once. `requires-python` in
`pyproject.toml` is the declaration; the trove classifiers,
`python_version` in `.mypy.ini` and the `--python-version` that
`lock_options` hands `uv` are checked against it by
`tests/python_floor_test.py`, and `target-version` in `.ruff.toml` was
dropped altogether -- `ruff` resolves the floor out of the declaration
on its own.
