import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import { renderMarkdown } from "../markdown";
import type { ChatTurn, ChatWorkspace, DiagnosticSchool, Level, WorkspaceSpec } from "../types";

interface Msg extends ChatTurn {
  tools?: string[];
}

interface ChatResponse {
  reply: string;
  tools_used?: string[];
  workspace?: ChatWorkspace;
}

interface Props {
  school: DiagnosticSchool | null;
  level: Level;
  // What the workspace currently shows — sent with every turn so the model's system prompt
  // describes the true screen ("don't regurgitate the screen" needs ground truth).
  wspec: WorkspaceSpec;
  // A turn's workspace mutations, server-built payloads included — App applies them.
  onWorkspace: (w: ChatWorkspace) => void;
  // The active session: its id joins traces server-side (eval-trace-system.md §2), its
  // transcript seeds this pane, and every turn is reported back up into it. App remounts
  // this component (key={sessionId}) on session switch, so state init here is per-session.
  sessionId: string | null;
  initialMessages: ChatTurn[];
  onMessages: (turns: ChatTurn[]) => void;
}

export function Chat({ school, level, wspec, onWorkspace, sessionId, initialMessages, onMessages }: Props) {
  const [msgs, setMsgs] = useState<Msg[]>(initialMessages);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const msgsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = msgsRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [msgs, busy]);

  const scoped = school ? school.school_name : "these schools";
  const chips = school
    ? [
        `Why is ${school.school_name} a concern on attendance?`,
        `Show chronic absenteeism for English learners`,
        `What are ${school.school_name}'s peers doing that it isn't?`,
      ]
    : [`Compare Long Beach ${level} schools on attendance`];

  async function ask(text: string) {
    const next: Msg[] = [...msgs, { role: "user", content: text }];
    setMsgs(next);
    setInput("");
    setBusy(true);
    const turns = (ms: Msg[]) => ms.map((m) => ({ role: m.role, content: m.content }));
    onMessages(turns(next)); // persist the question before the round trip, not after it
    try {
      const d = await api.post<ChatResponse>("/chat", {
        messages: turns(next),
        level,
        session_id: sessionId,
        school_id: school ? school.school_id : null,
        workspace: wspec,
      });
      const done: Msg[] = [...next, { role: "assistant", content: d.reply, tools: d.tools_used }];
      setMsgs(done);
      onMessages(turns(done));
      // Ordering matters on a set_school turn: the transcript above must land in the
      // CURRENT session before this forks the conversation into the new school's session.
      if (d.workspace) onWorkspace(d.workspace);
    } catch (e) {
      const detail = e instanceof ApiError ? `${e.status}` : (e as Error).message;
      const done: Msg[] = [...next, { role: "assistant", content: "Error: " + detail }];
      setMsgs(done);
      onMessages(turns(done));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="chat-hd">
        Ask Claude<span className="muted"> · grounded in the data</span>
      </div>
      <div className="msgs" ref={msgsRef}>
        {msgs.length === 0 ? (
          <div className="muted" style={{ fontSize: "13px" }}>
            Ask about {scoped} — grounded in the plans, metrics, and peer data.
          </div>
        ) : null}
        {msgs.map((m, i) =>
          m.role === "user" ? (
            <div className="m u" key={i}>
              {m.content}
            </div>
          ) : (
            // The ONLY HTML sink in the app. renderMarkdown neutralises raw HTML while
            // keeping formatting — see ../markdown.ts for why that is not paranoia: the model
            // is told to quote plan text verbatim, and plan text comes from PDFs we don't
            // author. Never swap this back to a bare marked.parse().
            <div
              className="m a md"
              key={i}
              dangerouslySetInnerHTML={{ __html: renderMarkdown(m.content) }}
            />
          ),
        )}
        {busy ? <div className="m a dots">thinking</div> : null}
      </div>
      <div className="chips">
        {chips.map((c, i) => (
          <div className="chip" key={i} onClick={() => ask(c)}>
            {c}
          </div>
        ))}
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (input.trim() && !busy) ask(input.trim());
        }}
      >
        <input
          value={input}
          placeholder={"Ask about " + scoped + "…"}
          onChange={(e) => setInput(e.target.value)}
        />
        <button disabled={busy}>Send</button>
      </form>
    </>
  );
}
