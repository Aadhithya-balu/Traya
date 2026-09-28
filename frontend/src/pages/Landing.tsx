import { Link } from "react-router-dom";

import { useI18n, type StringKey } from "../i18n";
import { ArrowIcon, CheckIcon } from "../components/icons";

const FEATURES: Array<{ id: string; title: StringKey; body: StringKey }> = [
  { id: "f1", title: "landing.f1.title", body: "landing.f1.body" },
  { id: "f2", title: "landing.f2.title", body: "landing.f2.body" },
  { id: "f3", title: "landing.f3.title", body: "landing.f3.body" },
  { id: "f4", title: "landing.f4.title", body: "landing.f4.body" },
  { id: "f5", title: "landing.f5.title", body: "landing.f5.body" },
  { id: "f6", title: "landing.f6.title", body: "landing.f6.body" },
];

const STEPS: Array<{ title: StringKey; body: StringKey }> = [
  { title: "landing.f1.title", body: "landing.f1.body" },
  { title: "landing.f3.title", body: "landing.f3.body" },
  { title: "landing.f4.title", body: "landing.f4.body" },
];

export function Landing() {
  const { t } = useI18n();

  return (
    <div className="py-6">
      <section className="animate-rise">
        <span className="badge border border-line text-muted">
          {t("landing.badge")}
        </span>
        <h1 className="mt-4 text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">
          {t("landing.title")}
        </h1>
        <p className="mt-3 text-base leading-relaxed text-muted">
          {t("landing.body")}
        </p>

        {/* Full-width on a phone; side by side once there is room. */}
        <div className="mt-6 flex flex-col gap-3 sm:flex-row">
          <Link to="/emergency" className="btn btn-primary btn-lg btn-block">
            <ArrowIcon size={20} />
            {t("landing.cta.primary")}
          </Link>
          <Link to="/demo" className="btn btn-ghost btn-lg btn-block">
            {t("landing.cta.secondary")}
          </Link>
        </div>
      </section>

      <section className="mt-10">
        <h2 className="eyebrow">{t("landing.features.title")}</h2>
        <ul className="mt-3 space-y-2">
          {FEATURES.map((feature) => (
            <li key={feature.id} className="card flex gap-3">
              <span className="mt-0.5 shrink-0 text-ok">
                <CheckIcon size={18} />
              </span>
              <div className="min-w-0">
                <h3 className="text-sm font-semibold">{t(feature.title)}</h3>
                <p className="mt-1 text-sm leading-relaxed text-muted">
                  {t(feature.body)}
                </p>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-10">
        <h2 className="eyebrow">{t("landing.steps.title")}</h2>
        <ol className="mt-3 space-y-3">
          {STEPS.map((step, index) => (
            <li key={step.title} className="flex gap-3">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-line text-xs font-semibold text-muted">
                {index + 1}
              </span>
              <div className="min-w-0 pt-0.5">
                <h3 className="text-sm font-semibold">{t(step.title)}</h3>
                <p className="mt-1 text-sm leading-relaxed text-muted">
                  {t(step.body)}
                </p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="mt-10">
        <Link to="/emergency" className="btn btn-primary btn-lg btn-block">
          {t("landing.cta.primary")}
          <ArrowIcon size={20} />
        </Link>
        <Link
          to="/register"
          className="mt-3 block text-center text-sm text-muted underline underline-offset-4"
        >
          {t("auth.register.title")}
        </Link>
      </section>
    </div>
  );
}
