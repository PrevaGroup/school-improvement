// Sessions — the client-side "line of inquiry" store (design doc § Sessions).
//
// A session pins ONE school and carries everything the user was looking at: the workspace
// SPEC (never cached chart data — payloads go stale and the screen must only ever show
// numbers the server just built; restore refetches via POST /marts/workspace) and the chat
// transcript (reply text only, never tool payloads).
//
// Deliberately localStorage, not a server table: the backend stays stateless and
// public-data-only, which is what lets chat.py skip tenancy entirely. Accounts/cross-device
// sync would drag auth/RLS into `serving` — that's a go-live decision, not a default.
//
// Pure helpers are exported for tests; localStorage touches live in load/save only.

import type { ChatTurn, Level, WorkspaceSpec } from "./types";
import { DEFAULT_WORKSPACE_SPEC } from "./workspace";

export interface Session {
  v: 1; // schema version — unparseable/foreign versions are dropped on load
  id: string; // uuid; sent as session_id on every /chat call (trace continuity, §2)
  school_id: string; // pinned — switching school activates/creates a session, never mutates
  school_name: string; // denormalized for rail display without a fetch
  district_id: string;
  level: Level;
  title: string; // "<school> — <first question>" once the first message lands
  custom_title?: boolean; // true once Claude (rename_session) or a future UI set it — titleFor stops overwriting
  created_at: number;
  updated_at: number; // rail sort key
  workspace: WorkspaceSpec;
  messages: ChatTurn[];
}

export interface SessionStore {
  v: 1;
  active_id: string | null;
  sessions: Session[];
}

const KEY = "si.sessions.v1";
export const MAX_SESSIONS = 20;

function uuid(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `sess-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
}

export function createSession(school: {
  school_id: string;
  school_name: string;
  district_id: string;
  level: Level;
}): Session {
  const now = Date.now();
  return {
    v: 1,
    id: uuid(),
    school_id: school.school_id,
    school_name: school.school_name,
    district_id: school.district_id,
    level: school.level,
    title: school.school_name, // refined by titleFor() on the first user message
    created_at: now,
    updated_at: now,
    // Deep copy — a session must own its spec (chat mutations patch slots in place).
    workspace: JSON.parse(JSON.stringify(DEFAULT_WORKSPACE_SPEC)) as WorkspaceSpec,
    messages: [],
  };
}

// "Let's look at Jordan" mid-conversation FORKS (design § Sessions): the transcript copies
// forward so the user experiences one continuous conversation, the workspace resets to the
// defaults, and the rail keeps two honest snapshots of "what was I looking at".
export function forkSession(from: Session | null, school: {
  school_id: string;
  school_name: string;
  district_id: string;
  level: Level;
}): Session {
  const s = createSession(school);
  if (from) s.messages = from.messages.slice();
  return s;
}

export function titleFor(session: Session): string {
  const q = session.messages.find((m) => m.role === "user")?.content?.trim();
  if (!q) return session.school_name;
  return `${session.school_name} — ${q.length > 60 ? q.slice(0, 57) + "…" : q}`;
}

// The most recent session for a school — what the header picker activates (else it creates).
export function latestForSchool(sessions: Session[], school_id: string): Session | null {
  let best: Session | null = null;
  for (const s of sessions) {
    if (s.school_id === school_id && (!best || s.updated_at > best.updated_at)) best = s;
  }
  return best;
}

export function byRecency(sessions: Session[]): Session[] {
  return sessions.slice().sort((a, b) => b.updated_at - a.updated_at);
}

// Immutable update + prune. Keeps the store bounded: MAX_SESSIONS by updated_at, but the
// active session is never pruned (it would orphan the screen).
export function upsert(sessions: Session[], next: Session, activeId: string | null): Session[] {
  const rest = sessions.filter((s) => s.id !== next.id);
  const all = byRecency([...rest, next]);
  if (all.length <= MAX_SESSIONS) return all;
  const keep = all.slice(0, MAX_SESSIONS);
  const dropped = all.slice(MAX_SESSIONS).filter((s) => s.id === activeId);
  return dropped.length ? [...keep, ...dropped] : keep;
}

// Rail timestamp: coarse on purpose — "which of these is recent" is the question it answers.
export function relTime(ts: number, now: number = Date.now()): string {
  const s = Math.max(0, Math.round((now - ts) / 1000));
  if (s < 60) return "now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h`;
  return `${Math.round(h / 24)}d`;
}

// ---- storage (the only impure part) ----------------------------------------------------- //

export function loadStore(): SessionStore {
  const empty: SessionStore = { v: 1, active_id: null, sessions: [] };
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return empty;
    const parsed = JSON.parse(raw) as SessionStore;
    if (parsed?.v !== 1 || !Array.isArray(parsed.sessions)) return empty;
    // Drop anything malformed rather than let one bad session brick the app.
    const sessions = parsed.sessions.filter(
      (s) => s && s.v === 1 && typeof s.id === "string" && typeof s.school_id === "string"
        && s.workspace && Array.isArray(s.workspace.slots) && Array.isArray(s.messages),
    );
    const active_id = sessions.some((s) => s.id === parsed.active_id) ? parsed.active_id : null;
    return { v: 1, active_id, sessions };
  } catch {
    return empty; // corrupted storage = start fresh, never crash the app over history
  }
}

let saveTimer: ReturnType<typeof setTimeout> | null = null;

export function saveStore(store: SessionStore): void {
  // Debounced — chat turns and slot changes can land in bursts.
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    try {
      localStorage.setItem(KEY, JSON.stringify(store));
    } catch {
      // Quota/private-mode failures lose persistence, not the session in memory.
    }
  }, 250);
}
