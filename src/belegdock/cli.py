import argparse
from collections.abc import Sequence
from importlib import import_module

from . import __version__
from . import accounts


def connect_gmail(client_path):
    return ""


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
