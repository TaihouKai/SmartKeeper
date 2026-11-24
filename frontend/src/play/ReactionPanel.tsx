import { useState } from "react";
import { api, call, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox } from "../ui/components";
import { useAction, usePoll } from "../ui/hooks";

type Prompt = { seq: number; entry: string; defender: string; who?: string | null; checks: readonly string[]; labels?: Record<string, string>; skills: readonly Schemas["ReactionSkill"][] };
type Choice = Schemas["ReactionChoice"];

/** 每次攻击选一个应对：不抵抗、用检定对抗、或者用一个能当反应的技能（填它的“使用时填写”的列）。一次交齐。 */
export function ReactionForm({ prompts, onSubmit, busy }: { prompts: readonly Prompt[]; onSubmit: (choices: Choice[]) => void; busy: boolean }) {
  const { t } = useI18n();
  const [picked, setPicked] = useState<Record<number, Choice>>({});
  const choice = (seq: number): Choice => picked[seq] ?? { seq, kind: "none", check: "", entry: "", params: {} };
  const set = (seq: number, c: Partial<Choice>) => setPicked({ ...picked, [seq]: { ...choice(seq), ...c } });
  const missing = prompts.some((p) => {
    const c = choice(p.seq);
    if (c.kind !== "skill") return false;
    const sk = p.skills.find((s) => s.entry === c.entry);
    return !sk || (sk.params ?? []).some((x) => typeof c.params?.[x.name] !== "number");
  });
  return (
    <div className="sk-react-form">
      {prompts.map((p) => {
        const c = choice(p.seq);
        const key = c.kind === "check" ? `check:${c.check}` : c.kind === "skill" ? `skill:${c.entry}` : "none";
        const skill = c.kind === "skill" ? p.skills.find((s) => s.entry === c.entry) : undefined;
        return (
          <fieldset key={p.seq} className="sk-react-one">
            <legend>{p.who ? t("react.by", { who: p.who, entry: p.entry, defender: p.defender }) : t("react.by_unknown", { entry: p.entry, defender: p.defender })}</legend>
            <label className="sk-inline">
              <input type="radio" name={`r${p.seq}`} checked={key === "none"} onChange={() => set(p.seq, { kind: "none" })} /> {t("react.none")}
            </label>
            {p.checks.map((name) => (
              <label key={name} className="sk-inline">
                <input type="radio" name={`r${p.seq}`} checked={key === `check:${name}`} onChange={() => set(p.seq, { kind: "check", check: name })} /> {t("react.check", { name: p.labels?.[name] || name })}
              </label>
            ))}
            {p.skills.map((s) => (
              <label key={s.entry} className="sk-inline" title={s.description ?? ""}>
                <input type="radio" name={`r${p.seq}`} checked={key === `skill:${s.entry}`} onChange={() => set(p.seq, { kind: "skill", entry: s.entry, params: {} })} /> {t("react.skill", { name: s.entry })}
              </label>
            ))}
            {skill && (skill.params ?? []).length > 0 && (
              <div className="sk-react-params">
                {(skill.params ?? []).map((x) => (
                  <label key={x.name}>
                    {x.label || x.name}
                    <input
                      type="number"
                      value={c.params?.[x.name] ?? ""}
                      onChange={(e) => set(p.seq, { params: { ...(c.params ?? {}), ...(e.target.value === "" ? {} : { [x.name]: Number(e.target.value) }) } })}
                    />
                  </label>
                ))}
              </div>
            )}
            {skill?.description && <small className="sk-hint">{skill.description}</small>}
          </fieldset>
        );
      })}
      <button type="button" className="sk-primary" disabled={busy || missing} onClick={() => onSubmit(prompts.map((p) => choice(p.seq)))}>
        {t("react.submit")}
      </button>
    </div>
  );
}

/** 有人攻击我、等我选应对时，在页面最上面显示（没有时限，本轮等我交了才接着裁定）。 */
export function ReactionPanel({ onDone }: { onDone: () => void }) {
  const { t } = useI18n();
  const list = usePoll(() => call(api.GET("/api/reactions")), 8_000);
  const act = useAction();
  const prompts = list.data ?? [];
  if (!prompts.length) return null;
  return (
    <div className="sk-card sk-warn sk-react">
      <h3>{t("react.title")}</h3>
      <p className="sk-hint">{t("react.hint")}</p>
      <ReactionForm
        prompts={prompts}
        busy={act.busy}
        onSubmit={(choices) =>
          void act.run(async () => {
            await call(api.POST("/api/reactions", { body: { choices } }));
            void list.refresh();
            onDone();
          })
        }
      />
      <ErrorBox error={act.error} />
    </div>
  );
}
