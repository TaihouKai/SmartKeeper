import { useMemo, useState } from "react";
import { api, call, type Schemas } from "../../../api/client";
import { useI18n } from "../../../i18n";
import { ErrorBox } from "../../../ui/components";
import { translateCode } from "../../../ui/errors";
import { FUNCTION_SIGNATURES } from "../../../ui/FormulaHelp";
import { CHECK_KEYS, CHECK_VARS, EXTRA_CONFIG_KEYS, OUTCOME_VARS, configKeys, mergeConfig } from "../../../ui/skillConfig";
import { useAction } from "../../../ui/hooks";
import { allFormulas, describePath, getAt, type Doc, type Pack } from "../model";

type Insert = (text: string) => void;

function Item({ code, note, onClick }: { code: string; note?: string; onClick: () => void }) {
  return (
    <button type="button" className="wb-name" onClick={onClick} title={note}>
      <code>{code}</code>
      {note && <span className="wb-name-note">{note}</span>}
    </button>
  );
}

/** 写到这里能用的名字：点一下插入到光标处。 */
export function NamesPanel({ pack, doc, insert, part = "main" }: { pack: Pack; doc: Doc | null; insert: Insert; part?: "config" | "main" }) {
  const { t } = useI18n();
  const tpl = doc?.template ? pack.templates.find((x) => x.name === doc.template) : undefined;
  const row = doc?.entry ? pack.templates[doc.entry.t]?.groups?.[doc.entry.g] : undefined;
  const preset = doc?.entry ? row?.presets?.[doc.entry.r] : undefined;
  const targetFields = useMemo(() => {
    const seen = new Map<string, string>();
    for (const x of pack.templates) for (const f of [...(x.fields ?? []), ...(x.derived ?? [])]) if (!seen.has(f.name)) seen.set(f.name, f.label ?? "");
    return [...seen.entries()];
  }, [pack]);
  if (!doc) return <p className="sk-hint">{t("ide.names_none")}</p>;
  const script = doc.kind === "entry" && part === "main";
  const group = doc.entry ? pack.templates[doc.entry.t]?.groups?.[doc.entry.g] : undefined;
  if (doc.kind === "check")
    return (
      <div className="wb-names">
        <section>
          <h5>{t("rules.checks")}</h5>
          {CHECK_KEYS.map((k) => (
            <Item key={k} code={`${k} = …`} note={t(`check.c.${k}`)} onClick={() => insert(`${k} = `)} />
          ))}
        </section>
        <section>
          <h5>{t("check.vars")}</h5>
          {CHECK_VARS.map((k) => (
            <Item key={k} code={k} note={t(k === "target" ? "check.c.target" : `check.v.${k}`)} onClick={() => insert(k)} />
          ))}
          {(pack.checks ?? [])
            .filter((c) => c.name)
            .map((c) => (
              <Item key={`c-${c.name}`} code={`"${c.name}"`} note={t("check.c.opposed_by")} onClick={() => insert(`"${c.name}"`)} />
            ))}
        </section>
      </div>
    );
  return (
    <div className="wb-names">
      {doc.kind === "entry" && part === "config" && group && (
        <section>
          <h5>{t("config.title")}</h5>
          {[...configKeys(group), ...EXTRA_CONFIG_KEYS].map((k) => (
            <Item key={k} code={`${k} = …`} note={t(`config.c.${k}`)} onClick={() => insert(`${k} = `)} />
          ))}
          <Item code='best("a", "b")' note={t("config.best")} onClick={() => insert('best("')} />
          {OUTCOME_VARS.slice(0, 5).map((k) => (
            <Item key={k} code={k} note={t(`doc.kw.${k}`)} onClick={() => insert(k)} />
          ))}
          {(pack.checks ?? [])
            .filter((c) => c.name)
            .map((c) => (
              <Item key={`check-${c.name}`} code={`"${c.name}"`} note={t("rules.checks")} onClick={() => insert(`"${c.name}"`)} />
            ))}
          {["sphere(radius=", "cone(length=, angle=", "capsule(length=, width=", "box(length=, width=, height=", "placement(radius=", "placement(building=True"].map((c) => (
            <Item key={c} code={`${c}…)`} note={t(c.startsWith("placement") ? "config.c.placement" : "config.c.shape")} onClick={() => insert(c)} />
          ))}
        </section>
      )}
      {script && (
        <section>
          <h5>{t("ide.n.actions")}</h5>
          {[
            ["target.damage(", "fh.s.damage"],
            ["self.add(hp, ", "fh.s.add"],
            ["target.sub(mp, ", "fh.s.sub"],
            ["target.set(", "ide.n.set"],
            ["target.modify(", "fh.s.modify"],
            ["self.summon(", "doc.verb.summon"],
            ["target.teleport(self", "doc.verb.teleport"],
          ].map(([code, key]) => (
            <Item key={code} code={`${code!}…)`} note={t(key!)} onClick={() => insert(code!)} />
          ))}
          <Item code="if …:" note={t("fh.s.if")} onClick={() => insert("if ")} />
          {OUTCOME_VARS.map((k) => (
            <Item key={k} code={k} note={t(`doc.kw.${k}`)} onClick={() => insert(k)} />
          ))}
          <Item key="negate" code="self.negate()" note={t("doc.verb.negate")} onClick={() => insert("self.negate()")} />
        </section>
      )}
      {row && preset && (
        <section>
          <h5>{t("ide.n.this", { name: preset.name || "?" })}</h5>
          {(row.fields ?? []).map((f) => {
            const v = (preset.fields ?? {})[f.name];
            const note = v === undefined || v === "" ? t("ide.n.empty") : `= ${String(v)}`;
            return <Item key={f.name} code={`this.${f.name}`} note={`${f.label ? `${f.label} ` : ""}${note}`} onClick={() => insert(`this.${f.name}`)} />;
          })}
        </section>
      )}
      {tpl && (
        <section>
          <h5>{t("ide.n.self", { name: tpl.label || tpl.name })}</h5>
          {[...(tpl.fields ?? []), ...(tpl.derived ?? [])].map((f) => (
            <Item key={f.name} code={script ? `self.${f.name}` : f.name} note={f.label ?? ""} onClick={() => insert(script ? `self.${f.name}` : f.name)} />
          ))}
        </section>
      )}
      {script && (
        <section>
          <h5>{t("ide.n.target")}</h5>
          <Item code="target.template" note={t("fh.b.template")} onClick={() => insert("target.template")} />
          {targetFields.map(([name, label]) => (
            <Item key={name} code={`target.${name}`} note={label} onClick={() => insert(`target.${name}`)} />
          ))}
        </section>
      )}
      {(pack.formulas ?? []).length > 0 && (
        <section>
          <h5>{t("rules.formulas")}</h5>
          {(pack.formulas ?? []).map((f) => (
            <Item key={f.name} code={f.name} note={f.formula} onClick={() => insert(f.name)} />
          ))}
        </section>
      )}
      <section>
        <h5>{t("fh.functions")}</h5>
        {FUNCTION_SIGNATURES.map(([name, sig]) => (
          <Item key={name} code={sig} note={t(`fh.fn.${name}`)} onClick={() => insert(`${name}(`)} />
        ))}
      </section>
    </div>
  );
}

/** 在整个规则包的公式和脚本里找一段文字（通常是一个名字）。 */
export function SearchPanel({ pack, query, setQuery, onOpen, fromCursor }: { pack: Pack; query: string; setQuery: (q: string) => void; onOpen: (path: string) => void; fromCursor: () => string }) {
  const { t } = useI18n();
  const hits = useMemo(() => {
    const q = query.trim();
    if (!q) return [];
    const word = /^[\p{L}_][\p{L}\p{N}_.]*$/u.test(q);
    const re = word ? new RegExp(`(?<![\\p{L}\\p{N}_])${q.replace(/\./g, "\\.")}(?![\\p{L}\\p{N}_])`, "u") : null;
    const out: { path: string; line: number; text: string }[] = [];
    for (const f of allFormulas(pack)) {
      f.text.split("\n").forEach((ln, i) => {
        if (re ? re.test(ln) : ln.includes(q)) out.push({ path: f.path, line: i + 1, text: ln.trim() });
      });
    }
    return out;
  }, [pack, query]);
  return (
    <div className="wb-search">
      <div className="wb-search-bar">
        <input value={query} placeholder={t("ide.search_ph")} onChange={(e) => setQuery(e.target.value)} />
        <button type="button" onClick={() => setQuery(fromCursor())}>
          {t("ide.search_cursor")}
        </button>
      </div>
      {query.trim() && <p className="sk-hint">{t("ide.search_count", { n: String(hits.length) })}</p>}
      <ul className="wb-hits">
        {hits.map((h, i) => (
          <li key={i}>
            <button type="button" onClick={() => onOpen(h.path)}>
              <span className="wb-hit-where">
                {describePath(t, pack, h.path).join(" › ")}
                {h.line > 1 ? ` · ${t("script.line", { n: String(h.line) })}` : ""}
              </span>
              <code>{h.text}</code>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

type Step = Schemas["ScriptStep"];

/** 用例题卡把脚本跑一遍（不进对局）：会执行哪些动作、掷出什么、谁的哪个值从多少变成多少。 */
export function TryPanel({ pack, doc, onGoSamples }: { pack: Pack; doc: Doc | null; onGoSamples: () => void }) {
  const { t, lang } = useI18n();
  const act = useAction();
  const [user, setUser] = useState(0);
  const [target, setTarget] = useState<string>("same");
  const [params, setParams] = useState<Record<string, string>>({});
  const [out, setOut] = useState<Schemas["ScriptTryOut"] | null>(null);
  const samples = pack.samples ?? [];
  if (!doc || doc.kind !== "entry" || !doc.entry) return <p className="sk-hint">{t("ide.try_only_scripts")}</p>;
  const group = pack.templates[doc.entry.t]?.groups?.[doc.entry.g];
  const preset = group?.presets?.[doc.entry.r];
  // 用途：设置在条目自己的设置上覆盖
  const ownConfig = String(getAt(pack, `${doc.path}.config`) ?? "");
  const config = doc.entry.u !== undefined ? mergeConfig(preset?.config ?? "", ownConfig) : ownConfig;
  const mine = samples.map((s, i) => ({ s, i })).filter(({ s }) => s.template === doc.template);
  if (!mine.length)
    return (
      <div>
        <p className="sk-hint">{t("ide.try_no_sample", { tpl: doc.template ?? "" })}</p>
        <button type="button" onClick={onGoSamples}>
          {t("ide.try_go_samples")}
        </button>
      </div>
    );
  const me = mine.find((x) => x.i === user) ?? mine[0]!;
  // 这次使用的参数：规则包给这个分组的默认参数，加上这一条自己的
  const paramCols = [...(pack.params ?? []).filter((x) => group && (x.groups ?? []).includes(group.name)), ...(preset?.params ?? [])];
  const run = () =>
    void act.run(async () => {
      const entry: Record<string, unknown> = { ...(preset?.fields ?? {}) };
      for (const f of paramCols) if (params[f.name]?.trim()) entry[f.name] = Number(params[f.name]);
      const tgt = target === "none" ? null : target === "same" ? me.s : samples[Number(target)];
      setOut(
        await call(
          api.POST("/api/admin/rulepacks/script/try", {
            body: {
              pack,
              script: String(getAt(pack, `${doc.path}.script`) ?? ""),
              config,
              template: me.s.template,
              sheet: me.s.sheet as Record<string, unknown>,
              entry: entry as Schemas["ScriptTryIn"]["entry"],
              target_template: tgt ? tgt.template : null,
              target_sheet: tgt ? (tgt.sheet as Record<string, unknown>) : null,
            },
          }),
        ),
      );
    });
  return (
    <div className="wb-try">
      <div className="wb-try-form">
        <label>
          {t("ide.try_user")}
          <select value={me.i} onChange={(e) => setUser(Number(e.target.value))}>
            {mine.map(({ s, i }) => (
              <option key={i} value={i}>
                {s.name || `#${i + 1}`}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("ide.try_target")}
          <select value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="same">{t("ide.try_self")}</option>
            <option value="none">{t("ide.try_none")}</option>
            {samples.map((s, i) => (
              <option key={i} value={String(i)}>
                {`${s.name || `#${i + 1}`}（${s.template}）`}
              </option>
            ))}
          </select>
        </label>
        {paramCols.map((f) => (
          <label key={f.name}>
            {f.label || f.name}
            <input type="number" value={params[f.name] ?? ""} placeholder={f.min ?? ""} onChange={(e) => setParams({ ...params, [f.name]: e.target.value })} />
          </label>
        ))}
        <button type="button" className="sk-primary" disabled={act.busy} onClick={run}>
          {out ? t("ide.try_again") : t("ide.try_run")}
        </button>
      </div>
      <ErrorBox error={act.error} />
      {out && out.problems.length > 0 && (
        <ul className="sk-problems">
          {out.problems.map((p, i) => (
            <li key={i}>{translateCode(lang, p.code, p.params)}</li>
          ))}
        </ul>
      )}
      {out && out.problems.length === 0 && <Steps steps={out.steps} values={out.values ?? {}} pack={pack} />}
    </div>
  );
}

function Steps({ steps, values, pack }: { steps: Step[]; values: Record<string, Record<string, unknown>>; pack: Pack }) {
  const { t } = useI18n();
  const labels = new Map<string, string>();
  for (const x of pack.templates) for (const f of [...(x.fields ?? []), ...(x.derived ?? [])]) if (f.label && !labels.has(f.name)) labels.set(f.name, f.label);
  const label = (n: string) => (labels.get(n) ? `${labels.get(n)}（${n}）` : n);
  // 按顺序在副本上算：同一个值被改两次时第二句从第一句的结果算起（不计上下限）
  const now: Record<string, Record<string, number>> = {};
  const num = (who: string, f: string): number | null => {
    const v = now[who]?.[f] ?? values[who]?.[f];
    return typeof v === "number" ? v : null;
  };
  const set = (who: string, f: string, v: number) => {
    now[who] = { ...(now[who] ?? {}), [f]: v };
  };
  if (!steps.length) return <p className="sk-hint">{t("ide.try_nothing")}</p>;
  return (
    <ol className="wb-steps">
      {steps.map((s, i) => {
        const who = t(s.who === "self" ? "ide.who.self" : "ide.who.target");
        const changes: string[] = [];
        if (s.op === "damage") {
          let left = s.amount ?? 0;
          for (const f of ["shield", "hp"]) {
            const before = num(s.who, f);
            if (before === null || left <= 0) continue;
            const take = f === "shield" ? Math.min(before, left) : left;
            if (take <= 0) continue;
            set(s.who, f, before - take);
            left -= take;
            changes.push(`${label(f)} ${fmt(before)} → ${fmt(before - take)}`);
          }
        } else if (s.op !== "modify" && s.field) {
          const before = num(s.who, s.field);
          if (before !== null) {
            const after = s.op === "add" ? before + (s.amount ?? 0) : s.op === "subtract" ? before - (s.amount ?? 0) : (s.amount ?? 0);
            set(s.who, s.field, after);
            changes.push(`${label(s.field)} ${fmt(before)} → ${fmt(after)}`);
          }
        }
        const minutes = s.seconds != null ? t("ide.try_minutes", { n: fmt(s.seconds / 60) }) : "";
        return (
          <li key={i} className={`wb-step wb-step-${s.who}`}>
            <div>
              <span className="wb-who">{who}</span> {t(`ide.op.${s.op}`)}
              {s.field && <b> {label(s.field)}</b>}
              {s.op === "modify" ? <code> {s.formula}</code> : <b> {fmt(s.amount ?? 0)}</b>}
              {minutes && <span className="sk-hint"> · {minutes}</span>}
              {s.rolls && s.rolls.length > 0 && <span className="wb-rolls">🎲 {s.rolls.join(", ")}</span>}
            </div>
            {changes.length > 0 && <div className="wb-change">{changes.join("；")}</div>}
          </li>
        );
      })}
    </ol>
  );
}

function fmt(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}
