import type { KeyboardEvent } from "react";
import { Link } from "react-router-dom";

import { useI18n, type StringKey } from "../i18n";

/**
 * A horizontally scrolling strip of tabs.
 *
 * Sized to be thumb-reachable and tappable without precision, and scrolled so
 * the active tab is always in view. The scroller is padded to the screen edge
 * with negative margins so a partially visible neighbour signals more content.
 *
 * Implements the ARIA tabs pattern properly, which matters more than usual here
 * because the emergency flow must be completable from a keyboard alone:
 *
 * - **Roving tabindex.** Only the selected tab is in the Tab order, so Tab moves
 *   *out* of the tab strip rather than through five stops. Without it a keyboard
 *   user walks the whole strip on every pass, which on a five-tab strip during
 *   an emergency is the difference between the tab bar and the panel being one
 *   stop apart and five.
 * - **Arrow keys** move between tabs, Home/End jump to the ends, and selection
 *   follows focus. Automatic activation is the right choice for this: the panels
 *   here are cheap and locally cached, and requiring a second keypress to see
 *   what you just selected is worse than the render.
 * - `aria-controls` points at the panel, so assistive technology can name what a
 *   tab will reveal.
 *
 * The previous version declared `role="tablist"` and `role="tab"` but left every
 * tab at the default `tabIndex` of 0 and handled no keys, which is the worst of
 * both worlds: the roles promise behaviour the component does not implement.
 */
export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  label,
  idPrefix,
}: {
  tabs: ReadonlyArray<{ id: T; label: StringKey }>;
  value: T;
  onChange: (id: T) => void;
  /** Names the group for a screen reader; the visible labels are not enough. */
  label: StringKey;
  /** Prefix for the generated tab/panel ids. Must be unique on the page. */
  idPrefix: string;
}) {
  const { t } = useI18n();

  const focusTab = (list: HTMLElement, tabId: string) => {
    // Focus follows selection, but only after React has committed the new
    // aria-selected, or the browser moves focus back to a stale node.
    queueMicrotask(() =>
      list
        .querySelector<HTMLButtonElement>(
          `#${CSS.escape(`${idPrefix}-${tabId}`)}`,
        )
        ?.focus(),
    );
  };

  const move = (list: HTMLElement, delta: number) => {
    const index = tabs.findIndex((tab) => tab.id === value);
    if (index < 0) return;
    const next = tabs[(index + delta + tabs.length) % tabs.length];
    onChange(next.id);
    focusTab(list, next.id);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const list = event.currentTarget;
    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
        event.preventDefault();
        move(list, 1);
        break;
      case "ArrowLeft":
      case "ArrowUp":
        event.preventDefault();
        move(list, -1);
        break;
      case "Home":
        event.preventDefault();
        onChange(tabs[0].id);
        focusTab(list, tabs[0].id);
        break;
      case "End":
        event.preventDefault();
        onChange(tabs[tabs.length - 1].id);
        focusTab(list, tabs[tabs.length - 1].id);
        break;
      default:
        break;
    }
  };

  return (
    <div
      role="tablist"
      aria-label={t(label)}
      onKeyDown={onKeyDown}
      className="scroll-x border-b border-line px-3"
      ref={(node) => {
        // Keeps the selected tab on screen when the tab set changes underneath,
        // and after an arrow-key move scrolls the strip. Focus moves are handled
        // from the event target instead, so this node handle is not retained.
        if (!node) return;
        const active = node.querySelector<HTMLElement>('[aria-selected="true"]');
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
            id={`${idPrefix}-${tab.id}`}
            role="tab"
            type="button"
            aria-selected={selected}
            aria-controls={`${idPrefix}-${tab.id}-panel`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab.id)}
            className={[
              "tap relative shrink-0 px-3 py-3 text-sm font-medium transition-colors duration-150 motion-reduce:transition-none",
              selected ? "text-text" : "text-muted",
            ].join(" ")}
          >
            {t(tab.label)}
            {selected && (
              <span
                aria-hidden
                className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-accent"
              />
            )}
          </button>
        );
      })}
    </div>
  );
}

/**
 * The panel belonging to the selected tab.
 *
 * Separate from the tab strip so `aria-controls` resolves to something. Given the
 * tab id and whether it is selected, this returns the wrapper only for the
 * active tab, which is what keeps a screen reader from walking three panels that
 * are all visually present in the DOM.
 */
export function TabPanel({
  tabId,
  idPrefix,
  active,
  children,
  className = "",
}: {
  tabId: string;
  idPrefix: string;
  active: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  if (!active) return null;
  return (
    <div
      id={`${idPrefix}-${tabId}-panel`}
      role="tabpanel"
      aria-labelledby={`${idPrefix}-${tabId}`}
      tabIndex={0}
      className={className}
    >
      {children}
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
    "tap flex w-full items-center gap-3 rounded-md px-3 py-3 text-left transition-colors duration-150 hover:bg-raised motion-reduce:transition-none";

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