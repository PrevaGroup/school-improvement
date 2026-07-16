import { useEffect, useState, type ReactNode } from "react";
import { api, ApiError } from "../api";
import { signInWithGoogle, signOut, watchUser, type User } from "../firebase";

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
  | { s: "in"; email: string };

export function AuthGate({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>({ s: "checking" });

  useEffect(() => {
    return watchUser(async (user: User | null) => {
      if (!user) {
        setPhase({ s: "signed-out" });
        return;
      }
      setPhase({ s: "checking" });
      try {
        const me = await api.get<{ email: string }>("/me");
        setPhase({ s: "in", email: me.email });
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
        <h1>School Improvement</h1>
        <p className="muted auth-tagline">
          Working proof of concept to demonstrate agentic data analytics best practices
          according to leading AI companies (e.g.,{" "}
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
          )
        </p>
        <p className="muted">Attendance diagnostics · peers · grounded chat</p>
        <button
          className="auth-btn"
          onClick={() => signInWithGoogle().catch((e) => setPhase({ s: "signed-out", error: e?.message }))}
        >
          Sign in with Google
        </button>
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
        <span className="muted">{phase.email}</span>
        <button onClick={() => void signOut()}>Sign out</button>
      </div>
      {children}
    </>
  );
}
