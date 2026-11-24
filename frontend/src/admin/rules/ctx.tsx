import { createContext, useContext } from "react";
import type { Schemas } from "../../api/client";

/** 规则编辑器里各处共用的：在 IDE 里打开一段公式或脚本、现在打开的是哪一段、全部校验问题。 */
export type Workbench = {
  open: (path: string) => void;
  active: string | null;
  problems: Schemas["Problem"][];
};

const Ctx = createContext<Workbench>({ open: () => {}, active: null, problems: [] });
export const WorkbenchProvider = Ctx.Provider;

export function useWorkbench(): Workbench {
  return useContext(Ctx);
}

/** 这个路径（或它下面）有没有校验问题。 */
export function hasProblem(problems: Schemas["Problem"][], path: string): boolean {
  return problems.some((p) => {
    const q = p.path ?? "";
    return q === path || q.startsWith(`${path}.`) || q.startsWith(`${path}[`);
  });
}
