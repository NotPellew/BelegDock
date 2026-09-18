import argparse
from collections.abc import Sequence

from . import __version__


def gmail_client():
    raise NotImplementedError


def lexware_client():
    raise NotImplementedError


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="belegdock",
        description="BelegDock early-stage CLI for local document transfer experiments.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    try:
        parser.parse_args(argv)
    except SystemExit as error:
        return error.code if isinstance(error.code, int) else 1
    return 0
