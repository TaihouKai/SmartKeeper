"""世界状态的折叠、快照、patch 校验。依赖 rules 的接口（经构造函数注入）。"""

from smartkeeper.world.patch import PatchError, apply_patch, get, parse_pointer
from smartkeeper.world.service import TOP_LEVEL, WorldService

__all__ = ["TOP_LEVEL", "PatchError", "WorldService", "apply_patch", "get", "parse_pointer"]
