[../README.md](../README.md) | [Frontend index](README.md) | [Pages](pages.md)

# Routing and Guards

React Router **6.30.4**, declarative `<Routes>`. Not v7, not
`createBrowserRouter`, no data router. The route table lives in one place,
`src/App.tsx`, and every page is reachable from there or not at all.

## Provider order

`src/main.tsx` nests providers outside-in:

```
StrictMode
  ThemeProvider          theme preference, applies .dark to <html>
  I18nProvider           locale, applies <html lang>
    BrowserRouter        routing
      AuthProvider        current user, roles, permissions
        EmergencyProvider in-flight emergency session
          App             routes
```

`ThemeProvider` and `I18nProvider` sit outside `BrowserRouter` so the shell can
read the locale and theme before any route renders. `useAuth` and
`useEmergency` **throw** if their provider is missing, which turns a wiring
mistake into an immediate, obvious error rather than a silent `undefined`.

## Route table

One layout route wraps every page. `Layout.tsx` renders `<Outlet />` inside
`<main>`; if it renders `{children}` instead, **every page renders blank**.

| # | Path | Element | Guard | Reachable by |
|---|---|---|---|---|
| 1 | `/` | `Landing` | none | everyone |
| 2 | `/login` | `Login` | none | everyone |
| 3 | `/register` | `Register` | none | everyone |
| 4 | `/privacy` | `Privacy` | none | everyone |
| 5 | `/connect` | `Connect` | none | everyone; the first-run screen on a packaged app |
| 6 | `/emergency` | `Emergency` | none | everyone, including unauthenticated bystanders |
| 7 | `/emergency/:sessionId` | `EmergencyHub` | none | session token or responder |
| 8 | `/demo` | `Demo` | none | everyone |
| 9 | `/dashboard` | `Dashboard` | `Protected` | any authenticated user |
| 10 | `/profile` | `Profile` | `Protected` | any authenticated user |
| 11 | `/admin` | `Admin` | `AdminOnly` | `admin` role only |
| 12 | `*` | `Landing` | none | catch-all, so unknown URLs land somewhere sane |

`Layout` also redirects a native app to `/connect` on first run when no backend
base is configured (`Capacitor.isNativePlatform()`), because a WebView has no
same-origin API and would otherwise fail every request against `https://localhost`.

## Guards

`src/components/Guards.tsx`. Both take `children` and return either a redirect,
a loading state, or the children.

| Guard | Logic |
|---|---|
| `Protected` | `loading` -> `Loading...`. `!isAuthed` -> `<Navigate to="/login" replace />`. Otherwise children. |
| `AdminOnly` | `loading` -> `Loading...`. `!isAuthed` -> `/login`. `!hasRole("admin")` -> `/dashboard`. Otherwise children. |

`AdminOnly` deliberately sends an authenticated non-admin to the dashboard
rather than to login, because login would be a confusing answer to "I am already
signed in but cannot see this".

**Client-side guards are a UX convenience, not security.** Every one of these
pages calls an endpoint that independently enforces authorization server-side
via `require_permission`. Removing a guard from the frontend changes nothing
about access; it only changes whether a user sees a friendly page or a 403.

## Client-side role and permission checks

`useAuth()` exposes two predicates:

| Call | Returns |
|---|---|
| `hasRole(...roles)` | `true` if the user holds any of the named roles. `false` for a null user. |
| `can(permission)` | `true` if the user's resolved `permissions` include it. `false` for a null user. |

`can` is currently **not called anywhere**. Nothing in the UI is gated on a
permission, only on roles. The data is there (`UserSummary.permissions` is
populated by `GET /api/auth/me`), so adopting it is a matter of replacing
`hasRole` calls with `can` where the check is about capability rather than
identity - for example the confirm-identity button, which is really the
`confirm_identity` permission rather than "is a responder".

## Navigation visibility

`Layout.tsx` builds the bottom tab bar from `PRIMARY_TABS` and hides it
entirely on `/emergency*`, switching `<main>` padding from `pb-tabbar` to
`pb-safe` so the camera view and shutter button get the full screen. A user
mid-emergency can still leave via the app bar, but the primary navigation does
not offer a way to abandon a capture by accident.

Secondary destinations (admin, demo, privacy, language, theme, logout) live in
the More sheet rather than the tab bar, so the bar stays at four items on a
320px screen.

## Adding a route

1. Add the `<Route path element />` to `src/App.tsx`. Keep the list in one place.
2. Decide the guard: none, `Protected`, or `AdminOnly`. If it needs a capability
   rather than a role, prefer `AdminOnly`-style composition with a new guard
   built on `can`.
3. Give the page a section in [pages.md](pages.md).
4. Add the link to `PRIMARY_TABS` or the More sheet in `Layout.tsx`, with a
   `StringKey` label so it is translated.
5. Run `npm run typecheck` and `npm run docs:check`.

## Base path caveat

`vite.config.ts` sets `base: "./"`, which is what lets the same build be served
by FastAPI from `frontend/dist` at an arbitrary path. But `BrowserRouter`
assumes root-absolute routes, so `<Link to="/dashboard">` resolves from the
origin root, not the mount point. It works today only because FastAPI serves
the SPA from `/`. **If you ever mount the build under a sub-path, switch to
`HashRouter` or `basename` in the same change** - otherwise every in-app link
silently escapes the mount point.
