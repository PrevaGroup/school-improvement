import { useEffect, useState, type ReactNode } from "react";
import { api, ApiError } from "../api";
import { routeForEmail } from "../auth-routing";
import {
  completeEmailLinkSignIn,
  forgetSignIn,
  lastSignIn,
  rememberSignIn,
  sendEmailSignInLink,
  signInWithProvider,
  signOut,
  watchUser,
  type User,
} from "../firebase";

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
  | { s: "link-sent"; email: string } // magic link emailed — waiting on the click
  | { s: "rejected"; email: string; detail: string }
  | { s: "in" }; // no email carried — the app does not display the caller's identity

export function AuthGate({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<Phase>({ s: "checking" });
  // Seeded from the last sign-in so a reload while signed out keeps the pre-filled address.
  const [email, setEmail] = useState(lastSignIn());
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let unsub = () => {};
    (async () => {
      // If this page load is a returning magic link, finish sign-in FIRST so watchUser's
      // first callback already reflects the signed-in user (no signed-out flash).
      try {
        await completeEmailLinkSignIn();
      } catch {
        setPhase({ s: "signed-out", error: "That sign-in link didn't work — request a new one." });
      }
      unsub = watchUser(async (user: User | null) => {
        if (!user) {
          // Keep the "check email" screen, and keep any reason already on screen: the 401
          // branch below signs out on purpose, and this callback fires as a result. Without
          // the second guard that sign-out would race the explanation off the screen and
          // leave a bare sign-in form, which is the confusion this whole path exists to end.
          setPhase((p) =>
            p.s === "link-sent" || (p.s === "signed-out" && p.error) ? p : { s: "signed-out" },
          );
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
            // 401 (token not accepted) or network. The server is the authority on whether a
            // session is still good, so make the client AGREE with it rather than keeping a
            // Firebase session the backend rejects on every reload — that disagreement is
            // what made this state sticky: the app showed a sign-in screen while silently
            // still signed in, and reloading reproduced the failure exactly.
            //
            // Remember the address first. The commonest cause by far is `auth_time` ageing
            // past session_max_age_days, where the person is who they say they are and has
            // simply been away a week; asking them to retype an address they already proved
            // they own is friction with nothing on the other side of it.
            rememberSignIn(user.email);
            if (user.email) setEmail(user.email);
            setPhase({
              s: "signed-out",
              error:
                e instanceof ApiError
                  ? e.detail ?? e.message // the server's sentence when it sent one
                  : "Couldn't reach the server — check your connection and try again.",
            });
            void signOut(); // the guard above protects the message from the resulting callback
          }
        }
      });
    })();
    return () => unsub();
  }, []);

  async function submitEmail() {
    const route = routeForEmail(email);
    if ("error" in route) {
      setPhase({ s: "signed-out", error: route.error });
      return;
    }
    setBusy(true);
    try {
      if (route.method === "sso") {
        await signInWithProvider(route.provider, route.email);
      } else {
        await sendEmailSignInLink(route.email);
        setPhase({ s: "link-sent", email: route.email });
      }
    } catch (err) {
      setPhase({ s: "signed-out", error: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(false);
    }
  }

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
            sign-in method. Member orgs go to their own IdP; everyone else gets a one-time
            sign-in link emailed to that exact address. The backend allowlist is the real gate. */}
        <form
          className="auth-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (!busy) void submitEmail();
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
            aria-label="Email address"
            disabled={busy}
          />
          <button className="auth-btn" type="submit" disabled={busy}>
            {busy ? "…" : "Continue"}
          </button>
        </form>
        {phase.error ? <p className="auth-err">{phase.error}</p> : null}
      </div>
    );
  }

  if (phase.s === "link-sent") {
    return (
      <div className="auth-screen">
        <h1>Check your email</h1>
        <p className="auth-tagline">
          We sent a one-time sign-in link to <b>{phase.email}</b>. Open it on this device to
          finish — it confirms you own the address, and it expires shortly.
        </p>
        <p className="muted auth-note">
          No link after a minute? Check spam, or{" "}
          <button
            className="auth-linkbtn"
            onClick={() => setPhase({ s: "signed-out" })}
          >
            try a different email
          </button>
          . You still need to be on the invite list — the link proves the mailbox is yours, not
          that you&rsquo;re approved.
        </p>
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
          Access is granted either to an invited organization's whole domain, or to named people
          in the group that may use this application. If you should have access, ask whoever sent
          you here to add you to that group — it takes effect within a few minutes.
        </p>
        <button
          className="auth-btn"
          onClick={() => {
            // "A different account" is the one request pre-filling the old one would defeat.
            forgetSignIn();
            setEmail("");
            void signOut();
          }}
        >
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
        <button
          onClick={() => {
            // Deliberate: unlike an aged-out session, this may be someone handing the
            // machine over. Don't leave their address in the next person's sign-in box.
            forgetSignIn();
            setEmail("");
            void signOut();
          }}
        >
          Sign out
        </button>
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
