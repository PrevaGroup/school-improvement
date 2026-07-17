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

// `defaultSpec` is the LEVEL-AWARE seed (App resolves it from the server-fetched defaults for
// school.level; falls back to the HS default). A session owns its spec, so it's deep-copied.
export function createSession(
  school: { school_id: string; school_name: string; district_id: string; level: Level },
  defaultSpec: WorkspaceSpec = DEFAULT_WORKSPACE_SPEC,
): Session {
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
    workspace: JSON.parse(JSON.stringify(defaultSpec)) as WorkspaceSpec,
    messages: [],
  };
}

// "Let's look at Jordan" mid-conversation FORKS (design § Sessions): the transcript copies
// forward so the user experiences one continuous conversation, the workspace resets to the
// (level-aware) defaults, and the rail keeps two honest snapshots of "what was I looking at".
export function forkSession(
  from: Session | null,
  school: { school_id: string; school_name: string; district_id: string; level: Level },
  defaultSpec: WorkspaceSpec = DEFAULT_WORKSPACE_SPEC,
): Session {
  const s = createSession(school, defaultSpec);
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

// DETERMINISTIC order: updated_at desc, then created_at, then id. The extra tie-breaks matter
// — Date.now() can repeat within a millisecond, and an unstable sort makes the rail visibly
// jitter (and reorder) between renders. Selecting a session must NOT reorder the rail (that's
// what read as a double-highlight); only real activity (a chat turn, a workspace change) bumps
// updated_at, so browsing sessions leaves the order put.
export function byRecency(sessions: Session[]): Session[] {
  return sessions
    .slice()
    .sort((a, b) => b.updated_at - a.updated_at || b.created_at - a.created_at || (a.id < b.id ? 1 : -1));
}

// Belt-and-braces against duplicate ids left in localStorage by earlier builds — two entries
// with the same id would both match `activeId` and both highlight. Keeps the first occurrence.
export function dedupeById(sessions: Session[]): Session[] {
  const seen = new Set<string>();
  return sessions.filter((s) => (seen.has(s.id) ? false : (seen.add(s.id), true)));
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

// A scratch session: never chatted in, so nothing is lost by repointing it at another school.
// (Workspace changes only ever arrive via chat, so no-messages == untouched.)
export function isEmptySession(s: Session): boolean {
  return s.messages.length === 0;
}

export interface SessionMeta {
  school_id: string;
  school_name: string;
  district_id: string;
  level: Level;
}

// Decide the session list + active id when the selected school changes. PURE so the timing-
// sensitive App effect stays a thin apply. The rules that fix the "sessions get confused" bugs:
//  - fork (a chat set_school) → a new session with the transcript copied forward (unchanged).
//  - an EXISTING session for the target school → adopt it; and if we're leaving an empty
//    scratch session behind, drop it (don't accumulate orphans).
//  - no session for the target, but the active one is an empty scratch → REPOINT it in place
//    (same id, reset to the default workspace) instead of spawning a second session.
//  - otherwise (active has a real conversation, no target session) → create a fresh session,
//    keeping the conversation intact.
export function reconcileSchoolChange(
  sessions: Session[],
  activeId: string | null,
  target: SessionMeta,
  fork: Session | null = null,
  defaultSpec: WorkspaceSpec = DEFAULT_WORKSPACE_SPEC,
): { sessions: Session[]; activeId: string; spec: WorkspaceSpec } {
  const act = sessions.find((s) => s.id === activeId) ?? null;
  if (!fork && act && act.school_id === target.school_id) {
    return { sessions, activeId: act.id, spec: act.workspace }; // already on this school
  }
  if (fork) {
    const next = forkSession(fork, target, defaultSpec);
    return { sessions: upsert(sessions, next, next.id), activeId: next.id, spec: next.workspace };
  }
  const existing = latestForSchool(sessions, target.school_id);
  if (existing) {
    // Adopt WITHOUT bumping updated_at — switching to a school you've looked at before is a
    // view, not activity, so it must not reorder the rail.
    let next = sessions;
    if (act && act.id !== existing.id && isEmptySession(act)) {
      next = next.filter((s) => s.id !== act.id); // discard the empty scratch we're leaving
    }
    return { sessions: next, activeId: existing.id, spec: existing.workspace };
  }
  if (act && isEmptySession(act)) {
    const repointed: Session = {
      ...act,
      school_id: target.school_id,
      school_name: target.school_name,
      district_id: target.district_id,
      level: target.level,
      title: target.school_name,
      custom_title: false,
      workspace: JSON.parse(JSON.stringify(defaultSpec)) as WorkspaceSpec,
      updated_at: Date.now(),
    };
    return { sessions: upsert(sessions, repointed, repointed.id), activeId: repointed.id, spec: repointed.workspace };
  }
  const created = createSession(target, defaultSpec);
  return { sessions: upsert(sessions, created, created.id), activeId: created.id, spec: created.workspace };
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
    // Drop anything malformed rather than let one bad session brick the app, and dedupe by id
    // (earlier builds could leave duplicates, which show as two highlighted rail rows).
    const sessions = dedupeById(
      parsed.sessions.filter(
        (s) => s && s.v === 1 && typeof s.id === "string" && typeof s.school_id === "string"
          && s.workspace && Array.isArray(s.workspace.slots) && Array.isArray(s.messages),
      ),
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
