The ``lock-deps`` and ``lock-deps-check`` envs now hand ``uv`` a
``--python-version`` read off the ``requires-python`` in the project's
``pyproject.toml``, so a lock records the same resolution whichever
interpreter compiled it -- and ``lock-deps-check`` stops reporting a
current lock as stale on any machine whose Python differs from the
writer's. Naming ``--python-version``, ``--python`` or ``-p`` in
``lock_options`` or after ``--`` withdraws the default, and a project
declaring no floor gets no option seeded.
