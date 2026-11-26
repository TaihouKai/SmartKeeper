import { useEffect, useMemo, useRef, useState } from "react";
import { api, call, currentGame, type Schemas } from "../api/client";
import { useI18n } from "../i18n";
import { ErrorBox, formatDuration } from "../ui/components";
import { useAction, usePoll } from "../ui/hooks";
import { Markdown } from "../ui/markdown";
import { PlaceText, type PlaceTarget } from "./PlaceText";
import { filterMentions, insertMention, mentionQuery } from "./mention";
import { describeEvent, prettyMentions, type Ev } from "./events";

export interface Mentionable {
  ref: string;
  label: string;
  kind?: string; // 候选列表里的小字：我的角色、身边的人、见过的人、地点
}

type Talk = Schemas["TalkOut"];
type Msg = Schemas["ChatMessageOut"];

/** 一个会话：KP（行动、提问、反馈、系统消息）、广播、一场对话、和一名玩家的私聊。 */
export type ChannelKey = string; // "kp" | "broadcast" | "talk:<id>" | "dm:<玩家 id>"

const BROADCAST_TYPES = new Set(["broadcast", "round_opened"]);
// 对话的事件在各自的会话里；建卡审核是开局前的事，留在建卡页
const HIDDEN_TYPES = new Set(["talk_invited", "talk_accepted", "talk_declined", "talk_message", "talk_ended", "round_closed", "character_submitted", "character_approved", "character_rejected"]);

/** 一条消息（气泡）：谁说的、内容、是不是自己说的、样式。 */
type Bubble = { id: string; who: string; body: string; md?: boolean; mine: boolean; tone: "kp" | "action" | "sys" | "plain"; quote?: number };

function toneOf(cls: string): Bubble["tone"] {
  if (cls.includes("sys")) return "sys";
  if (cls.includes("feedback")) return "kp";
  if (cls.includes("action")) return "action";
  return "plain";
}

/** 已读到哪里：每一局、每个会话记一个数（事件序号、对话行数、私聊消息 id），只存在这个浏览器里。 */
function useReadMarks(): [Record<string, number>, (key: string, mark: number) => void] {
  const storageKey = `sk.read.${currentGame() ?? "current"}`;
  const [marks, setMarks] = useState<Record<string, number>>(() => {
    try {
      return JSON.parse(window.localStorage.getItem(storageKey) ?? "{}") as Record<string, number>;
    } catch {
      return {};
    }
  });
  const mark = (key: string, value: number) =>
    setMarks((m) => {
      if ((m[key] ?? -1) >= value) return m;
      const next = { ...m, [key]: value };
      try {
        window.localStorage.setItem(storageKey, JSON.stringify(next));
      } catch {
        // 存不了就只在这一页里记
      }
      return next;
    });
  return [marks, mark];
}

/** 聊天面板：左边一列会话（像 QQ），右边是这个会话的消息和它自己的输入框。 */
export function ChatPanel({
  events,
  status,
  talks,
  channel,
  setChannel,
  draft,
  setDraft,
  quotes,
  setQuotes,
  mentionables,
  onChanged,
  places,
  onPlace,
}: {
  places: { id: string; name: string }[];
  onPlace: (p: PlaceTarget) => void;
  events: Ev[];
  status: Schemas["StatusOut"] | null;
  talks: Talk[];
  channel: ChannelKey;
  setChannel: (c: ChannelKey) => void;
  draft: string;
  setDraft: (s: string) => void;
  quotes: number[];
  setQuotes: (q: number[]) => void;
  mentionables: Mentionable[];
  onChanged: () => void;
}) {
  const { t } = useI18n();
  const peers = usePoll(() => call(api.GET("/api/chat/peers")), 60_000);
  const dms = usePoll(() => call(api.GET("/api/chat", { params: { query: { since: 0 } } })), 8_000);
  const [extraDm, setExtraDm] = useState<string[]>([]);
  const [marks, mark] = useReadMarks();

  const kpEvents = events.filter((e) => !BROADCAST_TYPES.has(e.type) && !HIDDEN_TYPES.has(e.type));
  const bcEvents = events.filter((e) => BROADCAST_TYPES.has(e.type));
  const messages: Msg[] = dms.data ?? [];
  const peerName = (id: string) => peers.data?.find((p) => p.player_id === id)?.display_name ?? "?";
  const dmPeers = useMemo(() => {
    const ids = new Set<string>(extraDm);
    for (const m of messages) ids.add(m.mine ? m.recipient : m.sender);
    return [...ids];
  }, [messages, extraDm]);
  const lastSeq = (list: Ev[]) => (list.length ? list[list.length - 1]!.seq : 0);

  type Row = { key: ChannelKey; label: string; latest: number; unread: number; alert?: boolean };
  const unreadOf = (key: string, latest: number, count: (since: number) => number) => (latest > (marks[key] ?? 0) ? count(marks[key] ?? 0) : 0);
  const rows: Row[] = [
    {
      key: "kp",
      label: t("ch.kp"),
      latest: lastSeq(kpEvents),
      unread: unreadOf("kp", lastSeq(kpEvents), (since) => kpEvents.filter((e) => e.seq > since && e.actor !== "me").length),
    },
    {
      key: "broadcast",
      label: t("ch.broadcast"),
      latest: lastSeq(bcEvents),
      unread: unreadOf("broadcast", lastSeq(bcEvents), (since) => bcEvents.filter((e) => e.seq > since && e.actor !== "me").length),
    },
    ...[...talks]
      .sort((a, b) => Number(b.status === "active" || b.status === "invited") - Number(a.status === "active" || a.status === "invited"))
      .map((x) => {
        const key = `talk:${x.id}`;
        const latest = x.lines.length;
        return {
          key,
          label: t("ch.talk", { label: x.other_label }),
          latest,
          unread: unreadOf(key, latest, (since) => x.lines.slice(since).filter((l) => !l.mine).length),
          alert: x.status === "invited" && x.incoming,
        };
      }),
    ...dmPeers.map((id) => {
      const key = `dm:${id}`;
      const conv = messages.filter((m) => m.sender === id || m.recipient === id);
      const latest = conv.length ? conv[conv.length - 1]!.id : 0;
      return { key, label: t("ch.dm", { name: peerName(id) }), latest, unread: unreadOf(key, latest, (since) => conv.filter((m) => m.id > since && !m.mine).length) };
    }),
  ];
  const active = rows.find((r) => r.key === channel) ?? rows[0]!;
  // 正在看的会话：看到哪就算读到哪
  useEffect(() => {
    if (active.latest) mark(active.key, active.latest);
  }, [active.key, active.latest]); // eslint-disable-line react-hooks/exhaustive-deps

  const quote = (seq: number) => setQuotes(Array.from(new Set([...quotes, seq])));
  const bubbles: Bubble[] = (() => {
    if (active.key === "kp" || active.key === "broadcast") {
      const list = active.key === "kp" ? kpEvents : bcEvents;
      return list.map((e) => {
        const d = describeEvent(e, t);
        return { id: `e${e.seq}`, who: d.who, body: d.body, md: d.md, mine: e.actor === "me", tone: toneOf(d.cls), quote: e.type === "round_opened" ? undefined : e.seq };
      });
    }
    if (active.key.startsWith("talk:")) {
      const talk = talks.find((x) => `talk:${x.id}` === active.key);
      return (talk?.lines ?? []).map((l) => ({ id: `l${l.seq}`, who: l.mine ? t("talk.me") : `@${talk?.other_label ?? ""}`, body: l.text, mine: l.mine, tone: "plain" as const }));
    }
    const id = active.key.slice(3);
    return messages
      .filter((m) => m.sender === id || m.recipient === id)
      .map((m) => ({ id: `m${m.id}`, who: m.mine ? t("talk.me") : peerName(id), body: m.text, mine: m.mine, tone: "plain" as const }));
  })();

  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [active.key, bubbles.length]);

  const newDmPeers = (peers.data ?? []).filter((p) => !dmPeers.includes(p.player_id));
  return (
    <div className="pl-chat">
      <nav className="pl-channels" aria-label={t("ch.list")}>
        {rows.map((r) => (
          <button key={r.key} type="button" className={`${r.key === active.key ? "active" : ""}${r.alert ? " alert" : ""}`} onClick={() => setChannel(r.key)}>
            <span className="pl-ch-name">{r.label}</span>
            {r.unread > 0 && r.key !== active.key && <span className="pl-badge">{r.unread}</span>}
          </button>
        ))}
        {newDmPeers.length > 0 && (
          <select
            value=""
            aria-label={t("ch.new_dm")}
            onChange={(e) => {
              if (!e.target.value) return;
              setExtraDm([...extraDm, e.target.value]);
              setChannel(`dm:${e.target.value}`);
            }}
          >
            <option value="">{t("ch.new_dm")}</option>
            {newDmPeers.map((p) => (
              <option key={p.player_id} value={p.player_id}>
                {p.display_name}
              </option>
            ))}
          </select>
        )}
      </nav>
      <section className="pl-conv">
        <header className="pl-conv-head">
          <strong>{active.label}</strong>
          <span className="sk-hint">{t(active.key === "kp" ? "ch.kp_hint" : active.key === "broadcast" ? "ch.broadcast_hint" : active.key.startsWith("talk:") ? "ch.talk_hint" : "ch.dm_hint")}</span>
        </header>
        <div className="pl-msgs">
          {bubbles.length === 0 && <p className="sk-hint pl-empty">{t("ch.empty")}</p>}
          {bubbles.map((b) => (
            <div key={b.id} className={`pl-msg ${b.mine ? "mine" : ""} ${b.tone}`}>
              {b.tone !== "sys" && b.who && <div className="pl-who">{b.who}</div>}
              <div className="pl-bubble">{b.md ? <Markdown text={b.body} /> : <PlaceText text={b.body} places={places} onOpen={onPlace} />}</div>
              {b.quote !== undefined && !b.mine && b.tone !== "sys" && (
                <button type="button" className="sk-link pl-quote" onClick={() => quote(b.quote!)}>
                  {t("event.quote")}
                </button>
              )}
            </div>
          ))}
          <div ref={end} />
        </div>
        {active.key === "kp" && <KpComposer status={status} events={events} draft={draft} setDraft={setDraft} quotes={quotes} setQuotes={setQuotes} mentionables={mentionables} onChanged={onChanged} />}
        {active.key === "broadcast" && <BroadcastComposer onChanged={onChanged} />}
        {active.key.startsWith("talk:") && (
          <TalkComposer talk={talks.find((x) => `talk:${x.id}` === active.key)} onChanged={onChanged} />
        )}
        {active.key.startsWith("dm:") && <DmComposer peer={active.key.slice(3)} onSent={() => void dms.refresh()} />}
      </section>
    </div>
  );
}

/**
 * 输入框：Enter 发送，Shift+Enter 换行（行动用 Ctrl+Enter 解析，免得一不小心交上去）。
 * 给了 mentions 时，打 @ 弹出候选（继续打字筛选，↑↓ 选，Enter/Tab 确定，Esc 关）；
 * plain 时插入 @名字，否则插入 @[名字](引用)（行动解析用）。
 */
function Composer({
  value,
  onChange,
  onSend,
  disabled,
  placeholder,
  rows = 2,
  sendOnEnter = true,
  mentions,
  plain = false,
}: {
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  disabled?: boolean;
  placeholder?: string;
  rows?: number;
  sendOnEnter?: boolean;
  mentions?: Mentionable[];
  plain?: boolean;
}) {
  const box = useRef<HTMLTextAreaElement>(null);
  const [at, setAt] = useState<{ start: number; query: string; caret: number } | null>(null);
  const [sel, setSel] = useState(0);
  const options = at && mentions ? filterMentions(mentions, at.query) : [];
  const look = (text: string, caret: number) => {
    const q = mentions?.length ? mentionQuery(text, caret) : null;
    setAt(q ? { ...q, caret } : null);
    setSel(0);
  };
  const choose = (m: Mentionable) => {
    if (!at) return;
    const r = insertMention(value, at.start, at.caret, plain ? `@${m.label}` : `@[${m.label}](${m.ref})`);
    onChange(r.text);
    setAt(null);
    requestAnimationFrame(() => {
      box.current?.focus();
      box.current?.setSelectionRange(r.caret, r.caret);
    });
  };
  return (
    <div className="pl-input">
      <textarea
        ref={box}
        rows={rows}
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(e) => {
          onChange(e.target.value);
          look(e.target.value, e.target.selectionStart);
        }}
        onClick={(e) => look(value, e.currentTarget.selectionStart)}
        onBlur={() => setTimeout(() => setAt(null), 150)}
        onKeyDown={(e) => {
          if (options.length > 0) {
            if (e.key === "ArrowDown" || e.key === "ArrowUp") {
              e.preventDefault();
              setSel((sel + (e.key === "ArrowDown" ? 1 : options.length - 1)) % options.length);
              return;
            }
            if ((e.key === "Enter" || e.key === "Tab") && !e.ctrlKey && !e.metaKey) {
              e.preventDefault();
              choose(options[sel] ?? options[0]!);
              return;
            }
            if (e.key === "Escape") {
              e.preventDefault();
              setAt(null);
              return;
            }
          }
          if (e.key !== "Enter" || !value.trim()) return;
          if ((sendOnEnter && !e.shiftKey) || e.ctrlKey || e.metaKey) {
            e.preventDefault();
            onSend();
          }
        }}
      />
      {options.length > 0 && (
        <ul className="pl-at" role="listbox">
          {options.map((m, i) => (
            <li key={`${m.ref}|${m.label}`} role="option" aria-selected={i === sel}>
              <button
                type="button"
                className={i === sel ? "active" : ""}
                onMouseDown={(e) => {
                  e.preventDefault(); // 不让输入框先失去焦点
                  choose(m);
                }}
              >
                @{m.label}
                {m.kind && <span className="sk-hint"> · {m.kind}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** KP 会话的输入框：“行动”（声明本轮行动，解析确认后提交）和“提问”（向 KP 问规则、问情况）切换。 */
function KpComposer({
  status,
  events,
  draft,
  setDraft,
  quotes,
  setQuotes,
  mentionables,
  onChanged,
}: {
  status: Schemas["StatusOut"] | null;
  events: Ev[];
  draft: string;
  setDraft: (s: string) => void;
  quotes: number[];
  setQuotes: (q: number[]) => void;
  mentionables: Mentionable[];
  onChanged: () => void;
}) {
  const { t } = useI18n();
  const collecting = status?.game_status === "running" && (status.me === "act" || status.me === "submitted");
  const busy = status?.game_status === "running" && status.me === "busy";
  const [mode, setMode] = useState<"act" | "ask">("act");
  const [echo, setEcho] = useState<Schemas["ActionEcho"] | null>(null);
  const [question, setQuestion] = useState("");
  const parse = useAction();
  const confirm = useAction();
  const ask = useAction();
  const myDecl = [...events].reverse().find((e) => e.type === "action_declared");
  const doParse = () =>
    void parse.run(async () => {
      setEcho(await call(api.POST("/api/action/parse", { body: { text: draft } })));
    });
  const doConfirm = () =>
    void confirm.run(async () => {
      if (!echo) return;
      await call(api.POST("/api/action", { body: { parse_id: echo.parse_id, quotes } }));
      setEcho(null);
      setDraft("");
      setQuotes([]);
      onChanged();
    });
  const doAsk = () =>
    void ask.run(async () => {
      await call(api.POST("/api/kp/chat", { body: { text: question } }));
      setQuestion("");
      onChanged();
    });
  return (
    <div className="pl-composer">
      <div className="pl-modes" role="tablist">
        <button type="button" role="tab" aria-selected={mode === "act"} className={mode === "act" ? "active" : ""} title={t("kp.action_hint")} onClick={() => setMode("act")}>
          {t("kp.mode_act")}
        </button>
        <button type="button" role="tab" aria-selected={mode === "ask"} className={mode === "ask" ? "active" : ""} title={t("kp.chat_hint")} onClick={() => setMode("ask")}>
          {t("kp.mode_ask")}
        </button>
      </div>
      {mode === "act" ? (
        <>
          {busy && <p className="pl-note">{t("kp.busy")}</p>}
          {status?.me === "submitted" && myDecl && (
            <p className="pl-note">
              {t("kp.submitted_already")} {prettyMentions(String(myDecl.payload.text ?? ""))}
            </p>
          )}
          {echo && (
            <div className="sk-echo pl-echo">
              <strong>{t("kp.understood_as")}</strong>
              <ul>
                {echo.items.map((it, i) => (
                  <li key={i}>
                    <b>{it.actor_label}</b> · {it.verb}
                    {it.targets.length > 0 && <> → {it.targets.map((x) => (x.kind === "entity" ? `@${x.label}` : x.label || t("kp.a_point"))).join(", ")}</>}
                    {it.destination_label && <> ⇒ {it.destination_label}</>}
                    <div className="sk-hint">{t("kp.item_time", { move: formatDuration(t, it.move_seconds), act: formatDuration(t, it.act_seconds) })}</div>
                    {it.detail && <div className="sk-hint">{prettyMentions(it.detail)}</div>}
                  </li>
                ))}
              </ul>
              <p>
                <strong>{t("kp.estimate", { total: formatDuration(t, echo.total_seconds) })}</strong> <span className="sk-hint">{t("kp.confirm_hint")}</span>
              </p>
              {echo.unresolved.length > 0 && (
                <div className="sk-warn">
                  {t("kp.unresolved")} {echo.unresolved.join(", ")}
                </div>
              )}
              <div className="sk-row">
                <button className="sk-primary" disabled={confirm.busy || echo.unresolved.length > 0 || echo.items.length === 0} onClick={doConfirm}>
                  {t("kp.confirm")}
                </button>
                <button onClick={() => setEcho(null)}>{t("kp.edit")}</button>
              </div>
              <ErrorBox error={confirm.error} />
            </div>
          )}
          <Composer
            rows={3}
            value={draft}
            disabled={!collecting}
            sendOnEnter={false}
            mentions={mentionables}
            placeholder={t("kp.action_placeholder")}
            onChange={(v) => {
              setDraft(v);
              setEcho(null);
            }}
            onSend={doParse}
          />
          <div className="sk-row pl-tools">
            <select
              value=""
              disabled={!collecting}
              onChange={(e) => {
                const m = mentionables.find((x) => x.ref === e.target.value);
                if (m) setDraft(`${draft}@[${m.label}](${m.ref}) `);
              }}
            >
              <option value="">{t("kp.insert_mention")}</option>
              {mentionables.map((m) => (
                <option key={`${m.ref}|${m.label}`} value={m.ref}>
                  @{m.label}
                </option>
              ))}
            </select>
            {quotes.map((q) => (
              <button key={q} className="sk-chip" onClick={() => setQuotes(quotes.filter((x) => x !== q))}>
                {t("kp.quote_chip", { seq: String(q) })} ×
              </button>
            ))}
            <button className="sk-primary pl-send" disabled={!collecting || !draft.trim() || parse.busy} onClick={doParse}>
              {parse.busy ? t("common.working") : t("kp.parse")}
            </button>
          </div>
          <ErrorBox error={parse.error} />
        </>
      ) : (
        <>
          <Composer value={question} onChange={setQuestion} onSend={doAsk} placeholder={t("kp.ask_placeholder")} mentions={mentionables} plain />
          <div className="sk-row pl-tools">
            <button className="sk-primary pl-send" disabled={!question.trim() || ask.busy} onClick={doAsk}>
              {t("kp.ask")}
            </button>
          </div>
          <ErrorBox error={ask.error} />
        </>
      )}
    </div>
  );
}

function BroadcastComposer({ onChanged }: { onChanged: () => void }) {
  const { t } = useI18n();
  const [text, setText] = useState("");
  const [anon, setAnon] = useState(false);
  const act = useAction();
  const send = () =>
    void act.run(async () => {
      await call(api.POST("/api/broadcast", { body: { text, anonymous: anon } }));
      setText("");
      onChanged();
    });
  return (
    <div className="pl-composer">
      <Composer value={text} onChange={setText} onSend={send} placeholder={t("broadcast.hint")} />
      <div className="sk-row pl-tools">
        <label className="sk-inline">
          <input type="checkbox" checked={anon} onChange={(e) => setAnon(e.target.checked)} /> {t("broadcast.anonymous")}
        </label>
        <button className="sk-primary pl-send" disabled={!text.trim() || act.busy} onClick={send}>
          {t("broadcast.send")}
        </button>
      </div>
      <ErrorBox error={act.error} />
    </div>
  );
}

/** 一场对话的输入框：对方邀请我时先接受或拒绝；进行中可以说话、结束；结束了只能看。 */
function TalkComposer({ talk, onChanged }: { talk: Talk | undefined; onChanged: () => void }) {
  const { t } = useI18n();
  const [text, setText] = useState("");
  const act = useAction();
  if (!talk) return null;
  const id = talk.id;
  const post = (path: "answer" | "say" | "end", body?: { accept: boolean }) =>
    void act.run(async () => {
      if (path === "answer" && body) await call(api.POST("/api/talks/{talk_id}/answer", { params: { path: { talk_id: id } }, body }));
      if (path === "say") await call(api.POST("/api/talks/{talk_id}/say", { params: { path: { talk_id: id } }, body: { text } }));
      if (path === "end") await call(api.POST("/api/talks/{talk_id}/end", { params: { path: { talk_id: id } } }));
      if (path === "say") setText("");
      onChanged();
    });
  return (
    <div className="pl-composer">
      {talk.status === "invited" && talk.incoming && (
        <div className="pl-note">
          {t("talk.invited_me", { label: talk.other_label })}{" "}
          <button className="sk-primary" disabled={act.busy} onClick={() => post("answer", { accept: true })}>
            {t("talk.accept")}
          </button>{" "}
          <button disabled={act.busy} onClick={() => post("answer", { accept: false })}>
            {t("talk.decline")}
          </button>
        </div>
      )}
      {talk.status === "invited" && !talk.incoming && (
        <p className="pl-note">
          {t("talk.waiting")}{" "}
          <button className="sk-link" onClick={() => post("end")}>
            {t("talk.cancel")}
          </button>
        </p>
      )}
      {talk.status === "active" && (
        <>
          <Composer value={text} onChange={setText} onSend={() => post("say")} placeholder={t("talk.placeholder")} />
          <div className="sk-row pl-tools">
            <button disabled={act.busy} onClick={() => post("end")}>
              {t("talk.end")}
            </button>
            <button className="sk-primary pl-send" disabled={!text.trim() || act.busy} onClick={() => post("say")}>
              {t("talk.send")}
            </button>
          </div>
        </>
      )}
      {talk.status === "declined" && <p className="pl-note">{t("talk.declined")}</p>}
      {talk.status === "ended" && <p className="pl-note">{t("talk.ended")}</p>}
      <ErrorBox error={act.error} />
    </div>
  );
}

function DmComposer({ peer, onSent }: { peer: string; onSent: () => void }) {
  const { t } = useI18n();
  const [text, setText] = useState("");
  const act = useAction();
  const send = () =>
    void act.run(async () => {
      await call(api.POST("/api/chat", { body: { to: peer, text } }));
      setText("");
      onSent();
    });
  return (
    <div className="pl-composer">
      <Composer value={text} onChange={setText} onSend={send} placeholder={t("chat.hint")} />
      <div className="sk-row pl-tools">
        <button className="sk-primary pl-send" disabled={!text.trim() || act.busy} onClick={send}>
          {t("chat.send")}
        </button>
      </div>
      <ErrorBox error={act.error} />
    </div>
  );
}
