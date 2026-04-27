import asyncio
import os
import sys

# Force unbuffered output - must be done before any output
if hasattr(sys.stdout, 'fileno') and sys.stdout.fileno() >= 0:
    sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', buffering=1)

from nanocode.main import main


def cli_main() -> int:
    return asyncio.run(main())


if __name__ == "__main__":
    raise SystemExit(cli_main())
