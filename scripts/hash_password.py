"""生成管理员密码的 argon2 哈希，填进 SMARTKEEPER_ADMIN_PASSWORD_HASH。

uv run python scripts/hash_password.py
"""

from __future__ import annotations

import getpass
import sys

from smartkeeper.web import hash_password


def main() -> int:
    pw = getpass.getpass("admin password: ")
    if pw != getpass.getpass("again: "):
        print("passwords differ", file=sys.stderr)
        return 1
    print(hash_password(pw))
    return 0


if __name__ == "__main__":
    sys.exit(main())
