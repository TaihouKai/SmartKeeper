import { useState, type ReactNode } from "react";
import type { Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { FormulaInput, Mover, moved } from "./components";
import { DocsLink } from "./docs";
import { Described } from "./markdown";

export type Param = Schemas["ParamDef"];
type Check = (f: string) => Promise<{ problems: { code: string }[]; names: string[] }>;

export function blankParam(): Param {
  return { name: "", label: "", description: "", choices: [], requires: "", script: "", multiplier: "", duration: "", by_kp: false };
}

function choicesText(p: Param): string {
  return (p.choices ?? []).join("、");
}

function parseChoices(text: string): string[] {
  return text
    .split(/[、,，\n]/)
    .map((x) => x.trim())
    .filter(Boolean);
}

/** 规则包定好的参数：只读，列出名字和说明。 */
export function DefaultParams({ params }: { params: readonly Param[] }) {
  const { t } = useI18n();
  if (!params.length) return null;
  return (
    <details className="sk-default-params">
      <summary className="sk-hint">
        {t("params.defaults")}
        {params.map((p) => p.label || p.name).join("、")}
      </summary>
      <ul>
        {params.map((p) => (
          <li key={p.name}>
            <strong>{p.label || p.name}</strong>
            {p.by_kp && <span className="cf-tag">{t("params.by_kp")}</span>}
            {(p.choices ?? []).length > 0 && <span className="sk-hint">（{(p.choices ?? []).join("、")}）</span>}
            <Described text={p.description} />
          </li>
        ))}
      </ul>
    </details>
  );
}

/** 一串参数：使用时选的数。名字、显示名、可选值、说明常用；其余（条件、检定、冷却、扣什么、倍数……）收在“更多”里。 */
export function ParamsEditor({
  params,
  onChange,
  validate,
  validateScript,
  checks = [],
  spendTargets = [],
  title,
  hint,
}: {
  params: readonly Param[];
  onChange: (p: Param[]) => void;
  validate: Check;
  /** 校验“选了就执行的句子”（脚本）；不给时按公式校验 */
  validateScript?: Check;
  checks?: readonly string[];
  spendTargets?: readonly string[];
  title: string;
  hint?: string;
}) {
  const { t } = useI18n();
  const list = [...params];
  const set = (i: number, p: Param) => onChange(list.map((x, j) => (j === i ? p : x)));
  return (
    <div className="sk-effects sk-params">
      <strong>{title}</strong>
      {hint && <p className="sk-hint">{hint}</p>}
      {list.map((p, i) => (
        <ParamCard key={i} p={p} onChange={(x) => set(i, x)} onRemove={() => onChange(list.filter((_, j) => j !== i))} validate={validate} validateScript={validateScript ?? validate} checks={checks} spendTargets={spendTargets} mover={<Mover index={i} count={list.length} onMove={(a, b) => onChange(moved(list, a, b))} />} />
      ))}
      <button type="button" onClick={() => onChange([...list, blankParam()])}>
        {t("params.add")}
      </button>
    </div>
  );
}

function ParamCard({ p, onChange, onRemove, validate, validateScript, checks, spendTargets, mover }: { p: Param; onChange: (p: Param) => void; onRemove: () => void; validate: Check; validateScript: Check; checks: readonly string[]; spendTargets: readonly string[]; mover: ReactNode }) {
  const { t } = useI18n();
  const [text, setText] = useState(choicesText(p));
  // 外面换了参数（换了一条、挪了位置）：显示的文字跟着换
  if (parseChoices(text).join("、") !== choicesText(p)) setText(choicesText(p));
  const more = Boolean(p.requires || p.check || p.cooldown || p.spends || p.script || p.multiplier || p.duration || p.min || p.max);
  return (
    <div className="sk-param">
      <div className="sk-row">
        <input className="sk-small-input" value={p.name} placeholder={t("params.name")} onChange={(e) => onChange({ ...p, name: e.target.value.trim() })} />
        <input value={p.label ?? ""} placeholder={t("params.label")} onChange={(e) => onChange({ ...p, label: e.target.value })} />
        <label className="sk-inline" title={t("params.by_kp_hint")}>
          <input type="checkbox" checked={p.by_kp ?? false} onChange={(e) => onChange({ ...p, by_kp: e.target.checked })} /> {t("params.by_kp")}
        </label>
        <input
          className="sk-grow"
          value={text}
          placeholder={t("params.choices")}
          onChange={(e) => {
            setText(e.target.value);
            onChange({ ...p, choices: parseChoices(e.target.value) });
          }}
        />
        {mover}
        <button type="button" className="sk-link" onClick={onRemove}>
          {t("common.remove")}
        </button>
      </div>
      <input value={p.description ?? ""} placeholder={t("params.description")} onChange={(e) => onChange({ ...p, description: e.target.value })} />
      <details open={more}>
        <summary className="sk-hint">{t("params.more")}</summary>
        <div className="sk-param-grid">
          <label title={t("params.min_hint")}>
            {t("params.min")}
            <FormulaInput value={p.min ?? ""} validate={validate} onChange={(x) => onChange({ ...p, min: x || null })} />
          </label>
          <label title={t("params.min_hint")}>
            {t("params.max")}
            <FormulaInput value={p.max ?? ""} validate={validate} onChange={(x) => onChange({ ...p, max: x || null })} />
          </label>
          <label title={t("params.requires_hint")}>
            {t("params.requires")}
            <FormulaInput value={p.requires ?? ""} validate={validate} placeholder={t("params.requires_ph")} onChange={(x) => onChange({ ...p, requires: x })} />
          </label>
          <label title={t("params.check_hint")}>
            {t("params.check")}
            <select value={p.check ?? ""} onChange={(e) => onChange({ ...p, check: e.target.value || null })}>
              <option value="">{t("params.none")}</option>
              {checks.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label title={t("params.cooldown_hint")}>
            {t("params.cooldown")}
            <FormulaInput value={p.cooldown ?? ""} validate={validate} placeholder={t("params.cooldown_ph")} onChange={(x) => onChange({ ...p, cooldown: x || null })} />
          </label>
          <label title={t("params.spends_hint")}>
            {t("params.spends")}
            <select value={p.spends ?? ""} onChange={(e) => onChange({ ...p, spends: e.target.value || null })}>
              <option value="">{t("params.none")}</option>
              {spendTargets.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label title={t("params.multiplier_hint")}>
            {t("params.multiplier")}
            <FormulaInput value={p.multiplier ?? ""} validate={validate} placeholder={t("params.multiplier_ph")} onChange={(x) => onChange({ ...p, multiplier: x })} />
          </label>
          <label title={t("params.duration_hint")}>
            {t("params.duration")}
            <FormulaInput value={p.duration ?? ""} validate={validate} placeholder={t("params.duration_ph")} onChange={(x) => onChange({ ...p, duration: x })} />
          </label>
          <label className="sk-wide" title={t("params.script_hint")}>
            {t("params.script")}
            <FormulaInput value={p.script ?? ""} validate={validateScript} multiline placeholder={t("params.script_ph")} onChange={(x) => onChange({ ...p, script: x })} />
          </label>
        </div>
        <DocsLink text={t("params.hint")} query="this." />
      </details>
    </div>
  );
}
