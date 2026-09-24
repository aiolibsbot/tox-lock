# Changelog fragments

Every user-visible change adds a file to this directory. `towncrier`
collects them into `CHANGELOG.md` when a version is cut, and
`.github/workflows/release.yml` publishes that version's section as the
GitHub Release notes -- so a fragment is the text a user reads when
deciding whether to upgrade, not a note to the next maintainer.

## Naming

    <issue>.<category>.md

`<issue>` is the number of the issue or pull request the change belongs
to. A change with neither -- a typo fix, an internal rename -- takes
`+` followed by anything unique instead, and is rendered without a
link.

`<category>` is one of the directories listed under `[tool.towncrier]`
in `pyproject.toml`:

| category | for |
| --- | --- |
| `breaking` | changes that can stop an existing `tox.ini` from working |
| `deprecation` | things that still work and will not in the next major |
| `feature` | new configuration keys, new envs, new behaviour |
| `bugfix` | behaviour that did not match what was documented |
| `doc` | changes to the README or to these instructions |
| `packaging` | dists, metadata, supported versions, dependencies |
| `contrib` | changes only a contributor to this repository notices |
| `misc` | internal churn worth a line but not a description |

A name that matches neither shape is **not** ignored: `towncrier`
would drop it silently and the change would vanish from the release
notes, so `tox -e changelog` refuses it by name instead.

## Writing one

One or two sentences, in the present tense, about what changed for the
reader -- and, where it is not obvious, why. The category already says
what kind of change it is; the fragment does not need to repeat it.

    $ echo 'Locks are now written in PEP 751 format when the output file is named `pylock.toml`.' > changelog.d/42.feature.md

Preview the collected result without writing it:

    $ tox run -e changelog
