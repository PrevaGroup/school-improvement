import { useEffect, useState, type ReactNode } from "react";
import { api, ApiError } from "../api";
import { routeForEmail } from "../auth-routing";
import { signInWithProvider, signOut, watchUser, type User } from "../firebase";

// The gate in front of the app. Four states, and the third is the one that earns its keep:
//
//   checking   auth state or invite probe still resolving
//   signed-out sign-in screen
//   rejected   signed in, but NOT on the invite list — authentication is not invitation.
//              Google will happily authenticate any Gmail on earth; the backend's domain
//              allowlist decides who is actually invited (security.py). Without this state,
//              an uninvited-but-signed-in user sees a broken app full of 403s and no
//              explanation.
//   in         render the app, with a slim identity strip
//
// The invite probe is GET /api/me: the first authenticated round-trip, exercised BEFORE the
// app loads, so "token works end-to-end" and "you're invited" are proven at the door rather
// than discovered as scattered fetch errors.

type Phase =
  | { s: "checking" }
  | { s: "signed-out"; error?: string }
  | { s: "rejected"; email: string; detail: string }
  | { s: "in" }; // no email carried — the app does not display the caller's identity

export function AuthGate({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>({ s: "checking" });
  const [email, setEmail] = useState("");

  useEffect(() => {
    return watchUser(async (user: User | null) => {
      if (!user) {
        setPhase({ s: "signed-out" });
        return;
      }
      setPhase({ s: "checking" });
      try {
        await api.get("/me"); // invite probe — a 200 is the whole signal; body carries no identity
        setPhase({ s: "in" });
      } catch (e) {
        if (e instanceof ApiError && e.status === 403) {
          setPhase({
            s: "rejected",
            email: user.email ?? "(no email)",
            detail: "This account isn't on the invite list for this application.",
          });
        } else {
          // 401 (token not accepted) or network: fall back to sign-in with the reason shown.
          setPhase({ s: "signed-out", error: e instanceof Error ? e.message : String(e) });
        }
      }
    });
  }, []);

  if (phase.s === "checking") {
    return <div className="auth-screen muted dots">checking sign-in</div>;
  }

  if (phase.s === "signed-out") {
    return (
      <div className="auth-screen">
        <h1>Agentic School Improvement</h1>
        <p className="muted auth-tagline">
          Working proof of concept for agentic data analytics on school-improvement data.
        </p>
        <ul className="auth-pillars muted">
          <li>
            <strong>Semantic Data Layer:</strong> A data schema to consume available data and
            provide a grounded basis for agentic queries.
          </li>
          <li>
            <strong>Tools:</strong> Mechanisms agents use to query the data to scan indicators,
            prioritize, and begin to analyze root causes.
          </li>
          <li>
            <strong>Guidance:</strong> The agentic experience targets an opinionated perspective
            based on literature reviews.
          </li>
          <li>
            <strong>Evals:</strong> The agentic harness continuously improves leveraging
            practices advocated by leading AI companies (e.g.,{" "}
            <a
              href="https://claude.com/blog/how-anthropic-enables-self-service-data-analytics-with-claude"
              target="_blank"
              rel="noreferrer"
            >
              Anthropic
            </a>
            ,{" "}
            <a href="https://openai.com/index/inside-our-in-house-data-agent/" target="_blank" rel="noreferrer">
              OpenAI
            </a>
            ).
          </li>
        </ul>
        <p className="muted auth-note">
          This is a closed system, restricted to a handful of approved organizations. Your email
          is used only to confirm you&rsquo;re invited — it is not stored with your activity or
          shown in the app, and usage is metered anonymously. It is never shared.
        </p>
        {/* Email-first sign-in (Home Realm Discovery): people know their email, not their
            employer's identity provider. The routing table decides Google vs Microsoft;
            an uninvited domain is told so right here, before any popup. */}
        <form
          className="auth-form"
          onSubmit={(e) => {
            e.preventDefault();
            const route = routeForEmail(email);
            if ("error" in route) {
              setPhase({ s: "signed-out", error: route.error });
              return;
            }
            signInWithProvider(route.provider, route.email).catch((err) =>
              setPhase({ s: "signed-out", error: err?.message })
            );
          }}
        >
          <input
            className="auth-input"
            type="email"
            required
            autoFocus
            placeholder="you@yourorganization.org"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-label="Work email address"
          />
          <button className="auth-btn" type="submit">
            Continue
          </button>
        </form>
        {phase.error ? <p className="auth-err">{phase.error}</p> : null}
      </div>
    );
  }

  if (phase.s === "rejected") {
    return (
      <div className="auth-screen">
        <h1>Not invited</h1>
        <p>
          You're signed in as <b>{phase.email}</b>, but {phase.detail.toLowerCase()}
        </p>
        <p className="muted">
          Access is limited to invited organizations. If you believe this is a mistake, contact
          the person who sent you here.
        </p>
        <button className="auth-btn" onClick={() => void signOut()}>
          Sign in with a different account
        </button>
      </div>
    );
  }

  return (
    <>
      <div className="auth-strip">
        <AdminBadge />
        <span className="muted">Signed in</span>
        <button onClick={() => void signOut()}>Sign out</button>
      </div>
      {children}
    </>
  );
}

// Shows an "Admin" tag when the signed-in caller is an administrator (server-decided via the
// Workspace group / config allowlists). This is a UI HINT only — every admin action is gated
// server-side by require_admin. It reveals only the current user's OWN status, nothing about
// anyone else, so it doesn't reintroduce identity tracking.
function AdminBadge() {
  const [isAdmin, setIsAdmin] = useState(false);
  useEffect(() => {
    let live = true;
    api
      .get<{ is_admin: boolean }>("/admin/status")
      .then((r) => live && setIsAdmin(!!r.is_admin))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);
  if (!isAdmin) return null;
  return <span className="admin-badge">Admin</span>;
}
