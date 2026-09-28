import { useEffect, type ReactNode } from "react";

import { CloseIcon } from "./icons";
import { useI18n } from "../i18n";

/**
 * A bottom sheet.
 *
 * On a phone this is the right shape for secondary navigation and for
 * grouped actions: it anchors to the thumb, never covers the whole screen, and
 * dismisses the way every other sheet on the platform does.
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

  // Lock the page behind the sheet so scrolling the content underneath cannot
  // fight the sheet gesture.
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKey);
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
        role="dialog"
        aria-modal="true"
        aria-label={title}
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
