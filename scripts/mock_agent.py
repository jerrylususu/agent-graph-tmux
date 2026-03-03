#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys


def main() -> int:
    sys.stdout.write("mock-agent ready\n")
    sys.stdout.flush()

    for raw in sys.stdin:
        line = raw.rstrip("\n")
        sys.stdout.write(f"mock-agent input: {line}\n")
        sys.stdout.flush()

        if line.startswith("DONE_COMMAND:"):
            command = line.split(":", 1)[1].strip()
            proc = subprocess.run(command, shell=True)
            return proc.returncode

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
