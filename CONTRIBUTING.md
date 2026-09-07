# Contributing to XIFF

XIFF is an experimental intent-geometry language. Help us learn which
operations make drawings simpler to express.

## Start with a drawing

Examples, bug reports, documentation fixes, and geometry corrections are
welcome. For a bug, include the smallest `.xiff` source that reproduces it,
your Python version, the expected result, and the actual image or error.

Before implementing a new directive or changing syntax, open an issue with
a drawing that needs it. Explain how the proposed feature simplifies that
drawing. The maintainer makes the final decision on language changes.

## Design principles

- Describe drawing intent through local geometry.
- Keep the language small and the implementation readable.
- Preserve a Python standard-library-only runtime.
- Make transforms consistent across primitives, aliases, and defaults.
- Test geometric behavior or output, not just whether rendering succeeds.
- Keep external formats and tools optional; the engine writes PNG directly.

## Development

From the repository root, using Python 3.10 or newer:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
python -m py_compile engine.py xiff/__init__.py xiff/cli.py
xiff examples/robot_garden.xiff robot_garden.png
```

For rendering changes, inspect the resulting image and add a regression test
for the geometry or pixels that were wrong. Include a before/after example
in the pull request when useful. Keep changes focused and describe why they
help someone drawing with XIFF.

Generated PNGs are ignored except for the small gallery in `docs/`. Keep
editable `.xiff` examples alongside changes. To regenerate the logo studies:

```sh
python examples/logo_tests/build.py
```

Treat other contributors respectfully and give specific, constructive
feedback. Experiments are welcome; inclusion in the core depends on whether
they support the project's direction.
