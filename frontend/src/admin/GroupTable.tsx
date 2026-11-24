import { Fragment, useCallback, useState } from "react";
import type { Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { FormulaInput, Mover } from "../ui/components";
import { EffectsEditor, FieldInput, PlacementEditor, ShapeEditor, fieldLabel, type Effect, type PlacementSpec, type Shape } from "../ui/EntryEditor";
import { FieldCard, blankField, useListEdit, type Validate } from "./fieldCard";
import { hasProblem, useWorkbench } from "./rules/ctx";

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

/** 一行的技能脚本按钮：在 IDE 里打开。圆点：灰色是还没写，绿色是写了没问题，红色是有问题。 */
function ScriptButton({ path, script }: { path: string; script: string }) {
  const { t } = useI18n();
  const wb = useWorkbench();
  const empty = !script.trim();
  const bad = hasProblem(wb.problems, path);
  const state = empty ? "empty" : bad ? "bad" : "ok";
  return (
    <button type="button" className={`wb-script-btn ${state}${wb.active === path ? " active" : ""}`} onClick={() => wb.open(path)} title={t(`rules.gt.script_${state}`)}>
      <span className="wb-dot" />
      {empty ? t("rules.gt.script_add") : t("rules.gt.script")}
    </button>
  );
}

/**
 * 一个分组的条目表：每一行是一个规则写好的条目（固定条目），每一列是一项要填的内容。
 * 名称、技能脚本、ID、描述、生效条件是每行自带的列；其余的列是这个分组的字段，点列名在表格下面改这一列的设置。
 * 技能脚本点按钮在右边的 IDE 里写；修正和范围形状放不进格子，点“更多”在这一行下面展开。
 * base 是这个分组在规则包里的路径（templates[0].groups[1]），IDE 和校验问题都按路径对应。
 */
export function GroupTable({ g, onChange, validate, template, derived, spendTargets, base }: { g: Group; onChange: (g: Group) => void; validate: Validate; template: string; derived: string[]; spendTargets: string[]; base: string }) {
  const { t } = useI18n();
  const wb = useWorkbench();
  const fields = g.fields ?? [];
  const presets = g.presets ?? [];
  const shapes = g.shapes?.allowed ?? [];
  const pre = useListEdit(presets, (x) => onChange({ ...g, presets: x }));
  const [col, setCol] = useState<number | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  // 列的上下限可以用 this.<列名>，所以按条目校验
  const vCol = useCallback((f: string) => validate(f, template, g.name), [validate, template, g.name]);
  const vWhen = useCallback((f: string) => validate(f, template), [validate, template]);
  const vDice = useCallback((f: string) => validate(f, template, g.name, "dice"), [validate, template, g.name]);
  const vEff = useCallback((f: string) => validate(f, template, g.name), [validate, template, g.name]);
  const setRow = (r: number, patch: Partial<Preset>) => pre.update(r, { ...presets[r]!, ...patch });
  const rowPath = (r: number) => `${base}.presets[${r}]`;
  const scripts = g.effects !== false;
  const more = g.effects !== false || shapes.length > 0 || !!g.placements;

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
  const width = 6 + (scripts ? 1 : 0) + fields.length + (g.timing ? 2 : 0);

  return (
    <div>
      <div className="sk-scroll wb-table-wrap">
        <table className="sk-table sk-entry-table">
          <thead>
            <tr>
              <th />
              <th>{t("character.entry_name")}</th>
              {scripts && <th>{t("rules.gt.script_col")}</th>}
              <th title={t("rules.gt.id_hint")}>{t("rules.gt.id")}</th>
              <th>{t("character.entry_description")}</th>
              <th>{t("rules.gt.when")}</th>
              {g.timing && <th title={t("rules.gt.timing_hint")}>{t("rules.gt.cast_time")}</th>}
              {g.timing && <th title={t("rules.gt.timing_hint")}>{t("rules.gt.cooldown")}</th>}
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
                <tr className={wb.active?.startsWith(`${rowPath(r)}.`) ? "wb-row-active" : undefined}>
                  <td className="sk-nowrap">
                    <Mover index={r} count={presets.length} onMove={pre.move} />
                    <button type="button" className="sk-link" onClick={() => pre.remove(r)}>
                      {t("common.remove")}
                    </button>
                  </td>
                  <td>
                    <input value={p.name} onChange={(e) => setRow(r, { name: e.target.value })} />
                  </td>
                  {scripts && (
                    <td className="sk-nowrap">
                      <ScriptButton path={`${rowPath(r)}.script`} script={p.script ?? ""} />
                    </td>
                  )}
                  <td>
                    <input value={p.id ?? ""} placeholder={t("rules.gt.id_ph")} onChange={(e) => setRow(r, { id: e.target.value.trim() })} />
                  </td>
                  <td>
                    <textarea rows={1} value={p.description ?? ""} onChange={(e) => setRow(r, { description: e.target.value })} />
                  </td>
                  <td>
                    <FormulaInput value={p.when ?? ""} validate={vWhen} placeholder={t("rules.gt.always")} onChange={(x) => setRow(r, { when: x })} onExpand={() => wb.open(`${rowPath(r)}.when`)} />
                  </td>
                  {g.timing && (
                    <td>
                      <FormulaInput value={p.cast_time ?? ""} validate={vEff} placeholder={t("rules.gt.instant")} onChange={(x) => setRow(r, { cast_time: x })} onExpand={() => wb.open(`${rowPath(r)}.cast_time`)} />
                    </td>
                  )}
                  {g.timing && (
                    <td>
                      <FormulaInput value={p.cooldown ?? ""} validate={vEff} placeholder={t("rules.gt.no_cd")} onChange={(x) => setRow(r, { cooldown: x })} onExpand={() => wb.open(`${rowPath(r)}.cooldown`)} />
                    </td>
                  )}
                  {fields.map((f, i) => (
                    <td key={i}>
                      {f.kind === "param" ? (
                        <span className="sk-hint">{t("rules.gt.param_cell")}</span>
                      ) : (
                        <FieldInput
                          def={f}
                          value={(p.fields ?? {})[f.name] as Cell}
                          validateFormula={vDice}
                          onChange={(v) => setRow(r, { fields: clean({ ...(p.fields ?? {}), [f.name]: v }) })}
                          onExpand={f.kind === "formula" ? () => wb.open(`${rowPath(r)}.fields.${f.name}`) : undefined}
                        />
                      )}
                    </td>
                  ))}
                  <td className="sk-nowrap">
                    {more && (
                      <button type="button" className="sk-link" onClick={() => setOpen(open === r ? null : r)}>
                        {t("rules.gt.more", { n: String((p.effects ?? []).length + (p.shape ? 1 : 0) + (p.placement ? 1 : 0)) })}
                      </button>
                    )}
                  </td>
                </tr>
                {open === r && (
                  <tr className="sk-subrow">
                    <td colSpan={width}>
                      {g.effects !== false && <EffectsEditor effects={effectsOf(p)} derived={derived} validate={vEff} withPriority={false} onChange={(effects) => setRow(r, { effects })} />}
                      {shapes.length > 0 && <ShapeEditor allowed={shapes} shape={(p.shape ?? null) as Shape | null} onChange={(shape) => setRow(r, { shape })} />}
                      {g.placements && <PlacementEditor spec={(p.placement ?? null) as PlacementSpec | null} validate={vEff} onChange={(placement) => setRow(r, { placement: placement ? { radius: placement.radius, perceive_multiplier: placement.perceive_multiplier ?? "1", charges: placement.charges ?? "", duration: placement.duration ?? "", notify_owner: placement.notify_owner ?? true } : null })} />}
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
      <button type="button" onClick={() => pre.add({ name: "", id: "", description: "", fields: {}, effects: [], script: "", shape: null, when: "", cast_time: "", cooldown: "" })}>
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
            spendTargets={spendTargets}
          />
          <button type="button" className="sk-link" onClick={() => setCol(null)}>
            {t("play.close")}
          </button>
        </div>
      )}
    </div>
  );
}
