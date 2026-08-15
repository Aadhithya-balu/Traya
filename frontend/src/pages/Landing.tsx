import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

const FEATURES = [
  {
    title: "AI identity matching",
    desc: "Quality-checked face capture is matched against encrypted enrollment templates to propose an identity for an unresponsive victim.",
  },
  {
    title: "Medical alerts",
    desc: "After a reliable match, only treatment-critical information is disclosed — blood type, critical allergies and conditions.",
  },
  {
    title: "Emergency contact",
    desc: "One tap notifies the victim's designated emergency contact with your verification and secure location.",
  },
  {
    title: "Hospital routing",
    desc: "Nearby emergency-capable hospitals are surfaced with distance and availability, so responders pick the right destination.",
  },
  {
    title: "Privacy by design",
    desc: "Biometric templates are encrypted at rest, never exposed to clients, and everything is audited. Minimal data, maximal safety.",
  },
  {
    title: "Human confirmation",
    desc: "Any uncertain match is held for human review — TRAYA never fabricates an identity.",
  },
];

export function Landing() {
  const { isAuthed } = useAuth();

  return (
    <div>
      <section className="relative overflow-hidden border-b border-slate-800">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_70%_-10%,rgba(20,184,166,0.18),transparent_55%)]" />
        <div className="relative mx-auto max-w-6xl px-4 py-20 text-center sm:py-28">
          <p className="mb-4 inline-block rounded-full border border-accent-500/30 bg-accent-500/10 px-4 py-1 text-xs font-medium text-accent-400">
            Prototype · Synthetic demo data only
          </p>
          <h1 className="mx-auto max-w-3xl text-4xl font-bold leading-tight text-white sm:text-6xl">
            Identify the unresponsive.{" "}
            <span className="text-accent-400">Deliver the right care.</span>
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-lg text-slate-400">
            TRAYA is an AI-assisted emergency victim identification platform. A single
            photo of an unresponsive person flows through real quality checks, biometric
            matching, medical alerting, contact notification and hospital routing.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <Link to="/emergency" className="btn-primary">
              Start emergency session
            </Link>
            <Link to="/demo" className="btn-ghost">
              Try the demo scenarios
            </Link>
            {!isAuthed && (
              <Link to="/register" className="btn-ghost">
                Create profile
              </Link>
            )}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-16">
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <div key={f.title} className="card">
              <h3 className="mb-2 text-base font-semibold text-white">{f.title}</h3>
              <p className="text-sm leading-relaxed text-slate-400">{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="border-t border-slate-800 bg-ink-950 py-14">
        <div className="mx-auto max-w-4xl px-4 text-center">
          <h2 className="text-2xl font-bold text-white">How it works</h2>
          <ol className="mt-8 grid gap-6 text-left sm:grid-cols-3">
            {[
              ["1", "Capture", "A responder or bystander photographs the victim's face. Quality gates reject blurry, obstructed or multi-face images."],
              ["2", "Match", "The face is embedded and compared against enrolled templates. Scores decide: high-confidence, review-required, or no match."],
              ["3", "Respond", "Medical alerts, emergency contact, location and nearby hospitals are surfaced for the matched identity."],
            ].map(([n, t, d]) => (
              <li key={n} className="card">
                <span className="mb-3 inline-flex h-8 w-8 items-center justify-center rounded-full bg-accent-500/15 font-mono text-sm font-bold text-accent-400">
                  {n}
                </span>
                <h3 className="mb-1 font-semibold text-white">{t}</h3>
                <p className="text-sm text-slate-400">{d}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="mx-auto max-w-4xl px-4 py-14 text-center">
        <h2 className="text-2xl font-bold text-white">Built for the golden hour</h2>
        <p className="mx-auto mt-3 max-w-2xl text-slate-400">
          Every second counts in a trauma situation. TRAYA keeps the loop tight: capture,
          match, alert, route — without leaking private medical history to anyone who
          doesn't need it.
        </p>
        <div className="mt-6 flex justify-center gap-3">
          <Link to="/emergency" className="btn-primary">
            Start now
          </Link>
          <Link to="/privacy" className="btn-ghost">
            Read the privacy model
          </Link>
        </div>
      </section>
    </div>
  );
}
