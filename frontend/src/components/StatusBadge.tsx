import type { AnalyticsStatus, IdentifyResult, IdentifyStatus } from "../api/types";
import {
  RESULT_STATES,
  analyticsBadge,
  type ResultTone,
} from "../api/resultStates";
import { useI18n, type StringKey } from "../i18n";

type Tone = "ok" | "warn" | "danger" | "neutral";

const TONE_CLASS: Record<Tone, string> = {
  ok: "bg-ok/15 text-ok",
  warn: "bg-warn/15 text-warn",
  danger: "bg-danger/15 text-danger",
  neutral: "bg-raised text-muted",
};

/** A result tone maps onto the palette, but never carries meaning on its own. */
function toneClass(tone: ResultTone): string {
  if (tone === "go") return TONE_CLASS.ok;
  if (tone === "decide") return TONE_CLASS.warn;
  if (tone === "retake") return TONE_CLASS.danger;
  if (tone === "neutral") return TONE_CLASS.neutral;
  return TONE_CLASS.warn;
}

/**
 * The instruction a responder should follow for a status, in words.
 *
 * The badge answers "what happened". This answers "what now", which is the part
 * that was missing: a responder who is handed "REVIEW REQUIRED" with no
 * instruction has been given a classification, not a decision.
 */
export function NextAction({ status }: { status: IdentifyStatus }) {
  const { t } = useI18n();
  const state = RESULT_STATES[status];
  return (
    <p className="text-sm text-text">
      <span className="sr-only">{t("result.next.label")}: </span>
      {t(state.next)}
    </p>
  );
}

/**
 * Map a status code to a plain-language label and a tone.
 *
 * The labels deliberately describe what the person should do, not the internal
 * enum, so nobody has to know what REVIEW_REQUIRED means.
 *
 * Total by construction: `RESULT_STATES` is keyed on `IdentifyStatus`, so this
 * lookup is exhaustive and a new backend state will not compile until someone
 * decides what a responder should be told. The previous version took a bare
 * `string` and fell back to `status.replaceAll("_", " ")`, which meant
 * MULTIPLE_CANDIDATES and CONFIRMED - two of the nine - rendered as internal
 * enum names on screen, in a product whose stated goal is that nobody reads ML
 * vocabulary during an emergency.
 *
 * Takes `AnalyticsStatus` rather than `IdentifyStatus` only so the same badge
 * can render a report bucket; `analyticsBadge` is what resolves the extra
 * member, and every live-result caller passes one of the nine.
 */
export function StatusBadge({ status }: { status: AnalyticsStatus }) {
  const { t } = useI18n();
  const state = analyticsBadge(status);
  if (!state) return null;
  return <span className={`badge ${toneClass(state.tone)}`}>{t(state.badge)}</span>;
}

/** A pre-existing generic status badge for non-identification state. */
export function GenericStatusBadge({
  status,
  labels,
}: {
  status: string;
  labels: Record<string, StringKey>;
}) {
  const { t } = useI18n();
  const key = labels[status];
  const label = key ? t(key) : status.replaceAll("_", " ").toLowerCase();
  return <span className={`badge ${TONE_CLASS.neutral}`}>{label}</span>;
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
  // Declared before the `value === null` early return on purpose. Calling a hook
  // after an early return makes the hook count depend on `value`, and a result
  // that arrives with a score after rendering as null - which is exactly what
  // happens while an identification is in flight - would then change the number
  // of hooks on a mounted component.
  const { t } = useI18n();

  if (value === null) {
    return (
      <p className="text-xs text-muted">
        <span className="font-mono">{t("common.notApplicable")}</span>
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
