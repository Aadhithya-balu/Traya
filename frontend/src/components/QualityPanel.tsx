import type { Quality } from "../api/types";
import { useI18n } from "../i18n";
import { AlertIcon, CheckIcon } from "./icons";

/**
 * Quality read-out.
 *
 * Shown before identification runs and again on the result. Each measurement
 * is a real score from the engine, and a failing one is named rather than left
 * for the person to infer from a bar.
 */
export function QualityPanel({
  quality,
  usable,
}: {
  quality: Quality;
  usable?: boolean;
}) {
  const { t } = useI18n();
  const isUsable = usable ?? quality.usable_for_matching;

  const rows = [
    { key: "blur", label: t("emergency.quality.blur"), value: quality.blur_score },
    { key: "light", label: t("emergency.quality.light"), value: quality.lighting_score },
    { key: "face", label: t("emergency.quality.face"), value: quality.face_visibility_score },
    {
      key: "occlusion",
      label: t("emergency.quality.occlusion"),
      // The engine reports how much is clear, so a high number is good here
      // while the other three read as "higher is better" too. No inversion.
      value: quality.occlusion_score,
    },
  ];

  return (
    <section className="card">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">{t("emergency.quality.title")}</h2>
        <span
          className={[
            "badge shrink-0",
            isUsable ? "bg-ok/15 text-ok" : "bg-danger/15 text-danger",
          ].join(" ")}
        >
          {isUsable ? (
            <CheckIcon size={13} />
          ) : (
            <AlertIcon size={13} />
          )}
          {isUsable
            ? t("emergency.quality.usable")
            : t("emergency.quality.unusable")}
        </span>
      </div>

      <dl className="mt-4 space-y-3">
        {rows.map((row) => (
          <div key={row.key}>
            <div className="flex items-baseline justify-between text-xs">
              <dt className="text-muted">{row.label}</dt>
              <dd className="font-mono text-faint">
                {Math.round(row.value * 100)}%
              </dd>
            </div>
            <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-raised">
              <div
                className={[
                  "h-full rounded-full transition-[width] duration-300",
                  row.value >= 0.5 ? "bg-text" : "bg-warn",
                ].join(" ")}
                style={{ width: `${Math.round(row.value * 100)}%` }}
              />
            </div>
          </div>
        ))}
      </dl>

      {quality.reasons?.length ? (
        <ul className="mt-4 space-y-1 border-t border-line pt-3">
          {quality.reasons.map((reason) => (
            <li key={reason} className="flex items-start gap-2 text-xs text-muted">
              <AlertIcon size={14} className="mt-px shrink-0 text-warn" />
              <span>{reason}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
