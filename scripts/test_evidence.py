"""Evidence recorder command line entry point."""

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Record pytest evidence outside a checkout")
    parser.add_argument("command", choices=("snapshot", "run"))
    parser.add_argument("--repo")
    parser.add_argument("--output")
    parser.add_argument("--snapshot")
    parser.add_argument("--phase", choices=("red", "green"))
    parser.add_argument("--expected-failure", action="append", default=[])
    parser.add_argument("--python")
    parser.parse_args()
    print("evidence recorder behavior is not implemented", file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
