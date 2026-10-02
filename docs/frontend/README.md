[../README.md](../README.md) | [Backend](../backend/README.md) | [Decisions](../decisions/README.md)

# Frontend

React 18, TypeScript 5, Vite 5, Tailwind 3, React Router 6. No UI library, no
state library, no i18n library - all four roles are filled by hand-rolled code
in this directory, and all four are documented here.

```
src/
  main.tsx              provider order, router mount
  App.tsx               the whole route table
  index.css             colour tokens, component classes, base rules
  api/
    client.ts           fetch wrapper, token refresh, 44 methods
    types.ts            24 interfaces mirroring the Pydantic schemas
  components/           Layout, Guards, Sheet, Tabs, StatusBadge,
                        QualityPanel, icons
  context/
    AuthContext.tsx     current user, roles, permissions
    EmergencyContext.tsx  in-flight session, result, preview
  hooks/
    useCamera.ts        rear-camera stream, canvas capture, base64
    useGeolocation.ts   one-shot GPS fix
  i18n/
    index.tsx           provider, key-type assertion
    strings.ts          en + ta, 20 namespaces
  pages/                10 screens
  utils/
    format.ts           date, percentage, distance, duration
  theme/ThemeProvider.tsx  light/dark, localStorage, OS default
```

| Page | Covers |
|---|---|
| [routing.md](routing.md) | Route table, guards, provider order, navigation. |
| [pages.md](pages.md) | All 10 screens, their state, their calls, their defects. |
| [components.md](components.md) | The 6 component files and all 17 icons. |
| [state-and-data.md](state-and-data.md) | Contexts, hooks, the API client, all 24 types. |
| [design-system.md](design-system.md) | Colour tokens, spacing, classes, motion, i18n. |

## Conventions

- **API calls go through `api/client.ts`.** No page calls `fetch` directly. The
  client owns base URL, auth header, 401 refresh and error shape.
- **Relative paths.** `client.ts` prefixes `/api`, and Vite proxies that to
  `127.0.0.1:8000` in dev. Nothing hardcodes a host.
- **Tailwind utility classes plus the composed classes** in `index.css`. If a
  button style is about to be written out a third time, it belongs in
  `@layer components`.
- **Mobile-first.** Layout is designed for 320px; wider breakpoints are
  enhancements.
- **Every user-visible string is an i18n key.** Phase 9 took the last five
  pages onto `t()`, and
  `test_no_page_or_component_hardcodes_user_visible_english` fails the build if
  a literal returns. The Tamil catalogue has had no native review, so the guard
  proves the script and placeholders, not the meaning.
- **Simulation disclosure is mandatory** wherever an `IdentifyResult` is
  rendered. See [ADR 0001](../decisions/0001-simulation-biometric-engine.md).

## Commands

Run from `frontend/`.

| Command | What it does |
|---|---|
| `npm run dev` | Vite dev server on `localhost:5173`, proxies `/api` to the backend. |
| `npm run build` | `tsc --noEmit` then `vite build` into `dist/`. |
| `npm run typecheck` | `tsc --noEmit` alone. |
| `npm run preview` | Serves the built `dist/` locally. |

`npm run build` runs the typecheck first, so a build is a typecheck. There is
no test runner configured - see the gap list in
[pages.md](pages.md).

## How the two servers fit together

Vite binds `localhost` (which resolves to IPv6 `::1` on this machine) and
uvicorn binds `127.0.0.1` (IPv4). The proxy target in `vite.config.ts` is
therefore spelled `127.0.0.1` explicitly. Probing `localhost:8000` from a
browser works; probing `::1:8000` does not.

`vite.config.ts` also sets `base: "./"`, so the same build can be served by
FastAPI from `dist/` at an arbitrary path. That has a consequence for routing -
see [routing.md](routing.md#base-path-caveat).
