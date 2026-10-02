import { useEffect, useRef, useState } from "react";

/**
 * Announces a short status change to assistive technology without stealing focus.
 *
 * Every capture and identification state change in the emergency flow routes
 * through one of these. That is the requirement Phase 9's gate states as "a
 * screen reader announces every capture and identification state", and it is not
 * satisfiable by adding `aria-live` to whatever happens to be on screen: a
 * region that only exists while a state is showing announces nothing when the
 * state is *replaced*, which is precisely when the responder most needs to know.
 *
 * Two details that are easy to get wrong:
 *
 * - The region is rendered always, even when empty. A live region added to the
 *   DOM at the same moment as its text is frequently not announced at all,
 *   because the assistive technology never saw it change.
 * - The previous message is cleared for one frame before the new one is set.
 *   Setting the same text twice in a row is not a change, so "Identifying…"
 *   followed by "Identifying…" for a retake would be silent.
 */
export function LiveStatus({
  message,
  assertive = false,
  className = "",
}: {
  message: string;
  /**
   * `assertive` interrupts whatever is being read. Correct for a failed
   * identification and a confirmation, wrong for routine progress.
   */
  assertive?: boolean;
  className?: string;
}) {
  const [announced, setAnnounced] = useState("");
  const previous = useRef("");

  useEffect(() => {
    if (message === previous.current) return;
    previous.current = message;
    setAnnounced("");
    const frame = requestAnimationFrame(() => setAnnounced(message));
    return () => cancelAnimationFrame(frame);
  }, [message]);

  return (
    <div
      role="status"
      aria-live={assertive ? "assertive" : "polite"}
      aria-atomic="true"
      className={className}
    >
      {announced}
    </div>
  );
}