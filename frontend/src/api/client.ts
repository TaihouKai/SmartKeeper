import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

/** 同源请求，带上 cookie（玩家 token 和控制台会话都在 HttpOnly cookie 里）。 */
export const api = createClient<paths>({ baseUrl: "", credentials: "same-origin" });

/** 这一页是哪一局的：每一局自己的网址 /g/<局 id>，或者在新标签页打开的规则书、剧本（?game=局 id）。 */
export function currentGame(): string | null {
  const m = /^\/g\/([^/?#]+)/.exec(window.location.pathname);
  if (m) return decodeURIComponent(m[1]!);
  return new URLSearchParams(window.location.search).get("game");
}

/** 某一局自己的网址；规则书、剧本页面带上 ?game= 才知道是哪一局。 */
export function gamePath(gameId: string): string {
  return `/g/${encodeURIComponent(gameId)}`;
}

/** 规则书、剧本这类页面的地址：在某一局的页面里打开时带上是哪一局。 */
export function withGame(path: string): string {
  const game = currentGame();
  return game ? `${path}?game=${encodeURIComponent(game)}` : path;
}

// 玩家接口按局取座位：一个浏览器开着几局的页面也互不干扰（服务器从这个浏览器的座位里找那一局的）
api.use({
  onRequest({ request }) {
    const game = currentGame();
    if (game) request.headers.set("X-SK-Game", game);
    return request;
  },
});

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
