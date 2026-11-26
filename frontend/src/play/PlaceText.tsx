import { Fragment } from "react";

/** 消息里可以点的地点：起了名字的地点（place），或地图上的地物（feature）。 */
export type PlaceTarget = { kind: "place" | "feature"; id: string; name: string };

/** 引擎写进 KP 消息里的链接：[名字](place:<id>) 或 [名字](feature:<地物 id>)。 */
const LINK = /\[([^\]\n]{1,80})\]\(((?:place|feature):[A-Za-z0-9_.-]{1,80})\)/g;

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * 把文字切成普通文字和地点。引擎写好的链接优先；其余文字里出现的起了名字的地点（两个字以上，长的优先）也当作地点，
 * 这样早先的消息、KP 忘了标的地方也能点。
 */
export function splitPlaces(text: string, places: { id: string; name: string }[]): (string | PlaceTarget)[] {
  const named = places.filter((p) => p.name.length >= 2).sort((a, b) => b.name.length - a.name.length);
  const auto = named.length ? new RegExp(named.map((p) => escapeRe(p.name)).join("|"), "g") : null;
  const byName = new Map(named.map((p) => [p.name, p.id]));
  const out: (string | PlaceTarget)[] = [];
  const plain = (s: string) => {
    if (!s) return;
    if (!auto) {
      out.push(s);
      return;
    }
    let last = 0;
    for (const m of s.matchAll(auto)) {
      const at = m.index ?? 0;
      if (at > last) out.push(s.slice(last, at));
      out.push({ kind: "place", id: byName.get(m[0]) ?? "", name: m[0] });
      last = at + m[0].length;
    }
    if (last < s.length) out.push(s.slice(last));
  };
  let last = 0;
  for (const m of text.matchAll(LINK)) {
    const at = m.index ?? 0;
    plain(text.slice(last, at));
    const [kind, id] = (m[2] ?? "").split(":") as ["place" | "feature", string];
    out.push({ kind, id, name: m[1] ?? "" });
    last = at + m[0].length;
  }
  plain(text.slice(last));
  return out;
}

/** 带可以点的地点的一段文字。 */
export function PlaceText({ text, places, onOpen }: { text: string; places: { id: string; name: string }[]; onOpen: (p: PlaceTarget) => void }) {
  return (
    <>
      {splitPlaces(text, places).map((x, i) =>
        typeof x === "string" ? (
          <Fragment key={i}>{x}</Fragment>
        ) : (
          <button key={i} type="button" className="pl-place-link" onClick={() => onOpen(x)}>
            {x.name}
          </button>
        ),
      )}
    </>
  );
}
