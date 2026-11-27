import { Fragment } from "react";

/** 消息里可以点的地点：起了名字的地点（place），或地图上的地物（feature）。 */
export type PlaceTarget = { kind: "place" | "feature"; id: string; name: string };

/** 消息里可以点的人（或东西）：我对他的代号 ref 和消息里写的名字。点了就是在行动里 @ 他。 */
export type PersonTarget = { kind: "entity"; ref: string; name: string };

/** 我认识的人：代号 ref 和我现在对他的叫法。 */
export type Person = { ref: string; label: string };

/**
 * 消息里的链接：引擎写的 [名字](place:<id>)、[名字](feature:<地物 id>)、@[名字](<代号 ref>)；
 * 玩家自己的行动里还有 @[名字](feature:…)、@[名字](point:x,y,z)。
 */
const LINK = /(@?)\[([^\]\n]{1,80})\]\(((?:place|feature|point):[A-Za-z0-9_.,-]{1,80}|[A-Za-z0-9_-]{1,80})\)/g;

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * 把文字切成普通文字、地点和人。写好的链接优先；其余文字里出现的起了名字的地点（两个字以上，长的优先）也当作地点，
 * “@我认识的人”也当作人，这样早先的消息、没标链接的地方也能点。
 */
export function splitPlaces(text: string, places: { id: string; name: string }[], people: Person[] = []): (string | PlaceTarget | PersonTarget)[] {
  const named = places.filter((p) => p.name.length >= 2).sort((a, b) => b.name.length - a.name.length);
  const known = people.filter((p) => p.label).sort((a, b) => b.label.length - a.label.length);
  const parts = [...known.map((p) => `@${escapeRe(p.label)}`), ...named.map((p) => escapeRe(p.name))];
  const auto = parts.length ? new RegExp(parts.join("|"), "g") : null;
  const byName = new Map(named.map((p) => [p.name, p.id]));
  const byLabel = new Map(known.map((p) => [p.label, p.ref]));
  const out: (string | PlaceTarget | PersonTarget)[] = [];
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
      const ref = m[0].startsWith("@") ? byLabel.get(m[0].slice(1)) : undefined;
      if (ref !== undefined) out.push({ kind: "entity", ref, name: m[0].slice(1) });
      else out.push({ kind: "place", id: byName.get(m[0]) ?? "", name: m[0] });
      last = at + m[0].length;
    }
    if (last < s.length) out.push(s.slice(last));
  };
  let last = 0;
  for (const m of text.matchAll(LINK)) {
    const [mention, name, ref] = [m[1] ?? "", m[2] ?? "", m[3] ?? ""];
    const colon = ref.indexOf(":");
    const scheme = colon < 0 ? "" : ref.slice(0, colon);
    if (!mention && scheme !== "place" && scheme !== "feature") continue; // 方括号后面跟圆括号的普通文字
    const at = m.index ?? 0;
    plain(text.slice(last, at));
    if (scheme === "place" || scheme === "feature") out.push({ kind: scheme, id: ref.slice(colon + 1), name });
    else if (scheme === "point") out.push(`@${name}`);
    else out.push({ kind: "entity", ref, name });
    last = at + m[0].length;
  }
  plain(text.slice(last));
  return out;
}

/** 带可以点的地点和人的一段文字。人用我现在对他的叫法（改过代号就显示新的）；不认识了就是普通文字。 */
export function PlaceText({
  text,
  places,
  onOpen,
  people = [],
  onPerson,
}: {
  text: string;
  places: { id: string; name: string }[];
  onOpen: (p: PlaceTarget) => void;
  people?: Person[];
  onPerson?: (p: PersonTarget) => void;
}) {
  const current = new Map(people.map((p) => [p.ref, p.label]));
  return (
    <>
      {splitPlaces(text, places, people).map((x, i) => {
        if (typeof x === "string") return <Fragment key={i}>{x}</Fragment>;
        if (x.kind === "entity") {
          const label = current.get(x.ref);
          if (label === undefined || !onPerson) return <Fragment key={i}>@{x.name}</Fragment>;
          return (
            <button key={i} type="button" className="pl-place-link" onClick={() => onPerson({ ...x, name: label })}>
              @{label}
            </button>
          );
        }
        return (
          <button key={i} type="button" className="pl-place-link" onClick={() => onOpen(x)}>
            {x.name}
          </button>
        );
      })}
    </>
  );
}
