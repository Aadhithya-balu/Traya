import type { AnalyticsStatus, IdentifyStatus } from "./types";
import type { StringKey } from "../i18n";

/**
 * The nine identification outcomes, and what a responder should do about each.
 *
 * This is the map that makes Phase 9's "every result state reachable, each with
 * a working next action" true by construction rather than by review. It is keyed
 * on `IdentifyStatus`, so the compiler requires an entry for every state the
 * backend can produce, and a state added to the pipeline without a responder
 * instruction here fails the build instead of rendering a bare enum.
 *
 * Two things are deliberately kept out of this table:
 *
 * - **Severity.** Colour is not information here. A responder deciding whether to
 *   act should be reading the instruction, not judging an amber swatch, and
 *   colour is the channel that fails hardest for colour-blind users and in
 *   sunlight. Tone is available but every state also has a word.
 * - **Confidence.** Not present because it is not always meaningful: `NO_FACE`
 *   and `MULTIPLE_FACES` have no score at all, and showing a percentage beside a
 *   photo that contains no usable face is a lie of omission.
 */
export type ResultTone = "go" | "decide" | "lookAgain" | "retake" | "neutral";

export interface ResultState {
  /** Short badge text. States the action, not the enum. */
  readonly badge: StringKey;
  /** The one line that tells the responder what to do next. */
  readonly next: StringKey;
  readonly tone: ResultTone;
}

export const RESULT_STATES: Record<IdentifyStatus, ResultState> = {
  HIGH_CONFIDENCE: {
    badge: "result.high",
    next: "result.next.high",
    tone: "go",
  },
  CONFIRMED: {
    badge: "result.confirmed",
    next: "result.next.confirmed",
    tone: "go",
  },
  REVIEW_REQUIRED: {
    badge: "result.review",
    next: "result.next.review",
    tone: "decide",
  },
  MULTIPLE_CANDIDATES: {
    badge: "result.multiple",
    next: "result.next.multiple",
    tone: "decide",
  },
  LOW_CONFIDENCE: {
    badge: "result.low",
    next: "result.next.low",
    tone: "lookAgain",
  },
  NO_MATCH: {
    badge: "result.none",
    next: "result.next.nomatch",
    tone: "lookAgain",
  },
  NO_FACE: {
    badge: "result.noface",
    next: "result.next.retake",
    tone: "retake",
  },
  MULTIPLE_FACES: {
    badge: "result.multiplefaces",
    next: "result.next.multiplefaces",
    tone: "retake",
  },
  POOR_QUALITY: {
    badge: "emergency.quality.unusable",
    next: "result.next.poorquality",
    tone: "retake",
  },
};

/**
 * Badge state for the analytics breakdown, which is not a live identification.
 *
 * Kept separate from `RESULT_STATES` so that table stays exactly nine entries
 * and the compiler keeps it exhaustive over `IdentifyStatus`. Folding "unknown"
 * in would mean either weakening the key type or special-casing inside a map
 * whose whole value is that it cannot be.
 *
 * An analytics row describes a bucket in a report, not something a responder is
 * looking at, so it gets a neutral tone and no "what to do next" instruction.
 */
export function analyticsBadge(status: AnalyticsStatus): ResultState | null {
  if (status === "unknown") {
    return { badge: "analytics.unknown", next: "result.next.label", tone: "neutral" };
  }
  return RESULT_STATES[status];
}

/**
 * Every state, in the order a responder meets them.
 *
 * Used by the demo page to exercise every branch rather than only the happy one,
 * which is how an unreachable result state gets discovered at all - three of the
 * nine were never rendered by any code path before this table existed.
 */
export const RESULT_STATE_ORDER = [
  "HIGH_CONFIDENCE",
  "REVIEW_REQUIRED",
  "MULTIPLE_CANDIDATES",
  "LOW_CONFIDENCE",
  "NO_MATCH",
  "CONFIRMED",
  "NO_FACE",
  "MULTIPLE_FACES",
  "POOR_QUALITY",
] as const satisfies readonly IdentifyStatus[];