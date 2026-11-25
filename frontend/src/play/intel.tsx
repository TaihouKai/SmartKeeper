import type { Schemas } from "../api/client";
import { useI18n } from "../i18n";

type Fact = Schemas["IntelFact"];
type Value = Schemas["IntelValue"];
type T = (k: string, params?: Record<string, string>) => string;

function valueText(v: Value, t: T): string {
  if (v.shown) return v.shown;
  if (typeof v.value === "boolean") return t(v.value ? "intel.yes" : "intel.no");
  return v.value === null || v.value === undefined ? "" : String(v.value);
}

/** 一条情报的文字：字段是“名字：值”，条目是“有「名字」（列：值）”，线索原样。 */
export function factText(f: Fact, t: T): string {
  if (f.kind === "field" && f.field) return t("intel.field", { label: f.field.label || f.field.name, value: valueText(f.field, t) });
  if (f.kind === "entry") {
    const cols = (f.columns ?? []).map((c) => t("intel.field", { label: c.label || c.name, value: valueText(c, t) }));
    return cols.length ? t("intel.entry_cols", { name: f.entry ?? "", cols: cols.join(t("intel.sep")) }) : t("intel.entry", { name: f.entry ?? "" });
  }
  return f.text ?? "";
}

/** 我知道的关于某个人的事。 */
export function IntelFacts({ facts }: { facts: readonly Fact[] }) {
  const { t } = useI18n();
  return (
    <ul className="sk-intel">
      {facts.map((f, i) => (
        <li key={i} className={`sk-intel-${f.source}`}>
          {factText(f, t)}
        </li>
      ))}
    </ul>
  );
}
