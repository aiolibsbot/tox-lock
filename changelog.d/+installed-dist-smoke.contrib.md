The built dists are now installed into a throwaway virtual environment
and driven with `tox` before CI accepts them, so the entry point a build
writes, the namespace package it lands in `site-packages`, and the
helper scripts the check env runs *by path* are exercised somewhere
other than an editable install of the work tree -- by a `smoke-dists`
env a contributor runs as part of a bare `tox`, replacing the
import-only shell step that lived in `ci.yml` alone.
