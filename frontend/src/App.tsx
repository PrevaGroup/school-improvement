import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { fmtNum, fmtPct } from "./format";
import { Chat } from "./components/Chat";
import { Diagnostic } from "./components/Diagnostic";
import { DEFAULT_WORKSPACE_SPEC, applyChatWorkspace } from "./workspace";
import {
  byRecency, createSession, forkSession, loadStore, reconcileSchoolChange, relTime, saveStore,
  titleFor, upsert,
} from "./sessions";
import type { Session } from "./sessions";
import type {
  ChatTurn, ChatWorkspace, District, DiagnosticSchool, Level, Peer, WorkspaceData, WorkspaceSpec,
} from "./types";

const DEMO_DISTRICT = "0622500"; // Long Beach Unified (NCES LEAID) — the demo default
const LEVELS: Level[] = ["High", "Middle", "Primary"];

// Loaded once at import: the persisted sessions seed the initial picker/workspace state,
// so a returning user opens on what they were last looking at.
const BOOT = loadStore();
const BOOT_ACTIVE = BOOT.sessions.find((s) => s.id === BOOT.active_id) ?? null;

// Header stat. `null` renders as an em dash, never 0 — a missing demographic is unknown, not zero.
function Feat({ v, kind, lab }: { v: number | string | null; kind: "pct" | "num" | "str"; lab: string }) {
  const shown = v == null ? "—" : kind === "pct" ? fmtPct(v as number) : kind === "num" ? fmtNum(v as number) : v;
  return (
    <div>
      <b>{shown}</b> <span>{lab}</span>
    </div>
  );
}

type LoadState = "loading" | "ready" | "error";

// The selected school carries its own header demographics, alongside the diagnostic fields.
interface SchoolRow extends DiagnosticSchool {
  enroll_total: number | null;
  pct_sed: number | null;
  pct_el: number | null;
  pct_swd: number | null;
  locale: string | null;
}

export default function App() {
  const [level, setLevel] = useState<Level>(BOOT_ACTIVE?.level ?? "High");
  const [districtId, setDistrictId] = useState(BOOT_ACTIVE?.district_id ?? DEMO_DISTRICT);
  const [districts, setDistricts] = useState<District[]>([]);
  const [schools, setSchools] = useState<SchoolRow[]>([]);
  const [sel, setSel] = useState<SchoolRow | null>(null);
  const [peers, setPeers] = useState<Peer[] | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");

  // Sessions: a session pins ONE school + the workspace spec + the transcript. The ACTIVE
  // session is the source of truth the rest of this state is a view of (design § Sessions).
  const [sessions, setSessions] = useState<Session[]>(BOOT.sessions);
  const [activeId, setActiveId] = useState<string | null>(BOOT.active_id);

  // The Claude-controlled workspace: `wspec` is what should be on screen (the active
  // session's spec), `ws` is the server-built data for it.
  const [wspec, setWspec] = useState<WorkspaceSpec>(BOOT_ACTIVE?.workspace ?? DEFAULT_WORKSPACE_SPEC);
  const [ws, setWs] = useState<WorkspaceData | null>(null);

  // Refs read by effects/handlers without re-triggering them. `wspecRef` is also written
  // DIRECTLY on session adoption so the sibling fetch effect (same commit) sees the adopted
  // spec, not last render's.
  const wspecRef = useRef(wspec);
  wspecRef.current = wspec;
  const sessionsRef = useRef(sessions);
  sessionsRef.current = sessions;
  const activeRef = useRef(activeId);
  activeRef.current = activeId;
  // A school switch that needs a roster (district/level) reload first parks its target here.
  const pendingSelRef = useRef<string | null>(BOOT_ACTIVE?.school_id ?? null);
  // A chat set_school forks the conversation into the new school's session (transcript
  // copies forward, workspace resets). Set before the selection changes; consumed once.
  const forkFromRef = useRef<Session | null>(null);

  const activeSession = useMemo(
    () => sessions.find((s) => s.id === activeId) ?? null,
    [sessions, activeId],
  );

  // Persist on every mutation (saveStore debounces).
  useEffect(() => {
    saveStore({ v: 1, active_id: activeId, sessions });
  }, [sessions, activeId]);

  useEffect(() => {
    api
      .get<{ districts: District[] }>("/marts/districts")
      .then((d) => setDistricts(d.districts || []))
      .catch(() => {});
  }, []);

  // Every selection resolves to a scoped backend query — no "fetch everything, filter
  // client-side". See ../CLAUDE.md: the browser never receives data outside the current scope.
  useEffect(() => {
    setSchools([]);
    setSel(null);
    setLoadState("loading");
    api
      .get<{ schools: SchoolRow[] }>(
        `/marts/attendance-diagnostic?district_id=${districtId}&level=${level}`,
      )
      .then((d) => {
        const rows = d.schools || [];
        setSchools(rows);
        // A session activation / chat set_school that crossed rosters parked its target here.
        const pending = pendingSelRef.current;
        pendingSelRef.current = null;
        setSel((pending && rows.find((s) => s.school_id === pending)) || rows[0] || null);
        setLoadState("ready");
      })
      .catch(() => setLoadState("error"));
  }, [level, districtId]);

  const current = useMemo(
    () => schools.find((s) => sel && s.school_id === sel.school_id) || sel,
    [schools, sel],
  );
  const currentId = current?.school_id;

  // Reconcile the active session with the selected school. Runs BEFORE the fetch effect
  // below (definition order), so an adopted spec is what gets fetched. The decision (adopt /
  // repoint-empty / create / fork, and dropping orphaned empty scratch sessions) lives in the
  // pure reconcileSchoolChange — see sessions.ts for the rules.
  useEffect(() => {
    if (!current) return;
    const cur = sessionsRef.current;
    const act = cur.find((s) => s.id === activeRef.current) ?? null;
    if (act && act.school_id === current.school_id) return;
    const fork = forkFromRef.current;
    forkFromRef.current = null;
    const r = reconcileSchoolChange(cur, activeRef.current, {
      school_id: current.school_id, school_name: current.school_name,
      district_id: districtId, level,
    }, fork);
    setSessions(r.sessions);
    sessionsRef.current = r.sessions;
    setActiveId(r.activeId);
    activeRef.current = r.activeId;
    setWspec(r.spec);
    wspecRef.current = r.spec; // sibling fetch effect runs in this same commit
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId]);

  function fetchWorkspace(schoolId: string, spec: WorkspaceSpec) {
    setWs(null);
    // One call restores every panel for the spec (charts + spotlight + plan).
    api
      .post<WorkspaceData>("/marts/workspace", { school_id: schoolId, spec })
      .then(setWs)
      .catch(() => setWs(null));
  }

  useEffect(() => {
    if (!currentId) {
      setPeers(null);
      setWs(null);
      return;
    }
    setPeers(null);
    api
      .get<{ peers: Peer[] }>(`/marts/like-schools?school_id=${currentId}&k=50`)
      .then((d) => setPeers(d.peers || []))
      .catch(() => setPeers([]));
    // Keyed on the school only: chat slot changes arrive WITH their payloads
    // (applyChatWorkspace), so a spec change alone never costs a refetch.
    fetchWorkspace(currentId, wspecRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId]);

  // The active session's spec follows wspec (chat mutations, adoption). Same-reference
  // specs (just adopted) short-circuit, so adoption doesn't echo a write.
  useEffect(() => {
    const id = activeRef.current;
    if (!id) return;
    setSessions((prev) => {
      const s = prev.find((x) => x.id === id);
      if (!s || s.workspace === wspec) return prev;
      return upsert(prev, { ...s, workspace: wspec, updated_at: Date.now() }, id);
    });
  }, [wspec]);

  // Chat transcript lands in the session the TURN belongs to — `sid` from the Chat that ran
  // it, NOT whatever is active now. This is what stops an answer arriving after the user has
  // switched sessions from landing in the wrong one. (title refines off the first question,
  // unless Claude renamed it — a custom title is never clobbered by the derivation.)
  function onMessages(sid: string | null, turns: ChatTurn[]) {
    const id = sid ?? activeRef.current;
    if (!id) return;
    setSessions((prev) => {
      const s = prev.find((x) => x.id === id);
      if (!s) return prev;
      const upd = { ...s, messages: turns, updated_at: Date.now() };
      if (!upd.custom_title) upd.title = titleFor(upd);
      return upsert(prev, upd, id);
    });
  }

  // Put a session on screen: adopt its school, spec, and transcript. Does NOT bump updated_at —
  // viewing a session is not activity, so the rail order stays put (a bump here is what made
  // selecting a session jump it to the top and read as a double-highlight).
  function adoptSession(s: Session) {
    setActiveId(s.id);
    activeRef.current = s.id;
    setWspec(s.workspace);
    wspecRef.current = s.workspace;
    if (s.district_id !== districtId || s.level !== level) {
      pendingSelRef.current = s.school_id;
      if (s.district_id !== districtId) setDistrictId(s.district_id);
      if (s.level !== level) setLevel(s.level);
    } else if (s.school_id !== currentId) {
      const row = schools.find((r) => r.school_id === s.school_id);
      if (row) setSel(row);
      else pendingSelRef.current = s.school_id;
    } else {
      // Same school already selected — no selection change to trigger a fetch, so refetch here.
      fetchWorkspace(s.school_id, s.workspace);
    }
  }

  // Rail click.
  function activateSession(s: Session) {
    if (s.id === activeId) return;
    adoptSession(s);
  }

  // Rail ✕: drop a session. Deleting the active one moves to the most recent remaining, or —
  // if none are left — starts a fresh session for the school currently on screen.
  function deleteSession(id: string) {
    const remaining = byRecency(sessionsRef.current.filter((s) => s.id !== id));
    setSessions(remaining);
    sessionsRef.current = remaining;
    if (id !== activeRef.current) return; // deleted a background session — screen unaffected
    const next = remaining[0];
    if (next) {
      adoptSession(next);
    } else if (current) {
      const fresh = createSession({
        school_id: current.school_id, school_name: current.school_name,
        district_id: districtId, level,
      });
      setSessions([fresh]);
      sessionsRef.current = [fresh];
      adoptSession(fresh);
    } else {
      setActiveId(null);
      activeRef.current = null;
      setWs(null);
    }
  }

  // Fresh look at the current school: old chat context must not contaminate a new inquiry.
  function newSession() {
    if (!current) return;
    const s = createSession({
      school_id: current.school_id, school_name: current.school_name,
      district_id: districtId, level,
    });
    setSessions((prev) => upsert(prev, s, s.id));
    setActiveId(s.id);
    setWspec(s.workspace);
    wspecRef.current = s.workspace;
    fetchWorkspace(current.school_id, s.workspace);
  }

  // Apply a chat turn's workspace mutations. `sid` is the session the turn belongs to. If the
  // user has since switched away, we still PERSIST the turn's spec/title to its own session,
  // but we do NOT disturb the screen (no slot changes, no school switch) — those belong to the
  // conversation that is no longer on-screen. Only when the turn's session is still active do
  // the live-screen effects run.
  function onWorkspace(sid: string | null, w: ChatWorkspace) {
    const id = sid ?? activeRef.current;
    if (id && id !== activeRef.current) {
      setSessions((prev) => {
        const s = prev.find((x) => x.id === id);
        if (!s) return prev;
        let upd: Session = { ...s, updated_at: Date.now() };
        if (w.session_title) upd = { ...upd, title: w.session_title, custom_title: true };
        // Only a same-school slot/spotlight spec belongs to THIS session. A set_school turn's
        // spec is the OTHER school's default — dropping it here avoids corrupting this session;
        // the school switch itself is intentionally not applied to a backgrounded conversation.
        if (w.spec && !w.school) upd = { ...upd, workspace: w.spec };
        return upsert(prev, upd, id);
      });
      return;
    }
    if (w.session_title) {
      // rename_session: retitle the session the turn ran in (before any fork below).
      const title = w.session_title;
      const id = activeRef.current;
      setSessions((prev) => {
        const s = prev.find((x) => x.id === id);
        if (!s) return prev;
        return upsert(prev, { ...s, title, custom_title: true, updated_at: Date.now() }, id);
      });
    }
    if (w.spec) setWspec(w.spec);
    if (w.school) {
      if (w.school.school_id === currentId) {
        // set_school to the school already on screen = a fresh look: fork the session and
        // apply its default payloads here (no selection change fires to do it for us).
        const src = sessionsRef.current.find((s) => s.id === activeRef.current) ?? null;
        const forked = forkSession(src, {
          school_id: w.school.school_id, school_name: w.school.school_name,
          district_id: w.school.district_id, level,
        });
        if (w.spec) forked.workspace = w.spec;
        setSessions((prev) => upsert(prev, forked, forked.id));
        setActiveId(forked.id);
        setWs((prev) =>
          prev
            ? {
                ...prev,
                spec: w.spec ?? prev.spec,
                slots: [0, 1, 2].map((i) => w.payloads[`slot_${i + 1}`] ?? prev.slots[i]),
                subgroup_slice: null,
                spotlight: null,
              }
            : prev,
        );
      } else {
        forkFromRef.current = sessionsRef.current.find((s) => s.id === activeRef.current) ?? null;
        if (w.school.district_id !== districtId) {
          pendingSelRef.current = w.school.school_id;
          setDistrictId(w.school.district_id); // roster reload selects it on arrival
        } else {
          const row = schools.find((s) => s.school_id === w.school!.school_id);
          if (row) setSel(row);
          else pendingSelRef.current = w.school.school_id;
        }
      }
      return;
    }
    setWs((prev) => applyChatWorkspace(prev, w));
  }

  return (
    <div className="cols">
      <div className="rail">
        <button className="new-sess" onClick={newSession} disabled={!current}>
          + New session
        </button>
        <div className="rail-list">
          {byRecency(sessions).map((s) => (
            <div
              key={s.id}
              className={"sess" + (s.id === activeId ? " on" : "")}
              onClick={() => activateSession(s)}
              title={s.title}
            >
              <button
                className="sess-del"
                title="Delete this session"
                onClick={(e) => {
                  e.stopPropagation(); // don't also activate the row we're deleting
                  deleteSession(s.id);
                }}
              >
                ×
              </button>
              <div className="sess-title">{s.title}</div>
              <div className="sess-meta">
                {s.school_name} · {relTime(s.updated_at)}
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="diag">
        <div className="school-hd">
          <select
            className="pill pill-lg"
            title="Select a school"
            value={current ? current.school_id : ""}
            onChange={(e) => setSel(schools.find((s) => s.school_id === e.target.value) || null)}
          >
            {schools.length === 0 ? (
              <option>
                {loadState === "loading"
                  ? "loading…"
                  : loadState === "error"
                    ? "failed to load"
                    : "no schools"}
              </option>
            ) : (
              schools.map((s) => (
                <option key={s.school_id} value={s.school_id}>
                  {s.alignment === "unmet_need" ? "⚠ " : ""}
                  {s.school_name}
                </option>
              ))
            )}
          </select>
          <div className="school-sub">
            <select
              className="pill"
              title="Select a district"
              value={districtId}
              onChange={(e) => setDistrictId(e.target.value)}
            >
              {districts.length === 0 ? (
                <option value={districtId}>Long Beach Unified</option>
              ) : (
                districts.map((d) => (
                  <option key={d.district_id} value={d.district_id}>
                    {d.district_name}
                  </option>
                ))
              )}
            </select>
            <select
              className="pill"
              title="Select a level"
              value={level}
              onChange={(e) => setLevel(e.target.value as Level)}
            >
              {LEVELS.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
            <span className="sub-x">schools</span>
          </div>
          {current ? (
            <div className="feats">
              <Feat v={current.enroll_total} kind="num" lab="enrollment" />
              <Feat v={current.pct_sed} kind="pct" lab="econ-disadv" />
              <Feat v={current.pct_el} kind="pct" lab="English learners" />
              <Feat v={current.pct_swd} kind="pct" lab="students w/ disab." />
              <Feat v={current.locale} kind="str" lab="locale" />
            </div>
          ) : null}
        </div>
        <Diagnostic s={current} peers={peers} ws={ws} />
      </div>
      <div className="chat">
        <Chat
          key={activeId ?? "boot"}
          school={current}
          level={level}
          wspec={wspec}
          onWorkspace={onWorkspace}
          sessionId={activeId}
          initialMessages={activeSession?.messages ?? []}
          onMessages={onMessages}
        />
      </div>
    </div>
  );
}
