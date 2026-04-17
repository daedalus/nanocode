import asyncio

from nanocode.main import main


def cli_main() -> int:
    return asyncio.run(main())


if __name__ == "__main__":
    raise SystemExit(cli_main())
