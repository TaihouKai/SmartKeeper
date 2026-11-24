import { useI18n } from "../i18n";

// 例子是公式代码，不翻译；说明文字走翻译表。函数表要和后端 smartkeeper/lang/formula.py 的 FUNCTIONS 一致（有测试检查）。
const BASICS: [string, string][] = [
  ["str * 2 + (dex - 10) / 2", "fh.b.arith"],
  ["str >= 50", "fh.b.compare"],
  ['occupation == "doctor"', "fh.b.text"],
  ['2 if job == "mage" else 1', "fh.b.ifexp"],
  ["1 < x <= 3 and not dead", "fh.b.logic"],
  ["x % 3    x // 2    x ** 2", "fh.b.ops"],
  ["hp_max", "fh.b.names"],
  ["self.hp", "fh.b.self"],
  ["this.level", "fh.b.this"],
  ["companion.str", "fh.b.peer"],
  ["hero.fireball", "fh.b.entry"],
  ["hero.fireball.level", "fh.b.entry_col"],
  ["target.hp", "fh.b.target"],
  ['target.template == "monster"', "fh.b.template"],
  ["count(companion.traits.rank, 3)", "fh.b.count"],
  ["sum(talents.cost)", "fh.b.sum"],
];

const DICE: [string, string][] = [
  ["3d6", "fh.d.basic"],
  ["d20    d%", "fh.d.one"],
  ["1dstr    2d(str + 1)", "fh.d.field"],
  ["dice(level, luck)", "fh.d.names"],
  ["2d6 * 5", "fh.d.order"],
  ["highest(4, 6, 3)", "fh.d.keep"],
];

const SCRIPT: [string, string][] = [
  ["target.damage(this.damage)", "fh.s.damage"],
  ["self.add(hp, 5)", "fh.s.add"],
  ["target.sub(mp, 10)", "fh.s.sub"],
  ["target.modify(move_speed, move_speed * 0.5, 10)", "fh.s.modify"],
  ['if target.template == "monster":', "fh.s.if"],
  ["elif …: / else:", "fh.s.else"],
];

export const FUNCTION_SIGNATURES: [string, string][] = [
  ["abs", "abs(x)"],
  ["floor", "floor(x)"],
  ["ceil", "ceil(x)"],
  ["round", "round(x)"],
  ["trunc", "trunc(x)"],
  ["sign", "sign(x)"],
  ["sqrt", "sqrt(x)"],
  ["pow", "pow(x, y)"],
  ["mod", "mod(x, y)"],
  ["min", "min(a, b, …)"],
  ["max", "max(a, b, …)"],
  ["clamp", "clamp(x, lo, hi)"],
  ["lookup", "lookup(table, key)"],
  ["count", "count(group.col, value)"],
  ["sum", "sum(group.col)"],
  ["highest", "highest(n, s, k)"],
  ["lowest", "lowest(n, s, k)"],
  ["dice", "dice(n, s)"],
];

function Rows({ rows }: { rows: [string, string][] }) {
  const { t } = useI18n();
  return (
    <dl className="sk-fh-rows">
      {rows.map(([code, key]) => (
        <div key={key}>
          <dt>
            <code>{code}</code>
          </dt>
          <dd>{t(key)}</dd>
        </div>
      ))}
    </dl>
  );
}

/** 公式写法速查：侧边抽屉，编辑时可以一直开着。 */
export function FormulaHelp({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  return (
    <aside className="sk-drawer" aria-label={t("fh.open")}>
      <div className="sk-drawer-head">
        <h3>{t("fh.open")}</h3>
        <button className="sk-link" onClick={onClose}>
          {t("fh.close")}
        </button>
      </div>
      <h4>{t("fh.basic")}</h4>
      <Rows rows={BASICS} />
      <h4>{t("fh.dice")}</h4>
      <Rows rows={DICE} />
      <p className="sk-hint">{t("fh.where")}</p>
      <h4>{t("fh.script")}</h4>
      <Rows rows={SCRIPT} />
      <p className="sk-hint">{t("script.hint")}</p>
      <h4>{t("fh.functions")}</h4>
      <Rows rows={FUNCTION_SIGNATURES.map(([name, sig]) => [sig, `fh.fn.${name}`])} />
    </aside>
  );
}
