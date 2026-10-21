# BelegDock application icon

`belegdock.ico` (16, 20, 24, 32, 40, 48, 64, 128, 256 px) and
`src/belegdock/assets/belegdock.png` (256 px, used by Tk at runtime) are generated
by `make_icon.py` in this directory. The design is a white receipt with a folded
corner dropping into a navy tray on a rounded blue square; a green check badge
appears from 32 px, and small sizes use simplified lines.

- Provenance: drawn procedurally by `make_icon.py`; no third-party artwork or fonts.
- License: Apache-2.0, like the repository.
- Approval: the maintainer approved this design on 2026-10-21.
- Pillow is only a generator tool, not a runtime or locked dev dependency.

Regenerate from the repository root:

```sh
uv run --no-project --with pillow python packaging/icon/make_icon.py /tmp/belegdock-icon
cp /tmp/belegdock-icon/belegdock.ico packaging/icon/belegdock.ico
cp /tmp/belegdock-icon/belegdock.png src/belegdock/assets/belegdock.png
```

Output is deterministic for a given Pillow version. The test suite compares pixel
data with the committed assets when Pillow is available and skips that check
otherwise.
