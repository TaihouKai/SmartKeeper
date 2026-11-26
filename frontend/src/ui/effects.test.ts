import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

/**
 * useEffect 的回调不能是不带花括号的箭头函数：它的返回值会被 React 当成清理函数。
 * 例如新版浏览器的 scrollIntoView 返回 Promise，组件卸载时 React 去“调用”它，整页崩掉。
 */
const SRC = join(__dirname, "..");
const BAD = /use(Layout)?Effect\(\s*\(\)\s*=>\s*[^{\s]/;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    if (statSync(p).isDirectory()) return files(p);
    return /\.tsx?$/.test(n) && !n.endsWith(".test.ts") ? [p] : [];
  });
}

describe("effects", () => {
  it("effect callbacks have a block body", () => {
    const all = files(SRC);
    expect(all.length).toBeGreaterThan(20);
    const bad = all.flatMap((f) =>
      readFileSync(f, "utf-8")
        .split("\n")
        .map((line, i) => (BAD.test(line) ? `${f}:${i + 1}: ${line.trim()}` : ""))
        .filter(Boolean),
    );
    expect(bad).toEqual([]);
  });
});
