import { useEffect, useState, type ReactNode } from "react";
import type { Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { FormulaInput, moved } from "../ui/components";

type Field = Schemas["FieldDef"];

export function blankField(): Field {
  return { name: "", label: "", description: "", kind: "number", cls: "player", required: true, hidden: false, choices: [] };
}

export type Scope = "any_entity" | "dice";
export type Validate = (formula: string, template: string | null, inEntry?: string, scope?: Scope) => Promise<{ problems: { code: string }[]; names: string[] }>;

export function useListEdit<T>(list: T[], set: (l: T[]) => void) {
  return {
    update: (i: number, v: T) => set(list.map((x, j) => (j === i ? v : x))),
    remove: (i: number) => set(list.filter((_, j) => j !== i)),
    add: (v: T) => set([...list, v]),
    move: (from: number, to: number) => set(moved(list, from, to)),
  };
}

function parseChoices(text: string): string[] {
  return text
    .split(/[|,，、]/)
    .map((x) => x.trim())
    .filter(Boolean);
}

/** 一个字段一张小卡片：第一行是名字、显示名、类型、类别；下面只显示这种类型用得上的设置。 */
export function FieldCard({
  f,
  onChange,
  onRemove,
  validate,
  isAppearance,
  isFly = false,
  inGroup,
  mover,
  spendTargets = [],
}: {
  f: Field;
  onChange: (f: Field) => void;
  onRemove: () => void;
  validate: (formula: string) => ReturnType<Validate>;
  isAppearance: boolean;
  isFly?: boolean;
  inGroup: boolean;
  mover?: ReactNode;
  /** 角色卡上的数值/资源字段：“使用时填写”的列可以从其中一个里扣 */
  spendTargets?: string[];
}) {
  const { t } = useI18n();
  const cls = inGroup ? "player" : (f.cls ?? "player");
  const numeric = f.kind === "number" || f.kind === "resource" || f.kind === "param";
  // 引擎必需的字段：名字、类型、类别都不能改，也不能删
  const locked = isAppearance || isFly;
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
          <input value={f.name} disabled={locked} title={locked ? t("rules.locked") : undefined} placeholder={t("rules.ph.field_name")} onChange={(e) => onChange({ ...f, name: e.target.value })} />
        </label>
        <label>
          {t("rules.f.label")}
          <input value={f.label ?? ""} placeholder={isAppearance ? t("rules.ph.appearance_label") : isFly ? t("rules.ph.label_can_fly") : t("rules.ph.field_label")} onChange={(e) => onChange({ ...f, label: e.target.value })} />
        </label>
        <label>
          {t("rules.f.kind")}
          <select value={f.kind} disabled={locked} title={locked ? t("rules.locked") : undefined} onChange={(e) => onChange({ ...f, kind: e.target.value as Field["kind"] })}>
            <option value="number">{t("rules.kind.number")}</option>
            <option value="resource">{t("rules.kind.resource")}</option>
            <option value="text">{t("rules.kind.text")}</option>
            <option value="boolean">{t("rules.kind.boolean")}</option>
            <option value="formula">{t("rules.kind.formula")}</option>
            {inGroup && <option value="param">{t("rules.kind.param")}</option>}
          </select>
        </label>
        {!inGroup && (
          <label>
            {t("rules.f.cls")}
            <select value={cls} disabled={locked} title={locked ? t("rules.locked") : undefined} onChange={(e) => onChange({ ...f, cls: e.target.value as Field["cls"] })}>
              <option value="player">{t("rules.cls.player")}</option>
              <option value="runtime">{t("rules.cls.runtime")}</option>
            </select>
          </label>
        )}
        <div className="sk-field-side sk-side-actions">
          {mover}
          {locked ? (
            <span className="sk-badge-req">{t(isFly ? "rules.can_fly_badge" : "rules.appearance_badge")}</span>
          ) : (
            <button className="sk-link" onClick={onRemove}>
              {t("common.remove")}
            </button>
          )}
        </div>
      </div>
      <p className="sk-hint sk-field-help">
        {isAppearance ? t("rules.help.appearance") : isFly ? t("rules.help.can_fly") : `${t(`rules.kind_help.${f.kind}`)} ${inGroup ? "" : t(`rules.cls_help.${cls}`)}`}
      </p>
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
                {f.kind === "resource" ? t("rules.f.max_required") : t("rules.f.max")}
                <FormulaInput value={f.max ?? ""} validate={validate} placeholder={f.kind === "resource" ? t("rules.ph.max_resource") : t("rules.ph.max")} onChange={(x) => onChange({ ...f, max: x || null })} />
              </label>
            </>
          )}
          {f.kind === "param" && (
            <label>
              {t("rules.f.spends")}
              <select value={f.spends ?? ""} onChange={(e) => onChange({ ...f, spends: e.target.value || null })}>
                <option value="">{t("rules.f.spends_none")}</option>
                {spendTargets.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
          )}
          {cls === "runtime" && f.kind !== "text" && f.kind !== "formula" && f.kind !== "param" && (
            <label>
              {t("rules.f.initial_required")}
              <FormulaInput value={f.initial ?? ""} validate={validate} placeholder={t("rules.ph.initial")} onChange={(x) => onChange({ ...f, initial: x || null })} />
            </label>
          )}
          {f.kind === "text" && cls === "player" && (
            <label className="sk-wide">
              {t("rules.f.choices")}
              <input
                value={choicesText}
                placeholder={t("rules.ph.choices")}
                onChange={(e) => {
                  setChoicesText(e.target.value);
                  onChange({ ...f, choices: parseChoices(e.target.value) });
                }}
              />
            </label>
          )}
          <div className="sk-field-flags">
            {cls === "player" && f.kind !== "boolean" && f.kind !== "param" && (
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
