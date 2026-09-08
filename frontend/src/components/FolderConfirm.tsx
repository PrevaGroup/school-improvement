import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";

// Confirming a folder: the teacher agrees with a SET once, instead of correcting it file by file.
//
// The whole screen is built around one idea — the unit is the folder, not the paper. So:
//
//  * The counts come first, and all five appear even at zero. A summary that showed only the
//    resolved would be the twenty-seven-files-twenty-four-scores failure with a nicer interface.
//  * Who handed in NOTHING sits beside who did. It is what a teacher chases, and the one thing a
//    per-file view structurally cannot show.
//  * Files needing a person sort to the top. A list ordered by filename buries the three that
//    matter among the twenty-five that do not, which is the review this exists to replace.
//  * Correcting a match is available and deliberately not the main action. If a teacher is fixing
//    half the folder the reconciliation broke, and the inferred rate says so.

type FileRow = {
  file_id: string;
  name: string;
  status: string;
  reason_code: string | null;
  word_count: number | null;
  candidates: { student_id: string; display_name: string | null; score: number }[] | null;
  resolved_student_id: string | null;
  resolution_basis: string | null;
  resolution_path: string | null;
  match_score: number | null;
  display_name: string | null;
};

type Student = { student_id: string; display_name: string | null };

type ManifestRow = {
  manifest_id: string;
  source_kind: string;
  source_ref: string;
  read_at: string | null;
  declared_section_id: string | null;
  declared_task_id: string | null;
  declared_iteration: string | null;
  declared_window_label: string | null;
  file_count: number;
  inferred_rate: number | null;
  confirmed_at: string | null;
  confirmed_by: string | null;
  resolved: number; unresolved: number; not_student_work: number;
  unreadable: number; empty: number;
};

type ManifestDetail = ManifestRow & {
  files: FileRow[];
  missing_students: Student[];
  roster: Student[];
};

// Every outcome named in words a teacher would use. None of them is "missing" — the whole point
// of five statuses is that a folder never quietly becomes a smaller number of papers.
const STATUS: Record<string, { label: string; hint: string }> = {
  resolved:         { label: "Named", hint: "we know whose this is" },
  unresolved:       { label: "Needs you", hint: "nothing in the file said whose it is" },
  not_student_work: { label: "Not a submission", hint: "the assignment, or a template" },
  unreadable:       { label: "Could not open", hint: "a format or a permission, not an absence" },
  empty:            { label: "Nothing in it", hint: "opened fine, no writing" },
};
const ORDER = ["unresolved", "unreadable", "empty", "not_student_work", "resolved"];

function when(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined,
    { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function FolderConfirm() {
  const [reads, setReads] = useState<ManifestRow[]>([]);
  const [available, setAvailable] = useState<boolean | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<ManifestDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadList = useCallback(async () => {
    try {
      const r = await api.get<{ available: boolean; manifests: ManifestRow[] }>(
        "/intake/manifests");
      setAvailable(r.available);
      setReads(r.manifests);
      if (r.manifests.length && !selected) setSelected(r.manifests[0].manifest_id);
    } catch (e) {
      setAvailable(false);
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, [selected]);

  const loadDetail = useCallback(async (id: string) => {
    try {
      setDetail(await api.get<ManifestDetail>(`/intake/manifest/${encodeURIComponent(id)}`));
    } catch (e) {
      setDetail(null);
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, []);

  useEffect(() => { void loadList(); }, [loadList]);
  useEffect(() => { if (selected) { setError(null); void loadDetail(selected); } }, [selected, loadDetail]);

  async function assign(file_id: string, student_id: string | null) {
    if (!detail) return;
    setBusy(true); setError(null);
    try {
      await api.post(`/intake/file/${encodeURIComponent(file_id)}/assign`, { student_id });
      await loadDetail(detail.manifest_id);
      await loadList();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally { setBusy(false); }
  }

  async function confirm() {
    if (!detail) return;
    setBusy(true); setError(null);
    try {
      await api.post(`/intake/manifest/${encodeURIComponent(detail.manifest_id)}/confirm`, {});
      await loadDetail(detail.manifest_id);
      await loadList();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally { setBusy(false); }
  }

  if (available === false) {
    return (
      <div className="rv-empty">
        <h2>No folders read yet</h2>
        <p>
          This fills once a folder of student work has been read. It is not an error — nothing has
          been handed in to the system yet.
        </p>
        {error && <p className="rv-err">{error}</p>}
      </div>
    );
  }

  return (
    <div className="rv">
      <aside className="rv-queue">
        <ul>
          {reads.map((r) => (
            <li key={r.manifest_id}
                className={r.manifest_id === selected ? "rv-sel" : ""}
                onClick={() => setSelected(r.manifest_id)}>
              <b>{r.source_ref.split(/[/\\]/).pop() || r.source_ref}</b>
              <span className={`rv-state ${r.confirmed_at ? "rv-released" : "rv-in_review"}`}>
                {r.confirmed_at ? "Confirmed" : "Waiting for you"}
              </span>
              <small>
                {r.file_count} file{r.file_count === 1 ? "" : "s"} · read {when(r.read_at)}
                {r.unresolved > 0 && <em> · {r.unresolved} need you</em>}
              </small>
            </li>
          ))}
        </ul>
        {!reads.length && <p className="rv-mut">Nothing read yet.</p>}
      </aside>

      <section className="rv-paper">
        {error && <div className="rv-err">{error}</div>}
        {!detail && <p className="rv-mut">Select a folder.</p>}
        {detail && (
          <Folder d={detail} busy={busy} onAssign={assign} onConfirm={confirm} />
        )}
      </section>
    </div>
  );
}

function Folder({ d, busy, onAssign, onConfirm }: {
  d: ManifestDetail; busy: boolean;
  onAssign: (file_id: string, student_id: string | null) => void;
  onConfirm: () => void;
}) {
  const counts = [
    ["resolved", d.resolved], ["unresolved", d.unresolved], ["empty", d.empty],
    ["unreadable", d.unreadable], ["not_student_work", d.not_student_work],
  ] as const;
  const locked = !!d.confirmed_at;
  const byStatus = ORDER
    .map((s) => [s, d.files.filter((f) => f.status === s)] as const)
    .filter(([, files]) => files.length > 0);

  return (
    <>
      <header className="rv-head">
        <div>
          <h2>{d.source_ref.split(/[/\\]/).pop() || d.source_ref}</h2>
          <small>
            {d.declared_task_id} · {d.declared_iteration} · {d.declared_window_label} ·
            read {when(d.read_at)}
          </small>
        </div>
        <div className="rv-actions">
          {locked ? (
            <span className="rv-state rv-released">Confirmed by {d.confirmed_by}</span>
          ) : (
            <button className="rv-primary" disabled={busy} onClick={onConfirm}>
              This is right — confirm the folder
            </button>
          )}
        </div>
      </header>

      {/* All five, always, even at zero. A folder never quietly becomes a smaller number. */}
      <section className="fc-counts">
        {counts.map(([k, n]) => (
          <div key={k} className={`fc-count${n === 0 ? " zero" : ""}`}>
            <b>{n}</b>
            <span>{STATUS[k].label}</span>
            <small>{STATUS[k].hint}</small>
          </div>
        ))}
      </section>

      {!locked && (
        <div className="rv-note">
          Confirming says <b>the set is right</b> — that this folder is that class's work on this
          task, and that the files nobody could place genuinely cannot be placed. Nothing is scored
          until you do. Fix any wrong matches first; once confirmed the read is fixed as a record
          and a change means reading the folder again.
        </div>
      )}

      {d.missing_students.length > 0 && (
        <section className="rv-criteria">
          <h3>Handed in nothing</h3>
          <div className="fc-missing">
            {d.missing_students.map((s) => (
              <span key={s.student_id}>{s.display_name ?? s.student_id}</span>
            ))}
          </div>
        </section>
      )}

      {d.inferred_rate != null && d.inferred_rate >= 0.5 && (
        <div className="rv-note">
          <b>{Math.round(d.inferred_rate * 100)}% of these were matched on the filename alone.</b>{" "}
          Nothing in this folder carried an owner account, so the matching had only names to go on.
          Worth a closer look at the list below than you would give a folder from Drive.
        </div>
      )}

      {byStatus.map(([status, files]) => (
        <section key={status} className="rv-criteria">
          <h3>{STATUS[status].label} <span className="rv-mut">· {files.length}</span></h3>
          {files.map((f) => (
            <FileRowView key={f.file_id} f={f} roster={d.roster} locked={locked} busy={busy}
                         onAssign={onAssign} />
          ))}
        </section>
      ))}
    </>
  );
}

function FileRowView({ f, roster, locked, busy, onAssign }: {
  f: FileRow; roster: Student[]; locked: boolean; busy: boolean;
  onAssign: (file_id: string, student_id: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState("");
  const candidates = f.candidates ?? [];
  const attachable = f.status !== "not_student_work" && f.status !== "unreadable";

  return (
    <div className={`rv-crit ${f.status === "unresolved" ? "rv-needs" : ""}`}>
      <div className="rv-crit-head">
        <div>
          <b>{f.name}</b>
          <small> {f.word_count != null ? `${f.word_count} words` : ""}</small>
        </div>
        <div className="rv-level">
          {f.display_name ? (
            <span className="fc-who">{f.display_name}</span>
          ) : (
            <span className="rv-nonum">{STATUS[f.status]?.label ?? f.status}</span>
          )}
          {/* How we know, not just that we know. A name match and an account lookup have
              different error profiles and a teacher checking the list needs to see which. */}
          {f.resolution_path && (
            <span className="rv-badge">
              {f.resolution_basis === "teacher" ? "you said"
                : f.resolution_path === "looked_up" ? "account" : "filename"}
            </span>
          )}
        </div>
      </div>

      {f.reason_code && f.status !== "resolved" && (
        <p className="rv-mut">{f.reason_code.replace(/_/g, " ")}</p>
      )}

      {!locked && attachable && (
        <div className="rv-override">
          {!open && (
            <button disabled={busy} onClick={() => setOpen(true)}>
              {f.display_name ? "Change who this is" : "Say whose this is"}
            </button>
          )}
          {open && (
            <div className="rv-override-form">
              {candidates.map((c) => (
                <button key={c.student_id} className="rv-primary" disabled={busy}
                        onClick={() => { onAssign(f.file_id, c.student_id); setOpen(false); }}>
                  {c.display_name ?? c.student_id}
                </button>
              ))}
              <select value={picked} disabled={busy}
                      onChange={(e) => setPicked(e.target.value)}>
                <option value="">{candidates.length ? "Someone else…" : "Choose a student…"}</option>
                {roster.map((r) => (
                  <option key={r.student_id} value={r.student_id}>
                    {r.display_name ?? r.student_id}
                  </option>
                ))}
              </select>
              <button disabled={busy || !picked}
                      onClick={() => { onAssign(f.file_id, picked); setOpen(false); }}>
                Save name
              </button>
              {f.display_name && (
                <button disabled={busy}
                        onClick={() => { onAssign(f.file_id, null); setOpen(false); }}>
                  Detach
                </button>
              )}
              <button disabled={busy} onClick={() => setOpen(false)}>Cancel</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
