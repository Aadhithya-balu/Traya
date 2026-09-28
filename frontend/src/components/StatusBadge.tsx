import type { IdentifyResult } from "../api/types";
import { useI18n, type StringKey } from "../i18n";

type Tone = "ok" | "warn" | "danger" | "neutral";

const TONE_CLASS: Record<Tone, string> = {
  ok: "bg-ok/15 text-ok",
  warn: "bg-warn/15 text-warn",
  danger: "bg-danger/15 text-danger",
  neutral: "bg-raised text-muted",
};

/**
 * Map a status code to a plain-language label and a tone.
 *
 * The labels deliberately describe what the person should do, not the internal
 * enum, so nobody has to know what REVIEW_REQUIRED means.
 */
const STATUS: Record<string, { key: StringKey; tone: Tone }> = {
  HIGH_CONFIDENCE: { key: "result.high", tone: "ok" },
  REVIEW_REQUIRED: { key: "result.review", tone: "warn" },
  LOW_CONFIDENCE: { key: "result.low", tone: "warn" },
  NO_MATCH: { key: "result.none", tone: "danger" },
  NO_FACE: { key: "result.none", tone: "danger" },
  MULTIPLE_FACES: { key: "result.none", tone: "danger" },
  POOR_QUALITY: { key: "emergency.quality.unusable", tone: "danger" },
};

export function StatusBadge({ status }: { status: string }) {
  const { t } = useI18n();
  const entry = STATUS[status] ?? { key: null, tone: "neutral" as Tone };
  const label = entry.key ? t(entry.key) : status.replaceAll("_", " ").toLowerCase();
  return <span className={`badge ${TONE_CLASS[entry.tone]}`}>{label}</span>;
}

/** A single similarity score, shown as a bar with the number alongside. */
export function ScoreBar({
  value,
  thresholdHigh = 0.82,
  thresholdReview = 0.62,
}: {
  value: number | null;
  thresholdHigh?: number;
  thresholdReview?: number;
}) {
  if (value === null) {
    return (
      <p className="text-xs text-muted">
        <span className="font-mono">n/a</span>
      </p>
    );
  }
  const pct = Math.round(value * 100);
  // The threshold ticks sit under the bar so a responder can see how close a
  // result is to the REVIEW line without reading the number.
  const marks = [thresholdReview, thresholdHigh];
  return (
    <div>
      <div className="flex items-center gap-2">
        <div className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-raised">
          <div
            className="h-full rounded-full bg-text"
            style={{ width: `${pct}%` }}
          />
          {marks.map((mark) => (
            <span
              key={mark}
              aria-hidden
              className="absolute inset-y-0 w-px bg-faint"
              style={{ left: `${Math.round(mark * 100)}%` }}
            />
          ))}
        </div>
        <span className="w-10 shrink-0 text-right font-mono text-xs text-muted">
          {pct}%
        </span>
      </div>
    </div>
  );
}

/**
 * The single most important banner in the product: this matcher is a
 * demonstration, not a production biometric. It is stated plainly on every
 * result rather than buried in a footer.
 */
export function SimulationNotice({ result }: { result?: IdentifyResult }) {
  const { t } = useI18n();
  if (result?.engine_mode !== "simulation" && result?.engine_mode !== undefined) {
    return null;
  }
  return (
    <div className="rounded-md border border-warn/40 bg-warn/10 p-3 text-xs leading-relaxed text-warn">
      {t("result.simulation")}
    </div>
  );
}
