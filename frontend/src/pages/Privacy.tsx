const PRINCIPLES = [
  {
    title: "Minimal disclosure",
    desc: "Public emergency users only ever see treatment-critical facts (blood type, critical allergies/conditions) after a reliable match. Full medical history is never exposed.",
  },
  {
    title: "Encrypted templates",
    desc: "Biometric embeddings are encrypted at rest with app-level encryption. They are decrypted only in-memory during a match and never returned to any client.",
  },
  {
    title: "No raw images stored",
    desc: "Uploaded photos are processed into embeddings and then discarded. TRAYA does not persist victim photographs.",
  },
  {
    title: "Informed consent",
    desc: "Enrollment requires an explicit, revocable biometric consent. Withdrawing it disables face matching for that account.",
  },
  {
    title: "Human confirmation",
    desc: "Ambiguous matches are held for a human responder to review and confirm. The system refuses to assert identity it is not confident about.",
  },
  {
    title: "Full audit trail",
    desc: "Every access to medical data, every confirmation, and every rate-limit event is recorded in an immutable audit log.",
  },
];

export function Privacy() {
  return (
    <div className="mx-auto max-w-3xl px-4 py-14">
      <h1 className="text-3xl font-bold text-white">Privacy & safety model</h1>
      <p className="mt-3 text-slate-400">
        TRAYA is built on a simple idea: emergency care needs the minimum necessary
        information, released only to the people who need it, at the moment they need it.
      </p>

      <div className="mt-8 space-y-4">
        {PRINCIPLES.map((p) => (
          <div key={p.title} className="card">
            <h2 className="mb-1 font-semibold text-white">{p.title}</h2>
            <p className="text-sm leading-relaxed text-slate-400">{p.desc}</p>
          </div>
        ))}
      </div>

      <div className="mt-8 rounded-xl border border-slate-800 bg-ink-800 p-5 text-sm text-slate-400">
        <h2 className="mb-2 font-semibold text-white">Role-based access</h2>
        <ul className="space-y-1">
          <li>
            <span className="text-accent-400">Public</span> — can start an emergency session
            and capture a photo; sees only the match result and a public medical summary.
          </li>
          <li>
            <span className="text-accent-400">Registered user</span> — their own profile,
            consents and contact details.
          </li>
          <li>
            <span className="text-accent-400">Responder</span> — can confirm identities and
            view the responder profile (treatment notes, visible features, contacts).
          </li>
          <li>
            <span className="text-accent-400">Auditor</span> — read-only access to the audit
            log.
          </li>
          <li>
            <span className="text-accent-400">Admin</span> — platform configuration, user
            management and hospital registry.
          </li>
        </ul>
      </div>

      <p className="mt-6 text-xs text-slate-500">
        This prototype operates exclusively on synthetic demo data. It demonstrates the
        workflows and controls of the production platform.
      </p>
    </div>
  );
}
