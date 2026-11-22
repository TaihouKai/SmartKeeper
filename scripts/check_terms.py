"""专有名词检查：具体世界观的名词不得出现在规则包数据、剧本和设计文档以外的地方。"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TERMS_FILE = ROOT / "scripts" / "proper_nouns.txt"
ALLOWED_PREFIXES = ("rulepacks/", "scenarios/", "docs/")
TEXT_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".json",
    ".md",
    ".txt",
    ".toml",
    ".yaml",
    ".yml",
    ".html",
    ".css",
    ".cfg",
    ".ini",
    ".j2",
    ".ps1",
    ".sh",
}


def load_terms() -> list[re.Pattern[str]]:
    patterns: list[re.Pattern[str]] = []
    for raw in TERMS_FILE.read_text(encoding="utf-8").splitlines():
        term = raw.strip()
        if not term or term.startswith("#"):
            continue
        if term.isascii():
            patterns.append(
                re.compile(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", re.IGNORECASE)
            )
        else:
            patterns.append(re.compile(re.escape(term)))
    return patterns


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
    ).stdout
    return [line for line in out.splitlines() if line]


def main() -> int:
    patterns = load_terms()
    errors: list[str] = []
    for rel in tracked_files():
        rel_posix = rel.replace("\\", "/")
        if rel_posix.startswith(ALLOWED_PREFIXES) or rel_posix == "scripts/proper_nouns.txt":
            continue
        path = ROOT / rel_posix
        if path.suffix not in TEXT_SUFFIXES or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            for pat in patterns:
                m = pat.search(line)
                if m:
                    errors.append(f"{rel_posix}:{lineno}: 出现专有名词 {m.group(0)!r}")
    for e in errors:
        print(e)
    if errors:
        print(f"专有名词检查失败：{len(errors)} 处")
        return 1
    print("专有名词检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
