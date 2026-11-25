import type { ReactNode } from "react";
import type { Schemas } from "../../api/client";
import { useI18n } from "../../i18n";
import { hasProblem } from "./ctx";
import { selKey, type Pack, type Sel } from "./model";

function Node({ sel, current, onSelect, bad, depth = 0, children, extra }: { sel: Sel; current: Sel; onSelect: (s: Sel) => void; bad: boolean; depth?: number; children: ReactNode; extra?: ReactNode }) {
  const active = selKey(sel) === selKey(current);
  return (
    <div className={`wb-node depth-${depth}${active ? " active" : ""}`}>
      <button type="button" onClick={() => onSelect(sel)} aria-current={active ? "page" : undefined}>
        <span className="wb-node-label">{children}</span>
        {extra}
        {bad && <span className="wb-node-bad" aria-label="!" />}
      </button>
    </div>
  );
}

/** 左边的目录：世界观、各个模板（字段、推导值、分组）和规则包的其余部分。有问题的地方标红点。 */
export function Outline({ pack, current, onSelect, problems, onAddTemplate, onAddGroup }: { pack: Pack; current: Sel; onSelect: (s: Sel) => void; problems: Schemas["Problem"][]; onAddTemplate: () => void; onAddGroup: (t: number) => void }) {
  const { t } = useI18n();
  const bad = (path: string) => hasProblem(problems, path);
  const top = (k: Exclude<Sel["k"], "fields" | "derived" | "group">, label: string, path: string) => (
    <Node sel={{ k } as Sel} current={current} onSelect={onSelect} bad={bad(path)}>
      {label}
    </Node>
  );
  return (
    <nav className="wb-outline" aria-label={t("rules.outline")}>
      {top("world", t("rules.world"), "world")}
      <div className="wb-outline-group">
        <div className="wb-outline-title">
          <span>{t("rules.templates")}</span>
          <button type="button" className="wb-add" title={t("rules.add_template")} aria-label={t("rules.add_template")} onClick={onAddTemplate}>
            +
          </button>
        </div>
        {pack.templates.map((tpl, ti) => {
          const base = `templates[${ti}]`;
          const groups = tpl.groups ?? [];
          return (
            <div key={ti} className="wb-tpl">
              <div className="wb-tpl-name">
                <span>{tpl.label || tpl.name || "?"}</span>
                {tpl.label && <code>{tpl.name}</code>}
              </div>
              <Node sel={{ k: "fields", t: ti }} current={current} onSelect={onSelect} bad={bad(`${base}.fields`) || problems.some((p) => p.path === base)} depth={1} extra={<span className="wb-count">{(tpl.fields ?? []).length}</span>}>
                {t("rules.fields")}
              </Node>
              <Node sel={{ k: "derived", t: ti }} current={current} onSelect={onSelect} bad={bad(`${base}.derived`)} depth={1} extra={<span className="wb-count">{(tpl.derived ?? []).length}</span>}>
                {t("rules.derived")}
              </Node>
              {groups.map((g, gi) => (
                <Node key={gi} sel={{ k: "group", t: ti, g: gi }} current={current} onSelect={onSelect} bad={bad(`${base}.groups[${gi}]`)} depth={1} extra={<span className="wb-count">{(g.presets ?? []).length}</span>}>
                  <span className="wb-node-icon">▦</span>
                  {g.label || g.name || t("rules.g.untitled")}
                </Node>
              ))}
              <button type="button" className="wb-outline-add depth-1" onClick={() => onAddGroup(ti)}>
                + {t("rules.add_group")}
              </button>
            </div>
          );
        })}
      </div>
      <div className="wb-outline-group">
        <div className="wb-outline-title">
          <span>{t("rules.outline_other")}</span>
        </div>
        {top("players", t("rules.path.player_entities"), "player_entities")}
        {top("formulas", t("rules.path.formulas"), "formulas")}
        {top("tables", t("rules.path.tables"), "tables")}
        {top("checks", t("rules.path.checks"), "checks")}
        {top("params", t("rules.path.params"), "params")}
        {top("handbook", t("rules.path.handbook"), "handbook")}
        {top("insights", t("rules.path.insights"), "insights")}
        {top("text", t("rules.outline_text"), "rules_text")}
        {top("samples", t("rules.path.samples"), "samples")}
      </div>
    </nav>
  );
}
