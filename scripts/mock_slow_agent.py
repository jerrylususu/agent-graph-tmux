#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import time


DELAY_SEC = 30


def main() -> int:
    sys.stdout.write(f"mock-slow-agent ready (delay={DELAY_SEC}s)\n")
    sys.stdout.flush()

    for raw in sys.stdin:
        line = raw.rstrip("\n")
        sys.stdout.write(f"mock-slow-agent input: {line}\n")
        sys.stdout.flush()

        if line.startswith("DONE_COMMAND:"):
            command = line.split(":", 1)[1].strip()
            sys.stdout.write(
                f"mock-slow-agent working {DELAY_SEC}s (progress every second)...\n"
            )
            sys.stdout.flush()
            for elapsed in range(1, DELAY_SEC + 1):
                remaining = DELAY_SEC - elapsed
                sys.stdout.write(
                    f"mock-slow-agent progress: {elapsed}/{DELAY_SEC}s "
                    f"(remaining {remaining}s)\n"
                )
                sys.stdout.flush()
                time.sleep(1)
            proc = subprocess.run(command, shell=True)
            return proc.returncode

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
