import { useEffect, useRef, type ReactNode } from "react";

import { CloseIcon } from "./icons";
import { useI18n } from "../i18n";

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * A bottom sheet.
 *
 * On a phone this is the right shape for secondary navigation and for
 * grouped actions: it anchors to the thumb, never covers the whole screen, and
 * dismisses the way every other sheet on the platform does.
 *
 * **It behaves as a modal, because it is one.** The overlay says
 * `aria-modal="true"`, so a screen reader is entitled to ignore everything
 * behind the sheet. That makes the focus behaviour load-bearing rather than
 * nice-to-have: focus is moved in when the sheet opens, Tab is trapped inside
 * it, and focus is returned to whatever opened it on close. Before Phase 9 this
 * only handled Escape, so keyboard focus walked straight out of a dialog that
 * claimed to be modal and onto the page underneath.
 */
export function Sheet({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const { t } = useI18n();
  const dialogRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);

  // Lock the page behind the sheet so scrolling the content underneath cannot
  // fight the sheet gesture, and keep focus inside it.
  useEffect(() => {
    if (!open) return;
    const node = dialogRef.current;
    restoreRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;

    const focusables = () =>
      node
        ? Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
            (el) => el.offsetParent !== null || el === document.activeElement,
          )
        : [];

    // Move focus in. The close button is the first focusable, which is the
    // conventionally safe landing spot for a dismissible dialog.
    const initial = focusables();
    (initial[0] ?? node)?.focus();

    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
        return;
      }
      if (event.key !== "Tab" || !node) return;
      const items = focusables();
      if (items.length === 0) {
        event.preventDefault();
        node.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || active === node)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKey);
      restoreRef.current?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex flex-col justify-end">
      <button
        type="button"
        aria-label={t("common.close")}
        onClick={onClose}
        className="absolute inset-0 animate-fade-in bg-black/50"
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className="relative animate-sheet-in rounded-t-2xl border-t border-line bg-surface pb-safe"
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 className="text-base font-semibold">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("common.close")}
            className="btn btn-quiet -mr-2 px-2"
          >
            <CloseIcon size={20} />
          </button>
        </div>
        <div className="max-h-[75vh] overflow-y-auto p-2">{children}</div>
      </div>
    </div>
  );
}
