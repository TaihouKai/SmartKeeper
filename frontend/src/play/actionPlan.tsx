import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { Schemas } from "../api/client";

/** 自己的一个角色。 */
export type OwnChar = { ref: string; name: string };

/** 自己角色能用的一个技能或动作（行动栏里的一格）。 */
export type Skill = Schemas["SkillView"] & { owner: string };

/** 地图上的一个地方：发给服务器的写法和给人看的名字。 */
export type Spot = { to: Schemas["SpotIn"]; label: string };

/** 本回合行动列表里的一条：谁去哪（谁和他一起走）、谁用什么技能对谁。 */
export type Planned = {
  key: string;
  actor: string;
  to?: Spot;
  companions: string[];
  entry?: string;
  target?: { ref: string; label: string };
  params: Record<string, number>;
};

type Ctx = {
  own: OwnChar[];
  skills: Skill[];
  plan: Planned[];
  actor: string;
  setActor: (ref: string) => void;
  /** 正在设置对象和参数的技能（行动栏或角色卡上点了“使用”） */
  configuring: Skill | null;
  setConfiguring: (s: Skill | null) => void;
  add: (p: Omit<Planned, "key">) => void;
  update: (key: string, p: Partial<Planned>) => void;
  remove: (key: string) => void;
  clear: () => void;
};

const PlanContext = createContext<Ctx | null>(null);

/** 本回合行动列表的状态（放在游戏页上：地图上设目的地、角色卡上点“使用”也往里加）。 */
export function usePlanState(own: OwnChar[], skills: Skill[]): Ctx {
  const [plan, setPlan] = useState<Planned[]>([]);
  const [chosen, setActor] = useState("");
  const [configuring, setConfiguring] = useState<Skill | null>(null);
  const actor = own.some((o) => o.ref === chosen) ? chosen : (own[0]?.ref ?? "");
  const add = useCallback((p: Omit<Planned, "key">) => setPlan((xs) => [...xs, { ...p, key: `${Date.now()}-${Math.random()}` }]), []);
  const update = useCallback((key: string, p: Partial<Planned>) => setPlan((xs) => xs.map((x) => (x.key === key ? { ...x, ...p } : x))), []);
  const remove = useCallback((key: string) => setPlan((xs) => xs.filter((x) => x.key !== key)), []);
  const clear = useCallback(() => setPlan([]), []);
  return useMemo(
    () => ({ own, skills, plan, actor, setActor, configuring, setConfiguring, add, update, remove, clear }),
    [own, skills, plan, actor, configuring, add, update, remove, clear],
  );
}

export function ActionPlanProvider({ value, children }: { value: Ctx; children: ReactNode }) {
  return <PlanContext.Provider value={value}>{children}</PlanContext.Provider>;
}

export function useActionPlan(): Ctx {
  const c = useContext(PlanContext);
  if (!c) throw new Error("useActionPlan outside ActionPlanProvider");
  return c;
}

/** “名字=值”的可选值：显示的名字和数值。 */
export function choiceParts(choice: string): { label: string; value: number } {
  const i = choice.lastIndexOf("=");
  if (i < 0) return { label: choice, value: Number(choice) || 0 };
  return { label: choice.slice(0, i), value: Number(choice.slice(i + 1)) || 0 };
}

/** 发给服务器的写法。 */
export function toCompose(p: Planned): Schemas["ComposeItemIn"] {
  return {
    actor: p.actor,
    to: p.to?.to ?? null,
    companions: p.companions,
    entry: p.entry ?? null,
    target: p.target ? { ref: p.target.ref } : null,
    params: p.params,
  };
}

/** 一条行动写成一句话（给玩家看，也记进“我的行动”）。 */
export function describePlanned(p: Planned, own: OwnChar[], skills: Skill[], t: (k: string, v?: Record<string, string>) => string): string {
  const name = (ref: string) => own.find((o) => o.ref === ref)?.name ?? "?";
  const who = p.companions.length ? t("plan.together", { who: name(p.actor), with: p.companions.map(name).join(t("intel.list_sep")) }) : name(p.actor);
  const parts: string[] = [];
  if (p.to) parts.push(t("plan.move", { who, where: p.to.label }));
  if (p.entry) {
    const sk = skills.find((s) => s.entity_id === p.actor && s.name === p.entry);
    const chosen = Object.entries(p.params)
      .map(([k, v]) => {
        const def = sk?.params.find((x) => x.name === k);
        const named = def?.choices.map(choiceParts).find((c) => c.value === v);
        return `${def?.label || k} ${named ? named.label : String(v)}`;
      })
      .join(t("intel.list_sep"));
    const base = p.target ? t("plan.use_on", { who: name(p.actor), skill: p.entry, target: p.target.label }) : t("plan.use", { who: name(p.actor), skill: p.entry });
    parts.push(chosen ? t("plan.with_params", { action: base, params: chosen }) : base);
  }
  return parts.join(t("intel.list_sep"));
}
