from __future__ import annotations

"""Generate example outputs (JSON/CSV) using cli_core in mock mode if needed."""

import subprocess
import sys


def main() -> None:
    # Call cli_core mock to ensure deterministic examples
    cmd = [sys.executable, "cli_core.py", "--mock", "--symbol", "bitcoin"]
    subprocess.check_call(cmd)
    print("Examples generated in examples/ and exports/")


if __name__ == "__main__":
    main()
