import { useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../context/AuthContext";
import { useI18n, LOCALES, type Locale, type StringKey } from "../i18n";
import { useTheme } from "../theme";
import { Sheet } from "./Sheet";
import { ListRow } from "./Tabs";
import {
  AlertIcon,
  BeakerIcon,
  ChevronRightIcon,
  GlobeIcon,
  GridIcon,
  HomeIcon,
  MoreIcon,
  MoonIcon,
  PulseIcon,
  ShieldIcon,
  SunIcon,
  UserIcon,
} from "./icons";

interface TabDef {
  to: string;
  label: StringKey;
  icon: typeof HomeIcon;
  /** Shown only when the person is signed in. */
  requiresAuth?: boolean;
}

/**
 * The bottom bar carries the four things a person reaches for most. It is
 * fixed, thumb-reachable and always in the same place, which is the whole
 * point: a rescuer using this app one-handed in a crowd should never have to
 * hunt for navigation.
 */
const PRIMARY_TABS: TabDef[] = [
  { to: "/", label: "nav.home", icon: HomeIcon },
  { to: "/emergency", label: "nav.emergency", icon: PulseIcon },
  { to: "/dashboard", label: "nav.dashboard", icon: GridIcon, requiresAuth: true },
  { to: "/profile", label: "nav.profile", icon: UserIcon, requiresAuth: true },
];

export function Layout() {
  const { t, locale, setLocale } = useI18n();
  const { theme, toggleTheme } = useTheme();
  const { isAuthed, hasRole, user, logout } = useAuth();
  const [sheetOpen, setSheetOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  // Leaving the emergency flow must not leave the sheet covering it.
  const onEmergencyFlow = location.pathname.startsWith("/emergency");

  const visibleTabs = PRIMARY_TABS.filter(
    (tab) => !tab.requiresAuth || isAuthed,
  );

  // Emergency Mode is a workflow state, not an authentication state, so it must
  // never offer a way to end the session. Logout used to be reachable from the
  // menu on /emergency/*: one mis-tap mid-emergency destroyed the login, and the
  // person using the app could not tell that from being logged out. The session
  // now survives the whole workflow by construction, and this is the other half.
  const moreItems: Array<{
    to?: string;
    onClick?: () => void;
    label: string;
    icon: typeof HomeIcon;
  }> = [
    { to: "/demo", label: t("nav.demo"), icon: BeakerIcon },
    ...(hasRole("admin") && !onEmergencyFlow
      ? [{ to: "/admin", label: t("nav.admin"), icon: ShieldIcon }]
      : []),
    { to: "/privacy", label: t("nav.privacy"), icon: AlertIcon },
  ];

  return (
    <div className="min-h-screen bg-canvas">
      <AppBar
        onOpenMenu={() => setSheetOpen(true)}
        hideMenu={onEmergencyFlow}
      />

      <main
        className={[
          "mx-auto w-full max-w-2xl px-4",
          // During the emergency flow the bar is hidden so the camera and the
          // shutter get the full height of the screen.
          onEmergencyFlow ? "pb-safe" : "pb-tabbar",
        ].join(" ")}
      >
        <Outlet />
      </main>

      {!onEmergencyFlow && (
        /* Opaque, not /95. At 95% the content underneath is faintly legible as
           it scrolls past, which on a result screen is exactly the wrong thing
           to see. A background blur also costs a compositing layer on every
           frame for no benefit once the background is solid.

           Note: the class name is deliberately not written in this comment.
           Tailwind's content scanner does not strip comments, so mentioning a
           utility here emits it into the stylesheet. */
        <nav
          aria-label={t("nav.menu")}
          className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-surface pb-safe"
        >
          <div className="mx-auto flex max-w-2xl items-stretch">
            {visibleTabs.map((tab) => (
              <TabLink key={tab.to} tab={tab} />
            ))}
            <TabButton
              to=""
              label={t("nav.more")}
              icon={MoreIcon}
              onClick={() => setSheetOpen(true)}
            />
          </div>
        </nav>
      )}

      <Sheet
        open={sheetOpen}
        title={user?.full_name ?? t("nav.menu")}
        onClose={() => setSheetOpen(false)}
      >
        <div className="py-1">
          {moreItems.map((item) => (
            <ListRow
              key={item.to}
              to={item.to}
              title={item.label}
              trailing={<ChevronRightIcon size={18} className="text-faint" />}
            />
          ))}

          <div className="divider my-2" />

          <div className="flex items-center justify-between px-3 py-2">
            <span className="flex items-center gap-2 text-sm text-muted">
              <GlobeIcon size={18} />
              {t("a11y.language")}
            </span>
            <div className="flex rounded-md border border-line p-0.5">
              {LOCALES.map((code) => (
                <button
                  key={code}
                  type="button"
                  onClick={() => setLocale(code as Locale)}
                  aria-pressed={locale === code}
                  className={[
                    // The pill stays 28px tall; `tap` grows the hit area to 44px
                    // and the negative margin takes the difference back out so
                    // the segmented control does not get taller.
                    "tap -my-2 rounded px-2.5 py-1.5 text-xs font-medium transition-colors",
                    locale === code
                      ? "bg-accent text-accent-fg"
                      : "text-muted",
                  ].join(" ")}
                >
                  {t(code === "en" ? "lang.en" : "lang.ta")}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center justify-between px-3 py-2">
            <span className="flex items-center gap-2 text-sm text-muted">
              {theme === "dark" ? <MoonIcon size={18} /> : <SunIcon size={18} />}
              {t("a11y.theme")}
            </span>
            <button
              type="button"
              onClick={toggleTheme}
              aria-label={t("a11y.theme")}
              className="tap -my-2 relative h-7 w-12 rounded-full bg-raised transition-colors"
            >
              <span
                className={[
                  "absolute left-0.5 top-0.5 h-6 w-6 rounded-full bg-text transition-transform duration-150",
                  // The knob is w-6 (1.5rem) in a w-12 (3rem) track, so the full
                  // travel is 1.5rem = spacing 6. The old -translate-x-5.5 is not
                  // in theme.spacing, which is `replace` and not `extend`, so the
                  // class compiled to nothing and the knob never visibly moved in
                  // either theme. Only the icon changed.
                  theme === "dark" ? "translate-x-6" : "translate-x-0",
                ].join(" ")}
              />
            </button>
          </div>

          {isAuthed && !onEmergencyFlow && (
            <>
              <div className="divider my-2" />
              <ListRow
                onClick={() => {
                  setSheetOpen(false);
                  logout();
                  navigate("/");
                }}
                title={t("nav.logout")}
              />
            </>
          )}
        </div>
      </Sheet>
    </div>
  );
}

function AppBar({
  onOpenMenu,
  hideMenu,
}: {
  onOpenMenu: () => void;
  hideMenu?: boolean;
}) {
  const { t } = useI18n();
  const { isAuthed } = useAuth();

  return (
    <header className="sticky top-0 z-30 border-b border-line bg-canvas">
      <div className="h-appbar pt-safe" />
      <div className="mx-auto flex h-14 max-w-2xl items-center justify-between px-4">
        <Link to="/" className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-text text-sm font-bold text-canvas">
            T
          </span>
          <span className="text-base font-semibold tracking-tight">
            {t("app.name")}
          </span>
        </Link>
        {/* Nothing but identity during an emergency: no menu, so no way to end
            the session by accident. */}
        {isAuthed && !hideMenu && (
          <button
            type="button"
            onClick={onOpenMenu}
            className="btn btn-quiet btn-sm px-3"
            aria-label={t("nav.menu")}
          >
            <MoreIcon size={20} />
          </button>
        )}
        {!isAuthed && (
          <Link to="/login" className="btn btn-ghost px-4 text-sm">
            {t("nav.login")}
          </Link>
        )}
      </div>
    </header>
  );
}

function TabLink({ tab }: { tab: TabDef }) {
  const { t } = useI18n();
  return (
    <NavLink
      to={tab.to}
      end={tab.to === "/"}
      className={({ isActive }) => tabClasses(isActive)}
    >
      <tab.icon size={22} />
      <span className="text-[11px] font-medium leading-none">
        {t(tab.label)}
      </span>
    </NavLink>
  );
}

function TabButton({
  label,
  icon: Icon,
  onClick,
}: {
  to?: string;
  label: string;
  icon: typeof HomeIcon;
  onClick: () => void;
}) {
  return (
    <button type="button" onClick={onClick} className={tabClasses(false)}>
      <Icon size={22} />
      <span className="text-[11px] font-medium leading-none">{label}</span>
    </button>
  );
}

function tabClasses(isActive: boolean) {
  return [
    // `tap` is load-bearing, not decoration. These are the most-tapped controls
    // in the app and `py-2` alone gave 41px, one pixel under the 44px floor.
    "tap flex flex-1 flex-col items-center justify-center gap-1 py-2 transition-colors duration-150",
    isActive ? "text-text" : "text-faint",
  ].join(" ");
}
