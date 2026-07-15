import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { fmtNum, fmtPct } from "./format";
import { Chat } from "./components/Chat";
import { Diagnostic } from "./components/Diagnostic";
import type { District, DiagnosticSchool, Level, Peer, SchoolDetail } from "./types";

const DEMO_DISTRICT = "0622500"; // Long Beach Unified (NCES LEAID) — the demo default
const LEVELS: Level[] = ["High", "Middle", "Primary"];

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
  const [level, setLevel] = useState<Level>("High");
  const [districtId, setDistrictId] = useState(DEMO_DISTRICT);
  const [districts, setDistricts] = useState<District[]>([]);
  const [schools, setSchools] = useState<SchoolRow[]>([]);
  const [sel, setSel] = useState<SchoolRow | null>(null);
  const [peers, setPeers] = useState<Peer[] | null>(null);
  const [detail, setDetail] = useState<SchoolDetail | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");

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
        setSchools(d.schools || []);
        setSel((d.schools || [])[0] || null);
        setLoadState("ready");
      })
      .catch(() => setLoadState("error"));
  }, [level, districtId]);

  const current = useMemo(
    () => schools.find((s) => sel && s.school_id === sel.school_id) || sel,
    [schools, sel],
  );

  const currentId = current?.school_id;
  useEffect(() => {
    if (!currentId) {
      setPeers(null);
      setDetail(null);
      return;
    }
    setPeers(null);
    setDetail(null);
    api
      .get<{ peers: Peer[] }>(`/marts/like-schools?school_id=${currentId}&k=50`)
      .then((d) => setPeers(d.peers || []))
      .catch(() => setPeers([]));
    api
      .get<SchoolDetail>(`/marts/school-detail?school_id=${currentId}`)
      .then(setDetail)
      .catch(() => setDetail(null));
  }, [currentId]);

  return (
    <div className="cols">
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
        <Diagnostic s={current} peers={peers} detail={detail} />
      </div>
      <div className="chat">
        <Chat school={current} level={level} />
      </div>
    </div>
  );
}
