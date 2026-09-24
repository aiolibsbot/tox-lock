The README told a project that would rather not install from a stale
lock to put `depends = lock-deps-check` on the env doing the
installing. That line is not a guard: `tox` resolves `depends` for
ordering alone, and an entry naming an env the invocation was not
asked about is passed over without a word -- so the guarded env ran
against whatever the lock happened to say, and the run stayed green
having checked nothing.

The advice now names `env_list` first, which is what puts the check in
the run, and says what the `depends` beneath it is and is not worth:
it resolves env names rather than the labels the plugin seeds, and it
orders rather than gates, so a failing check still leaves the
dependent env to run. What the pair buys is the drift diff reaching
the CI log ahead of the failures it explains, and a red run.

`tests/depends_semantics_test.py` asserts all four behaviours the
paragraph now rests on, three of them negative -- the kind that
otherwise go stale unnoticed, an unfired guard being indistinguishable
from a current lock.
