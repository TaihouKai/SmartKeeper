"""鉴权。权限检查只写在两个依赖项里：require_player 和 require_admin，路由里不自己判断身份。

- 玩家：邀请链接里的 token。首次打开后写进 HttpOnly cookie；脚本和以后的 adapter 用 Authorization: Bearer。
- 管理员：环境变量里配置的密码（argon2 哈希），登录后发另一个独立的、签名的会话 cookie，
  作用路径限定在 /api/admin。玩家 token 不携带任何管理权限。
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from smartkeeper.contracts import Player
from smartkeeper.engine import Engine

PLAYER_COOKIE = "sk_player"
ADMIN_COOKIE = "sk_admin"
ADMIN_COOKIE_PATH = "/api/admin"
ADMIN_SESSION_SECONDS = 12 * 3600


@dataclass
class RateLimiter:
    """滑动窗口限流：每个键在 window 秒内最多 limit 次。"""

    limit: int
    window: float = 60.0
    _hits: dict[str, deque[float]] = field(default_factory=dict[str, deque[float]])
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def hit(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True


def hash_password(password: str) -> str:
    return PasswordHasher().hash(password)


class Auth:
    def __init__(
        self, engine: Engine, admin_password_hash: str | None, session_secret: str
    ) -> None:
        self._engine = engine
        self._hash = admin_password_hash
        self._signer = TimestampSigner(session_secret or secrets.token_hex(32), salt="sk-admin")
        self.login_limiter = RateLimiter(limit=5, window=60)

    @property
    def admin_enabled(self) -> bool:
        return bool(self._hash)

    # ---------------- 玩家 ----------------

    @staticmethod
    def token_from(request: Request) -> str | None:
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            return header[7:].strip() or None
        return request.cookies.get(PLAYER_COOKIE)

    def require_player(self, request: Request) -> Player:
        token = self.token_from(request)
        player = self._engine.player_by_token(token) if token else None
        if player is None:
            raise HTTPException(status_code=401, detail={"code": "auth.player_required"})
        return player

    # ---------------- 管理员 ----------------

    def check_password(self, password: str) -> bool:
        if not self._hash:
            return False
        try:
            return PasswordHasher().verify(self._hash, password)
        except (VerificationError, InvalidHashError):
            return False

    def new_session(self) -> str:
        return self._signer.sign(secrets.token_hex(8)).decode()

    def require_admin(self, request: Request) -> None:
        """只认管理控制台的会话 cookie。玩家 token 一律 403。"""
        raw = request.cookies.get(ADMIN_COOKIE)
        if not raw or not self._hash:
            raise HTTPException(status_code=403, detail={"code": "auth.admin_required"})
        try:
            self._signer.unsign(raw, max_age=ADMIN_SESSION_SECONDS)
        except (BadSignature, SignatureExpired) as e:
            raise HTTPException(status_code=403, detail={"code": "auth.admin_required"}) from e
