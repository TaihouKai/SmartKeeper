import { useState } from "react";
import { api, call, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox, formatDuration } from "../ui/components";
import { useAction } from "../ui/hooks";
import { choiceParts, describePlanned, toCompose, useActionPlan, type Skill } from "./actionPlan";
import { prettyMentions } from "./events";

export type Target = { ref: string; label: string };

/**
 * 本回合行动（像 RPG 那样点出来）：上面是行动列表和补充说明，下面选角色、点动作和技能、开关。
 * 点出来的行动不经过 KP；只有写了补充说明才交给 KP 和点好的一起解析（矛盾时 KP 驳回）。
 * 不耗时、只对自己、没人看见的开关当场生效。
 */
export function ActionPanel({
  collecting,
  targets,
  text,
  setText,
  quotes,
  textBox,
  onChanged,
}: {
  collecting: boolean;
  targets: Target[];
  text: string;
  setText: (s: string) => void;
  quotes: number[];
  textBox: React.ReactNode;
  onChanged: () => void;
}) {
  const { t } = useI18n();
  const { own, skills, plan, actor, setActor, configuring, setConfiguring, add, update, remove, clear } = useActionPlan();
  const [echo, setEcho] = useState<Schemas["ActionEcho"] | null>(null);
  const [note, setNote] = useState("");
  const send = useAction();
  const confirm = useAction();
  const flip = useAction();
  const mine = skills.filter((s) => s.entity_id === actor);
  const toggles = mine.filter((s) => s.toggle_on !== null && s.toggle_on !== undefined);
  const buttons = mine.filter((s) => s.toggle_on === null || s.toggle_on === undefined);
  const groups = [...new Set(buttons.map((s) => s.group_label || s.group))];
  const summary = plan.map((p) => describePlanned(p, own, skills, t)).join("\n");

  const doSend = () =>
    void send.run(async () => {
      const out = await call(api.POST("/api/action/compose", { body: { actions: plan.map(toCompose), text: text.trim(), summary } }));
      if (out.instant) {
        clear();
        onChanged();
      } else setEcho(out.echo ?? null);
    });
  const doConfirm = () =>
    void confirm.run(async () => {
      if (!echo) return;
      await call(api.POST("/api/action", { body: { parse_id: echo.parse_id, quotes } }));
      setEcho(null);
      clear();
      setText("");
      onChanged();
    });
  // 开关：按一下就当场切换（没人看见时）；有人看见时放进本回合的行动，等结算
  const doFlip = (s: Skill) =>
    void flip.run(async () => {
      const out = await call(api.POST("/api/action/compose", { body: { actions: [{ actor: s.entity_id, entry: s.name, params: {}, companions: [] }], text: "", summary: "" } }));
      if (out.instant) {
        setNote("");
        onChanged();
      } else {
        add({ actor: s.entity_id, entry: s.name, companions: [], params: {} });
        setNote(t("plan.seen_wait"));
      }
    });
  const pick = (s: Skill) => {
    if (s.target === "single" || s.params.length > 0) setConfiguring(s);
    else add({ actor: s.entity_id, entry: s.name, companions: [], params: {} });
  };

  if (echo) {
    return (
      <div className="sk-echo pl-echo">
        <strong>{t("kp.understood_as")}</strong>
        <ul>
          {echo.items.map((it, i) => (
            <li key={i}>
              <b>{it.actor_label}</b>
              {it.verb && <> · {it.verb}</>}
              {it.targets.length > 0 && <> → {it.targets.map((x) => (x.kind === "entity" ? `@${x.label}` : x.label || t("kp.a_point"))).join(", ")}</>}
              {it.destination && <> ⇒ {it.destination_label || t("kp.a_point")}</>}
              {it.entry && <div className="pl-echo-skill">{t("skill.echo", { name: it.entry })}</div>}
              <div className="sk-hint">{t("kp.item_time", { move: formatDuration(t, it.move_seconds), act: formatDuration(t, it.act_seconds) })}</div>
              {it.detail && <div className="sk-hint">{prettyMentions(it.detail)}</div>}
            </li>
          ))}
        </ul>
        <p>
          <strong>{t("kp.estimate", { total: formatDuration(t, echo.total_seconds) })}</strong> <span className="sk-hint">{t("kp.confirm_hint")}</span>
        </p>
        {echo.conflict && <div className="sk-warn">{t("plan.conflict", { why: echo.conflict })}</div>}
        {echo.unresolved.length > 0 && (
          <div className="sk-warn">
            {t("kp.unresolved")} {echo.unresolved.join(", ")}
          </div>
        )}
        <div className="sk-row">
          <button className="sk-primary" disabled={confirm.busy || echo.unresolved.length > 0 || echo.items.length === 0 || Boolean(echo.conflict)} onClick={doConfirm}>
            {t("kp.confirm")}
          </button>
          <button onClick={() => setEcho(null)}>{t("kp.edit")}</button>
        </div>
        <ErrorBox error={confirm.error} />
      </div>
    );
  }

  return (
    <div className="pl-plan">
      <div className="pl-plan-list">
        {plan.length === 0 && <p className="sk-hint">{t("plan.empty")}</p>}
        {plan.map((p, i) => (
          <div key={p.key} className="pl-plan-item">
            <span className="pl-plan-no">{i + 1}.</span>
            <span className="pl-plan-text">{describePlanned(p, own, skills, t)}</span>
            {p.to &&
              own
                .filter((o) => o.ref !== p.actor)
                .map((o) => (
                  <label key={o.ref} className="sk-inline pl-plan-with">
                    <input
                      type="checkbox"
                      checked={p.companions.includes(o.ref)}
                      onChange={(e) => update(p.key, { companions: e.target.checked ? [...p.companions, o.ref] : p.companions.filter((x) => x !== o.ref) })}
                    />{" "}
                    {t("plan.with", { who: o.name })}
                  </label>
                ))}
            <button type="button" className="sk-link" aria-label={t("plan.remove")} onClick={() => remove(p.key)}>
              ✕
            </button>
          </div>
        ))}
      </div>
      {textBox}
      {configuring && <SkillSetup skill={configuring} targets={targets} onCancel={() => setConfiguring(null)} onAdd={(target, params) => {
        add({ actor: configuring.entity_id, entry: configuring.name, target: target ?? undefined, companions: [], params });
        setConfiguring(null);
      }} />}
      <div className="pl-plan-send">
        <button className="sk-primary" disabled={!collecting || send.busy || (plan.length === 0 && !text.trim())} onClick={doSend}>
          {send.busy ? t("common.working") : t("plan.send")}
        </button>
      </div>
      <ErrorBox error={send.error ?? flip.error} />
      <div className="pl-bar">
        <div className="pl-bar-chars" role="tablist">
          {own.map((o) => (
            <button key={o.ref} type="button" role="tab" aria-selected={o.ref === actor} className={o.ref === actor ? "active" : ""} onClick={() => setActor(o.ref)}>
              {o.name}
            </button>
          ))}
        </div>
        <div className="pl-bar-row">
          <span className="sk-hint pl-bar-move">{t("plan.move_hint")}</span>
        </div>
        {groups.map((g) => (
          <div key={g} className="pl-bar-row">
            <span className="pl-bar-group">{g}</span>
            {buttons
              .filter((s) => (s.group_label || s.group) === g)
              .map((s) => (
                <button key={s.name} type="button" className="pl-skill" disabled={!collecting || s.cooldown} title={s.description} onClick={() => pick(s)}>
                  {s.name}
                  {s.cooldown && <span className="sk-hint"> · {t("skill.cooldown")}</span>}
                </button>
              ))}
          </div>
        ))}
        {toggles.length > 0 && (
          <div className="pl-bar-row">
            <span className="pl-bar-group">{t("plan.switches")}</span>
            {toggles.map((s) => (
              <button key={s.name} type="button" className={`pl-switch ${s.toggle_on ? "on" : ""}`} disabled={!collecting || flip.busy || s.cooldown} title={s.description} onClick={() => doFlip(s)}>
                <span className="pl-switch-dot" />
                {s.name}
              </button>
            ))}
          </div>
        )}
        {note && <p className="pl-note">{note}</p>}
      </div>
    </div>
  );
}

/** 要选对象或参数的技能：选好了加进行动列表。 */
function SkillSetup({ skill, targets, onAdd, onCancel }: { skill: Skill; targets: Target[]; onAdd: (target: Target | null, params: Record<string, number>) => void; onCancel: () => void }) {
  const { t } = useI18n();
  const [target, setTarget] = useState("");
  const [params, setParams] = useState<Record<string, number>>(() =>
    Object.fromEntries(skill.params.map((p) => [p.name, p.choices.length ? choiceParts(p.choices[0]!).value : (p.min ?? 0)])),
  );
  const need = skill.target === "single";
  const chosen = targets.find((x) => x.ref === target) ?? null;
  return (
    <div className="pl-setup sk-card">
      <div>
        <strong>{skill.name}</strong> <span className="sk-hint">{skill.owner}</span>
      </div>
      {skill.description && <p className="sk-hint pl-setup-desc">{skill.description}</p>}
      {need && (
        <label className="pl-setup-row">
          {t("plan.target")}{" "}
          <select value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">{t("plan.pick_target")}</option>
            {targets.map((x) => (
              <option key={x.ref} value={x.ref}>
                {x.label}
              </option>
            ))}
          </select>
        </label>
      )}
      {skill.params.map((p) => (
        <label key={p.name} className="pl-setup-row" title={p.description}>
          {p.label || p.name}{" "}
          {p.choices.length ? (
            <select value={params[p.name] ?? 0} onChange={(e) => setParams({ ...params, [p.name]: Number(e.target.value) })}>
              {p.choices.map((c) => {
                const { label, value } = choiceParts(c);
                return (
                  <option key={c} value={value}>
                    {label}
                  </option>
                );
              })}
            </select>
          ) : (
            <input
              type="number"
              min={p.min ?? undefined}
              max={p.max ?? undefined}
              value={params[p.name] ?? 0}
              onChange={(e) => setParams({ ...params, [p.name]: Number(e.target.value) })}
            />
          )}
          {!p.choices.length && p.max !== null && p.max !== undefined && <span className="sk-hint"> {t("plan.range", { min: String(p.min ?? 0), max: String(p.max) })}</span>}
        </label>
      ))}
      <div className="sk-row">
        <button className="sk-primary" disabled={need && !chosen} onClick={() => onAdd(chosen, params)}>
          {t("plan.add")}
        </button>
        <button className="sk-link" onClick={onCancel}>
          {t("play.close")}
        </button>
      </div>
    </div>
  );
}
