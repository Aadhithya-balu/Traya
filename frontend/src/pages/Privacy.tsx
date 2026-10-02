import { useI18n, type StringKey } from "../i18n";

/**
 * The privacy and safety model, stated on the page rather than only in the docs.
 *
 * Every string here was a hardcoded English literal until Phase 9, which is why
 * this page used none of the `privacy.*` namespace it already had. The copy is
 * unusually load-bearing: this is the page a hospital admin opens to decide
 * whether they trust the thing, and a claim that cannot be read by half the
 * staff who must agree to it is not a disclosure.
 *
 * The six principles are keyed by slug rather than by array index so that
 * reordering them cannot silently relabel one as another, and so a removed
 * principle fails the key-existence test in `test_frontend_contract.py` instead
 * of quietly shifting every later entry up by one.
 */
const PRINCIPLES: ReadonlyArray<{ slug: string; title: StringKey; desc: StringKey }> = [
  {
    slug: "minimal",
    title: "privacy.principle.minimal.title",
    desc: "privacy.principle.minimal.desc",
  },
  {
    slug: "encrypted",
    title: "privacy.principle.encrypted.title",
    desc: "privacy.principle.encrypted.desc",
  },
  {
    slug: "noimages",
    title: "privacy.principle.noimages.title",
    desc: "privacy.principle.noimages.desc",
  },
  {
    slug: "consent",
    title: "privacy.principle.consent.title",
    desc: "privacy.principle.consent.desc",
  },
  {
    slug: "human",
    title: "privacy.principle.human.title",
    desc: "privacy.principle.human.desc",
  },
  {
    slug: "audit",
    title: "privacy.principle.audit.title",
    desc: "privacy.principle.audit.desc",
  },
];

/**
 * Roles and what each may see.
 *
 * `privacy.role.admin.*` is not decoration: RLS is enabled on every table and the
 * hosted project has been verified as filtering, but the application connects as
 * the table owner and therefore bypasses its own policies. This list is the
 * published promise; whether the platform enforces it end to end is documented
 * honestly in [ADR 0007](../decisions/0007-rls-claims-and-live-role-resolution.md)
 * and must not be overclaimed here.
 */
const ROLES: ReadonlyArray<{ label: StringKey; desc: StringKey }> = [
  { label: "privacy.role.public.label", desc: "privacy.role.public.desc" },
  { label: "privacy.role.registered.label", desc: "privacy.role.registered.desc" },
  { label: "privacy.role.responder.label", desc: "privacy.role.responder.desc" },
  { label: "privacy.role.auditor.label", desc: "privacy.role.auditor.desc" },
  { label: "privacy.role.admin.label", desc: "privacy.role.admin.desc" },
];

export function Privacy() {
  const { t } = useI18n();

  return (
    <div className="mx-auto max-w-3xl px-4 py-14">
      <h1 className="text-3xl font-bold text-text">{t("privacy.heading")}</h1>
      <p className="mt-3 text-muted">{t("privacy.intro")}</p>

      <div className="mt-8 space-y-4">
        {PRINCIPLES.map((p) => (
          <div key={p.slug} className="card">
            <h2 className="mb-1 font-semibold text-text">{t(p.title)}</h2>
            <p className="text-sm leading-relaxed text-muted">{t(p.desc)}</p>
          </div>
        ))}
      </div>

      <div className="mt-8 rounded-xl border border-line bg-raised p-5 text-sm text-muted">
        <h2 className="mb-2 font-semibold text-text">{t("privacy.roles.title")}</h2>
        <ul className="space-y-1">
          {ROLES.map((r) => (
            <li key={r.label}>
              {/* The role name is set in the accent colour so the list scans as a
                  table of authorities rather than a paragraph of prose. */}
              <span className="text-accent">{t(r.label)}</span>{" — "}
              {t(r.desc)}
            </li>
          ))}
        </ul>
      </div>

      <p className="mt-6 text-xs text-faint">{t("privacy.demo")}</p>
    </div>
  );
}