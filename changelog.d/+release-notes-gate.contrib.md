The release workflow now reads a tag's notes out of `CHANGELOG.md`
before publishing to PyPI rather than after it. A tag cut without
running `towncrier build` first therefore fails while the mistake is
still recoverable, instead of failing once PyPI has taken a filename
it never gives back.
