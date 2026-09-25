The new ``lock_build_requires`` core setting writes the requirements
file a build backend's lock is compiled from, out of the project's
``[build-system] requires`` table -- which ``uv pip compile`` cannot
read, and which previously left every project pinning its backend
maintaining a copy of that table that nothing compared.
``lock-deps`` writes the mirror before compiling from it;
``lock-deps-check`` reports the two drifting apart.
