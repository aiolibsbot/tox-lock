The pairing the README's Scope section recommends is now run rather
than asserted: an ``interop-tox-uv`` env and a CI job of the same name
install ``tox-uv`` alongside the plugin and drive both lock envs on
the runner it makes default. It takes an env of its own because
``tox-uv`` registers by making ``uv-venv-runner`` the process-wide
default, so installing it beside the rest of the suite would move
every test onto a runner none of them mean to exercise.
