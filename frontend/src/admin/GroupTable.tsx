import { Fragment, useCallback, useState } from "react";
import type { Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { FormulaInput, Mover } from "../ui/components";
import { EffectsEditor, FieldInput, ShapeEditor, fieldLabel, type Effect, type Shape } from "../ui/EntryEditor";
import { FieldCard, blankField, useListEdit, type Validate } from "./fieldCard";

type Field = Schemas["FieldDef"];
type Group = Schemas["GroupDef"];
type Preset = Schemas["GroupPreset"];
type Cell = string | number | boolean | undefined;

/** 清空的数字框是 ""，不存进规则包。 */
function clean(fields: Record<string, unknown>): Preset["fields"] {
  return Object.fromEntries(Object.entries(fields).filter(([, v]) => v !== "" && v !== undefined)) as Preset["fields"];
}

function effectsOf(p: Preset): Effect[] {
  return (p.effects ?? []).map((e) => ({ description: e.description ?? "", target: e.target ?? null, formula: e.formula ?? null }));
}

/**
 * 一个分组的条目表：每一行是一个规则写好的条目（固定条目），每一列是一项要填的内容。
 * “生效条件”“名称”“描述”是每行自带的列；其余的列是这个分组的字段，点列名在表格下面改这一列的设置。
 * 效果和范围形状放不进格子，点“更多”在这一行下面展开。
 */
export function GroupTable({ g, onChange, validate, template, derived }: { g: Group; onChange: (g: Group) => void; validate: Validate; template: string; derived: string[] }) {
  const { t } = useI18n();
  const fields = g.fields ?? [];
  const presets = g.presets ?? [];
  const shapes = g.shapes?.allowed ?? [];
  const pre = useListEdit(presets, (x) => onChange({ ...g, presets: x }));
  const [col, setCol] = useState<number | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const vCol = useCallback((f: string) => validate(f, template), [validate, template]);
  const vWhen = useCallback((f: string) => validate(f, template), [validate, template]);
  const vDice = useCallback((f: string) => validate(f, template, g.name, "dice"), [validate, template, g.name]);
  const vEff = useCallback((f: string) => validate(f, template, g.name), [validate, template, g.name]);
  const setRow = (r: number, patch: Partial<Preset>) => pre.update(r, { ...presets[r]!, ...patch });

  // 列的增删改：改名字时每一行里这一格的值跟着改键，删列时每一行里这一格的值也删掉
  const setColumn = (i: number, next: Field) => {
    const prev = fields[i]!.name;
    const renamed = prev !== next.name;
    onChange({
      ...g,
      fields: fields.map((x, j) => (j === i ? next : x)),
      presets: renamed
        ? presets.map((p) => {
            const { [prev]: v, ...rest } = (p.fields ?? {}) as Record<string, unknown>;
            return { ...p, fields: clean(v === undefined ? rest : { ...rest, [next.name]: v }) };
          })
        : presets,
    });
  };
  const removeColumn = (i: number) => {
    const name = fields[i]!.name;
    onChange({
      ...g,
      fields: fields.filter((_, j) => j !== i),
      presets: presets.map((p) => {
        const { [name]: _drop, ...rest } = (p.fields ?? {}) as Record<string, unknown>;
        return { ...p, fields: clean(rest) };
      }),
    });
    setCol(null);
  };
  const moveColumn = (from: number, to: number) => {
    const next = [...fields];
    const [x] = next.splice(from, 1);
    next.splice(to, 0, x!);
    onChange({ ...g, fields: next });
    setCol(to);
  };
  const width = 5 + fields.length;

  return (
    <div>
      <div className="sk-scroll">
        <table className="sk-table sk-entry-table">
          <thead>
            <tr>
              <th />
              <th>{t("rules.gt.when")}</th>
              <th>{t("character.entry_name")}</th>
              <th>{t("character.entry_description")}</th>
              {fields.map((f, i) => (
                <th key={i}>
                  <button type="button" className={col === i ? "sk-link sk-col-active" : "sk-link"} onClick={() => setCol(col === i ? null : i)}>
                    {fieldLabel(f, t("character.unnamed_field"))}
                  </button>
                  <div className="sk-hint">{t(`rules.kind.${f.kind}`)}</div>
                </th>
              ))}
              <th>
                <button type="button" onClick={() => { onChange({ ...g, fields: [...fields, blankField()] }); setCol(fields.length); }}>
                  {t("rules.gt.add_column")}
                </button>
              </th>
            </tr>
          </thead>
          <tbody>
            {presets.map((p, r) => (
              <Fragment key={r}>
                <tr>
                  <td className="sk-nowrap">
                    <Mover index={r} count={presets.length} onMove={pre.move} />
                    <button type="button" className="sk-link" onClick={() => pre.remove(r)}>
                      {t("common.remove")}
                    </button>
                  </td>
                  <td>
                    <FormulaInput value={p.when ?? ""} validate={vWhen} placeholder={t("rules.gt.always")} onChange={(x) => setRow(r, { when: x })} />
                  </td>
                  <td>
                    <input value={p.name} onChange={(e) => setRow(r, { name: e.target.value })} />
                  </td>
                  <td>
                    <textarea rows={1} value={p.description ?? ""} onChange={(e) => setRow(r, { description: e.target.value })} />
                  </td>
                  {fields.map((f, i) => (
                    <td key={i}>
                      <FieldInput
                        def={f}
                        value={(p.fields ?? {})[f.name] as Cell}
                        validateFormula={vDice}
                        onChange={(v) => setRow(r, { fields: clean({ ...(p.fields ?? {}), [f.name]: v }) })}
                      />
                    </td>
                  ))}
                  <td className="sk-nowrap">
                    {(g.effects !== false || shapes.length > 0) && (
                      <button type="button" className="sk-link" onClick={() => setOpen(open === r ? null : r)}>
                        {t("rules.gt.more", { n: String((p.effects ?? []).length) })}
                      </button>
                    )}
                  </td>
                </tr>
                {open === r && (
                  <tr className="sk-subrow">
                    <td colSpan={width}>
                      {g.effects !== false && <EffectsEditor effects={effectsOf(p)} derived={derived} validate={vEff} withPriority={false} onChange={(effects) => setRow(r, { effects })} />}
                      {shapes.length > 0 && <ShapeEditor allowed={shapes} shape={(p.shape ?? null) as Shape | null} onChange={(shape) => setRow(r, { shape })} />}
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {presets.length === 0 && (
              <tr>
                <td colSpan={width} className="sk-hint">
                  {t("rules.gt.empty")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <button type="button" onClick={() => pre.add({ name: "", description: "", fields: {}, effects: [], shape: null, when: "" })}>
        {t("rules.gt.add_row")}
      </button>
      {col !== null && fields[col] && (
        <div className="sk-card sk-col-edit">
          <strong>{t("rules.gt.column", { name: fieldLabel(fields[col]!, t("character.unnamed_field")) })}</strong>
          <FieldCard
            f={fields[col]!}
            inGroup
            isAppearance={false}
            validate={vCol}
            onChange={(x) => setColumn(col, x)}
            onRemove={() => removeColumn(col)}
            mover={<Mover index={col} count={fields.length} onMove={moveColumn} />}
          />
          <button type="button" className="sk-link" onClick={() => setCol(null)}>
            {t("play.close")}
          </button>
        </div>
      )}
    </div>
  );
}
