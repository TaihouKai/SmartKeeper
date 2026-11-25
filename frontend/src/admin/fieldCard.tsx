import { useEffect, useState, type ReactNode } from "react";
import type { Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { FormulaInput, moved } from "../ui/components";

type Field = Schemas["FieldDef"];

export function blankField(): Field {
  return { name: "", label: "", description: "", kind: "number", cls: "player", required: true, hidden: false, choices: [], vital: false };
}

export type Scope = "any_entity" | "dice" | "script" | "config" | "check" | "damage" | "stealth" | "search" | "bonus";
export type Validate = (formula: string, template: string | null, inEntry?: string, scope?: Scope, other?: string, names?: string[]) => Promise<{ problems: { code: string }[]; names: string[] }>;

export function useListEdit<T>(list: T[], set: (l: T[]) => void) {
  return {
    update: (i: number, v: T) => set(list.map((x, j) => (j === i ? v : x))),
    remove: (i: number) => set(list.filter((_, j) => j !== i)),
    add: (v: T) => set([...list, v]),
    move: (from: number, to: number) => set(moved(list, from, to)),
  };
}

/** 是/否字段的初值写成了 0、1 以外的数字或文字（多半是填错了）。 */
function badBool(text: string | null | undefined): boolean {
  const v = (text ?? "").trim();
  if (/^-?\d+(\.\d+)?$/.test(v)) return Number(v) !== 0 && Number(v) !== 1;
  return /^(".*"|'.*')$/.test(v);
}

function parseChoices(text: string): string[] {
  return text
    .split(/[|,，、;；]/)
    .map((x) => x.trim())
    .filter(Boolean);
}

/** 常用的可选字段：点一下把这张卡片设成它（运行值资源）。shield 是引擎认得的护盾：受伤时先扣它再扣 hp。 */
const COMMON: Pick<Field, "name" | "kind" | "cls" | "min" | "max" | "initial">[] = [
  { name: "mp", kind: "resource", cls: "runtime", min: "0", max: null, initial: "10" },
  { name: "sp", kind: "resource", cls: "runtime", min: "0", max: null, initial: "10" },
  { name: "san", kind: "resource", cls: "runtime", min: "0", max: null, initial: "50" },
  { name: "shield", kind: "resource", cls: "runtime", min: "0", max: null, initial: "0" },
];

/** 一个字段一张小卡片：第一行是名字、显示名、类型、类别；下面只显示这种类型用得上的设置。 */
export function FieldCard({
  f,
  onChange,
  onRemove,
  validate,
  isAppearance,
  isFly = false,
  isHp = false,
  inGroup,
  mover,
}: {
  f: Field;
  onChange: (f: Field) => void;
  onRemove: () => void;
  validate: (formula: string) => ReturnType<Validate>;
  isAppearance: boolean;
  isFly?: boolean;
  isHp?: boolean;
  inGroup: boolean;
  mover?: ReactNode;
  /** 角色卡上的数值/资源字段：“使用时填写”的列可以从其中一个里扣 */
  spendTargets?: string[];
  /** 规则包里的检定：“使用时填写”的列可以要求过一个检定 */
  checks?: string[];
}) {
  const { t } = useI18n();
  const cls = f.cls ?? "player";
  const numeric = f.kind === "number" || f.kind === "resource";
  // 引擎必需的字段：名字、类型、类别都不能改，也不能删（生命值的上下限、初值可以改）
  const locked = isAppearance || isFly;
  const fixed = locked || isHp;
  const [choicesText, setChoicesText] = useState((f.choices ?? []).join("、"));
  useEffect(() => {
    // 换了一个规则包或版本时，用新的值覆盖输入框
    if (parseChoices(choicesText).join("|") !== (f.choices ?? []).join("|")) setChoicesText((f.choices ?? []).join("、"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [f.choices]);
  return (
    <div className="sk-field">
      <div className="sk-field-main">
        <label>
          {t("rules.f.name")}
          <input value={f.name} disabled={fixed} title={fixed ? t("rules.locked") : undefined} placeholder={t("rules.ph.field_name")} onChange={(e) => onChange({ ...f, name: e.target.value })} />
        </label>
        <label>
          {t("rules.f.label")}
          <input value={f.label ?? ""} placeholder={isAppearance ? t("rules.ph.appearance_label") : isFly ? t("rules.ph.label_can_fly") : t("rules.ph.field_label")} onChange={(e) => onChange({ ...f, label: e.target.value })} />
        </label>
        <label>
          {t("rules.f.kind")}
          <select value={f.kind} disabled={fixed} title={fixed ? t("rules.locked") : undefined} onChange={(e) => onChange({ ...f, kind: e.target.value as Field["kind"] })}>
            <option value="number">{t("rules.kind.number")}</option>
            <option value="resource">{t("rules.kind.resource")}</option>
            <option value="text">{t("rules.kind.text")}</option>
            <option value="boolean">{t("rules.kind.boolean")}</option>
            <option value="formula">{t("rules.kind.formula")}</option>
          </select>
        </label>
        {(!inGroup || f.kind === "number" || f.kind === "boolean") && (
          <label title={inGroup ? t("rules.f.cls_group_hint") : undefined}>
            {t("rules.f.cls")}
            <select value={cls} disabled={fixed} title={fixed ? t("rules.locked") : undefined} onChange={(e) => onChange({ ...f, cls: e.target.value as Field["cls"] })}>
              <option value="player">{t("rules.cls.player")}</option>
              <option value="runtime">{t("rules.cls.runtime")}</option>
            </select>
          </label>
        )}
        <div className="sk-field-side sk-side-actions">
          {mover}
          {fixed ? (
            <span className="sk-badge-req">{t(isHp ? "rules.hp_badge" : isFly ? "rules.can_fly_badge" : "rules.appearance_badge")}</span>
          ) : (
            <button className="sk-link" onClick={onRemove}>
              {t("common.remove")}
            </button>
          )}
        </div>
      </div>
      <p className="sk-hint sk-field-help">
        {isAppearance ? t("rules.help.appearance") : isFly ? t("rules.help.can_fly") : isHp ? t("rules.help.hp") : `${t(`rules.kind_help.${f.kind}`)} ${inGroup ? "" : t(`rules.cls_help.${cls}`)}`}
      </p>
      {!inGroup && !fixed && (
        <p className="sk-hint sk-presets">
          {t("rules.common_fields")}{" "}
          {COMMON.map((c) => (
            <button key={c.name} type="button" className="sk-chip" onClick={() => onChange({ ...f, ...c, label: t(`rules.default_label.${c.name}`), description: f.description })}>
              {c.name} {t(`rules.default_label.${c.name}`)}
            </button>
          ))}
        </p>
      )}
      <label className="sk-field-desc-input">
        {t("rules.f.description")}
        <input value={f.description ?? ""} placeholder={t("rules.ph.field_description")} onChange={(e) => onChange({ ...f, description: e.target.value })} />
      </label>
      {!locked && (
        <div className="sk-field-extra">
          {numeric && (
            <>
              <label>
                {t("rules.f.unit")}
                <input value={f.unit ?? ""} placeholder={t("rules.ph.unit")} onChange={(e) => onChange({ ...f, unit: e.target.value || null })} />
              </label>
              <label>
                {t("rules.f.min")}
                <FormulaInput value={f.min ?? ""} validate={validate} placeholder={t("rules.ph.min")} onChange={(x) => onChange({ ...f, min: x || null })} />
              </label>
              <label>
                {t("rules.f.max")}
                <FormulaInput value={f.max ?? ""} validate={validate} placeholder={f.kind === "resource" ? t("rules.ph.max_resource") : t("rules.ph.max")} onChange={(x) => onChange({ ...f, max: x || null })} />
              </label>
            </>
          )}
          {cls === "runtime" && !inGroup && (f.kind === "number" || f.kind === "resource") && (
            <label className="sk-inline">
              <input type="checkbox" checked={f.vital ?? false} onChange={(e) => onChange({ ...f, vital: e.target.checked })} /> {t("rules.f.vital")}
            </label>
          )}
          {cls === "runtime" && !inGroup && (f.kind === "number" || f.kind === "resource") && (
            <label>
              {t("rules.f.per_minute")}
              <FormulaInput value={f.per_minute ?? ""} validate={validate} placeholder={t("rules.ph.per_minute")} onChange={(x) => onChange({ ...f, per_minute: x || null })} />
            </label>
          )}
          {cls === "runtime" && f.kind !== "text" && f.kind !== "formula" && (
            <label>
              {t(f.kind === "boolean" ? "rules.f.initial_bool" : "rules.f.initial_required")}
              <FormulaInput value={f.initial ?? ""} validate={validate} placeholder={t(f.kind === "boolean" ? "rules.ph.initial_bool" : "rules.ph.initial")} onChange={(x) => onChange({ ...f, initial: x || null })} />
              {f.kind === "boolean" && badBool(f.initial) && <small className="sk-invalid">{t("codes.pack.boolean_initial", { value: f.initial ?? "" })}</small>}
            </label>
          )}
          {(f.kind === "text" || f.kind === "number") && cls === "player" && (
            <label className="sk-wide">
              {t("rules.f.choices")}
              <input
                value={choicesText}
                placeholder={t(f.kind === "number" ? "rules.ph.choices_number" : "rules.ph.choices")}
                onChange={(e) => {
                  setChoicesText(e.target.value);
                  onChange({ ...f, choices: parseChoices(e.target.value) });
                }}
              />
            </label>
          )}
          <div className="sk-field-flags">
            {cls === "player" && f.kind !== "boolean" && (
              <label className="sk-inline">
                <input type="checkbox" checked={f.required ?? true} onChange={(e) => onChange({ ...f, required: e.target.checked })} /> {t("rules.f.required")}
              </label>
            )}
            <label className="sk-inline">
              <input type="checkbox" checked={f.hidden ?? false} onChange={(e) => onChange({ ...f, hidden: e.target.checked })} /> {t("rules.f.hidden")}
            </label>
          </div>
        </div>
      )}
    </div>
  );
}
