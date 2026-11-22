import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

/** 同源请求，带上 cookie（玩家 token 和控制台会话都在 HttpOnly cookie 里）。 */
export const api = createClient<paths>({ baseUrl: "", credentials: "same-origin" });

export interface ApiErrorBody {
  code: string;
  params?: Record<string, unknown>;
  problems?: { code: string; path?: string; params?: Record<string, unknown> }[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: ApiErrorBody,
  ) {
    super(body.code);
  }
}

/** 解开 openapi-fetch 的结果：成功返回 data，失败抛 ApiError（带消息代码）。 */
export async function call<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await p;
  if (response.ok) return data as T;
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  let body: ApiErrorBody;
  if (detail && typeof detail === "object" && !Array.isArray(detail) && "code" in detail) {
    body = detail as ApiErrorBody;
  } else if (Array.isArray(detail)) {
    body = { code: "request.invalid", problems: detail.map((d: { loc?: unknown[]; type?: string }) => ({ code: String(d.type ?? "invalid"), path: (d.loc ?? []).join(".") })) };
  } else {
    body = { code: `http.${response.status}` };
  }
  throw new ApiError(response.status, body);
}
