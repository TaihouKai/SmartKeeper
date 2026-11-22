import importlib

MODULES = [
    "contracts",
    "eventlog",
    "rules",
    "world",
    "rounds",
    "dice",
    "mapdata",
    "spatial",
    "handles",
    "memory",
    "engine",
    "chat",
    "llm",
    "kp",
    "notify",
    "web",
]


def test_all_modules_import() -> None:
    for name in MODULES:
        importlib.import_module(f"smartkeeper.{name}")
