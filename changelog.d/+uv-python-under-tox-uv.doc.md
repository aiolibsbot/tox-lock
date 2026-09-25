The README now records the one ``UV_*`` variable that does not reach
``uv pip compile``: ``tox-uv``, when installed, removes ``UV_PYTHON``
from every env's environment, so the passthrough documented as
unconditional has an exception that depends on an unrelated plugin
being present. The seeded ``--python-version`` is what keeps it from
moving a lock, which makes a project declining that seed the one the
asymmetry can reach.
