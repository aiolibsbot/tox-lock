Emptying `lock_options` no longer opts out of `--generate-hashes`: the
setting now adds to the command rather than replacing it, so an empty
one adds nothing and takes nothing away. A project that cannot pin
hashes -- one depending on a direct URL or an editable checkout --
declines them in `uv`'s own spelling instead:

```ini
[tox]
lock_options =
  --no-generate-hashes
```

...which says which option is being turned off, and leaves the rest of
the list where it is.
