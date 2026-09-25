Naming `--output-file` in `lock_file_options` is now refused under that
setting's own name. The refusal used to send the reader to
`lock_options`, which does not mention the option they wrote.
