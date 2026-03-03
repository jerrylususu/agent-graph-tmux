#!/usr/bin/env python3
from __future__ import annotations

import argparse
import time


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit runner done marker")
    parser.add_argument("--marker", required=True, help="done marker string")
    parser.add_argument("--delay", type=float, default=0.0, help="optional delay seconds")
    args = parser.parse_args()

    if args.delay > 0:
        time.sleep(args.delay)

    print(args.marker, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
