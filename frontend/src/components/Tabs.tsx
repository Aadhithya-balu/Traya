import { Link } from "react-router-dom";

import { useI18n, type StringKey } from "../i18n";

/**
 * A horizontally scrolling strip of tabs.
 *
 * Sized to be thumb-reachable and tappable without precision, and scrolled so
 * the active tab is always in view. The scroller is padded to the screen edge
 * with negative margins so a partially visible neighbour signals more content.
 */
export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: ReadonlyArray<{ id: T; label: StringKey }>;
  value: T;
  onChange: (id: T) => void;
}) {
  const { t } = useI18n();

  return (
    <div
      role="tablist"
      className="scroll-x border-b border-line px-3"
      ref={(node) => {
        if (!node) return;
        const active = node.querySelector<HTMLElement>('[aria-selected="true"]');
        // Keep the selected tab on screen when the tab set changes underneath.
        queueMicrotask(() =>
          active?.scrollIntoView({ block: "nearest", inline: "center" }),
        );
      }}
    >
      {tabs.map((tab) => {
        const selected = tab.id === value;
        return (
          <button
            key={tab.id}
            role="tab"
            type="button"
            aria-selected={selected}
            onClick={() => onChange(tab.id)}
            className={[
              "tap relative shrink-0 px-3 py-3 text-sm font-medium transition-colors duration-150",
              selected ? "text-text" : "text-muted",
            ].join(" ")}
          >
            {t(tab.label)}
            {selected && (
              <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-accent" />
            )}
          </button>
        );
      })}
    </div>
  );
}

/** A full-width stacked list item, used across every list surface. */
export function ListRow({
  to,
  onClick,
  title,
  subtitle,
  trailing,
}: {
  to?: string;
  onClick?: () => void;
  title: string;
  subtitle?: string;
  trailing?: React.ReactNode;
}) {
  const body = (
    <>
      <span className="min-w-0 flex-1 text-left">
        <span className="block truncate text-sm font-medium text-text">
          {title}
        </span>
        {subtitle && (
          <span className="mt-0.5 block truncate text-xs text-muted">
            {subtitle}
          </span>
        )}
      </span>
      {trailing}
    </>
  );

  const className =
    "tap flex w-full items-center gap-3 rounded-md px-3 py-3 text-left transition-colors duration-150 hover:bg-raised";

  if (to) {
    return (
      <Link to={to} className={className}>
        {body}
      </Link>
    );
  }
  return (
    <button type="button" onClick={onClick} className={className}>
      {body}
    </button>
  );
}
