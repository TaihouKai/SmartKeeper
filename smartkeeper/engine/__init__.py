"""把各模块组合成对外的 `Engine` 门面，做跨模块的校验。"""

from smartkeeper.engine.core import MAX_TEXT, Engine, hash_token
from smartkeeper.engine.repo import metadata as engine_metadata
from smartkeeper.engine.scenario import (
    KpMeta,
    NpcSpec,
    PublicMeta,
    kp_meta,
    public_meta,
    split_front_matter,
)

__all__ = [
    "MAX_TEXT",
    "Engine",
    "KpMeta",
    "NpcSpec",
    "PublicMeta",
    "engine_metadata",
    "hash_token",
    "kp_meta",
    "public_meta",
    "split_front_matter",
]
