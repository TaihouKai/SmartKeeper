import { Fragment, useCallback, useState } from "react";
import type { Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { FormulaInput, Mover } from "../ui/components";
import { BonusEditor, FieldInput, fieldLabel } from "../ui/EntryEditor";
import { ParamsEditor } from "../ui/ParamEditor";
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

/** 一行的“编辑”按钮：在 IDE 里打开这一条的设置和效果。圆点：灰色是效果还没写，绿色是没问题，红色是有问题。 */
function EditButton({ path, script }: { path: string; script: string }) {
  const { t } = useI18n();
  const wb = useWorkbench();
  const empty = !script.trim();
  const bad = hasProblem(wb.problems, `${path}.script`) || hasProblem(wb.problems, `${path}.config`);
  const state = bad ? "bad" : empty ? "empty" : "ok";
  return (
    <button type="button" className={`wb-script-btn ${state}${wb.active === path ? " active" : ""}`} onClick={() => wb.open(path)} title={t(`rules.gt.script_${state}`)}>
      <span className="wb-dot" />
      {t("rules.gt.edit")}
    </button>
  );
}

/**
 * 一个分组的条目表：每一行是一个规则写好的条目（固定条目），每一列是一项要填的内容。
 * 名称、技能脚本、ID、描述、生效条件是每行自带的列；其余的列是这个分组的字段，点列名在表格下面改这一列的设置。
 * 技能脚本点按钮在右边的 IDE 里写；修正和范围形状放不进格子，点“更多”在这一行下面展开。
 * base 是这个分组在规则包里的路径（templates[0].groups[1]），IDE 和校验问题都按路径对应。
 */
type Use = Schemas["EntryUse"];

/** 一串用途（物品的几种用法，或分组的用途模板）：名字、说明、开关、开着时的修正、这个用途自己的参数；
 * 设置和脚本点“编辑”在 IDE 里写。 */
function UsesEditor({ uses, onChange, path, hint, validate, vBonus, checks, spendTargets }: { uses: Use[]; onChange: (u: Use[]) => void; path: string; hint: string; derived: string[]; validate: (f: string) => ReturnType<Validate>; vBonus: (f: string) => ReturnType<Validate>; checks: string[]; spendTargets: string[] }) {
  const { t } = useI18n();
  const ed = useListEdit(uses, onChange);
  return (
    <div className="sk-effects">
      <strong>{t("rules.uses.title")}</strong>
      <p className="sk-hint">{hint}</p>
      {uses.map((u, j) => (
        <div key={j} className="sk-use">
          <div className="sk-effect">
            <input placeholder={t("rules.uses.name")} value={u.name} onChange={(e) => ed.update(j, { ...u, name: e.target.value })} />
            <input className="sk-wide" placeholder={t("rules.uses.description")} value={u.description ?? ""} onChange={(e) => ed.update(j, { ...u, description: e.target.value })} />
            <label className="sk-inline" title={t("uses.toggle_hint")}>
              <input type="checkbox" checked={u.toggle ?? false} onChange={(e) => ed.update(j, { ...u, toggle: e.target.checked })} /> {t("uses.toggle")}
            </label>
            {u.toggle && (
              <label className="sk-inline">
                <input type="checkbox" checked={u.default_on ?? false} onChange={(e) => ed.update(j, { ...u, default_on: e.target.checked })} /> {t("uses.default_on")}
              </label>
            )}
            <EditButton path={`${path}[${j}]`} script={u.script ?? ""} />
            {!(u.script ?? "").trim() && !(u.config ?? "").trim() && !u.toggle && <small className="sk-hint">{t("rules.uses.kp_rules")}</small>}
            <Mover index={j} count={uses.length} onMove={ed.move} />
            <button type="button" className="sk-link" onClick={() => ed.remove(j)}>
              {t("common.remove")}
            </button>
          </div>
          {u.toggle && <BonusEditor bonus={u.bonus ?? ""} legacy={u.effects ?? []} validate={vBonus} title={t("uses.effects")} onChange={(bonus) => ed.update(j, { ...u, bonus, effects: [] })} />}
          <ParamsEditor params={u.params ?? []} onChange={(params) => ed.update(j, { ...u, params })} validate={validate} checks={checks} spendTargets={spendTargets} title={t("params.use_own")} />
        </div>
      ))}
      <button type="button" onClick={() => ed.add({ name: "", description: "", config: "", script: "", params: [], toggle: false, default_on: false, effects: [], bonus: "" })}>
        {t("rules.uses.add")}
      </button>
    </div>
  );
}

export function GroupTable({ g, onChange, validate, template, derived, spendTargets, base, checks = [] }: { g: Group; onChange: (g: Group) => void; validate: Validate; template: string; derived: string[]; spendTargets: string[]; base: string; checks?: string[] }) {
  const { t } = useI18n();
  const wb = useWorkbench();
  const fields = g.fields ?? [];
  const presets = g.presets ?? [];
  const pre = useListEdit(presets, (x) => onChange({ ...g, presets: x }));
  const [col, setCol] = useState<number | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  // 列的上下限可以用 this.<列名>，所以按条目校验
  const vCol = useCallback((f: string) => validate(f, template, g.name), [validate, template, g.name]);
  const vWhen = useCallback((f: string) => validate(f, template), [validate, template]);
  const vDice = useCallback((f: string) => validate(f, template, g.name, "dice"), [validate, template, g.name]);
  const vEff = useCallback((f: string) => validate(f, template, g.name), [validate, template, g.name]);
  const vBonus = useCallback((f: string) => validate(f, template, g.name, "bonus"), [validate, template, g.name]);
  const setRow = (r: number, patch: Partial<Preset>) => pre.update(r, { ...presets[r]!, ...patch });
  const rowPath = (r: number) => `${base}.presets[${r}]`;
  const scripts = g.effects !== false;
  const more = g.effects !== false;

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
  const width = 6 + (scripts ? 1 : 0) + fields.length;

  return (
    <div>
      <div className="sk-scroll wb-table-wrap">
        <table className="sk-table sk-entry-table">
          <thead>
            <tr>
              <th />
              <th>{t("character.entry_name")}</th>
              {scripts && <th>{t("rules.gt.skill_col")}</th>}
              <th title={t("rules.gt.id_hint")}>{t("rules.gt.id")}</th>
              <th>{t("character.entry_description")}</th>
              <th>{t("rules.gt.when")}</th>
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
                <tr className={wb.active === rowPath(r) || wb.active?.startsWith(`${rowPath(r)}.`) ? "wb-row-active" : undefined}>
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
                      <EditButton path={rowPath(r)} script={p.script ?? ""} />
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
                  {fields.map((f, i) => (
                    <td key={i}>
                      {f.cls === "runtime" ? (
                        <span className="sk-hint">{t("rules.gt.runtime_cell")}</span>
                      ) : (
                        <FieldInput
                          def={f}
                          value={(p.fields ?? {})[f.name] as Cell}
                          validateFormula={vDice}
                          onChange={(v) => setRow(r, { fields: clean({ ...(p.fields ?? {}), [f.name]: v }) })}
                          onExpand={f.kind === "formula" ? () => wb.open(`${rowPath(r)}.fields.${f.name}`) : undefined}
                        />
                      )}
                      {f.cls !== "runtime" && !(f.name in (p.fields ?? {})) && <small className="sk-hint" title={t("rules.gt.player_fills_hint")}>{t("rules.gt.player_fills")}</small>}
                    </td>
                  ))}
                  <td className="sk-nowrap">
                    {more && (
                      <button type="button" className="sk-link" onClick={() => setOpen(open === r ? null : r)}>
                        {t("rules.gt.more", { n: String((p.effects ?? []).length + (p.uses ?? []).length) })}
                      </button>
                    )}
                  </td>
                </tr>
                {open === r && (
                  <tr className="sk-subrow">
                    <td colSpan={width}>
                      {g.effects !== false && <BonusEditor bonus={p.bonus ?? ""} legacy={p.effects ?? []} validate={vBonus} onChange={(bonus) => setRow(r, { bonus, effects: [] })} />}
                      <ParamsEditor params={p.params ?? []} onChange={(params) => setRow(r, { params })} validate={vEff} checks={checks} spendTargets={spendTargets} title={t(g.uses ? "params.item_own" : "params.own")} hint={t("params.own_hint")} />
                      {g.uses && <UsesEditor uses={p.uses ?? []} path={`${rowPath(r)}.uses`} hint={t("rules.uses.hint")} derived={derived} validate={vEff} vBonus={vBonus} checks={checks} spendTargets={spendTargets} onChange={(uses) => setRow(r, { uses })} />}
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
      <button type="button" onClick={() => pre.add({ name: "", id: "", description: "", fields: {}, effects: [], bonus: "", config: "", script: "", when: "", uses: [], params: [] })}>
        {t("rules.gt.add_row")}
      </button>
      {g.effects !== false && g.uses && (
        <div className="sk-card">
          <UsesEditor uses={g.use_templates ?? []} path={`${base}.use_templates`} hint={t("rules.uses.templates_hint")} derived={derived} validate={vEff} vBonus={vBonus} checks={checks} spendTargets={spendTargets} onChange={(use_templates) => onChange({ ...g, use_templates })} />
        </div>
      )}
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
