The environment `uv` is configured with -- `UV_*`, and whatever
`lock_pass_env` names alongside it -- now survives a project writing
its own `pass_env` on either lock env, or overriding it with `-x`.
Both are appended through the same `post_process` hook `tox` adds its
`PIP_*` with, rather than seeded as a value a section replaces
outright. Before, `[testenv:lock-deps]` with a `pass_env` in it -- the
section a project is told to write to pin the resolver -- silently
dropped `UV_*`, and the lock run resolved against PyPI having been
asked for a private index.
