# TRAYA Documentation

Documentation for every component of TRAYA. One page per subsystem, written so a
new contributor can find any component, understand its contract, and change it
without breaking its neighbours.

## How to read this

| If you want to... | Read |
|---|---|
| **Understand what exists today, honestly** | **[AUDIT.md](AUDIT.md)** |
| **Understand where this is going** | **[TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md)** |
| **Understand the order of work** | **[MIGRATION_PLAN.md](MIGRATION_PLAN.md)** |
| **Understand it without any technical terms** | **[NON_TECHNICAL.md](NON_TECHNICAL.md)** |
| Understand the current system in detail | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Call or add an HTTP endpoint | [backend/api.md](backend/api.md) |
| Understand auth, roles, permissions | [backend/security.md](backend/security.md) |
| Change a table or add a migration | [backend/data-model.md](backend/data-model.md) |
| Change matching, quality or enrollment logic | [backend/services.md](backend/services.md) |
| Add a data-access method | [backend/repositories.md](backend/repositories.md) |
| Change env vars or settings | [backend/configuration.md](backend/configuration.md) |
| Add or change a screen | [frontend/pages.md](frontend/pages.md) |
| Add a route or guard | [frontend/routing.md](frontend/routing.md) |
| Add or restyle a UI component | [frontend/components.md](frontend/components.md) |
| Change state, hooks or API calls | [frontend/state-and-data.md](frontend/state-and-data.md) |
| Change colours, spacing, theme, language | [frontend/design-system.md](frontend/design-system.md) |
| Run, seed, test, deploy | [operations/README.md](operations/README.md) |
| Know why something is the way it is | [decisions/README.md](decisions/README.md) |

## Structure

```
docs/
  AUDIT.md                    Phase 1: verified current state, ranked bugs
  TARGET_ARCHITECTURE.md      Phase 2: the destination design
  MIGRATION_PLAN.md           Phase 2: 13 phases, gates, rollback
  MODEL_EVALUATION.md         FAR, FRR, EER, ROC, latency, calibration
  SECURITY_MODEL.md           Threats, controls, what is deliberately absent
  NON_TECHNICAL.md            For reviewers, faculty and non-technical readers
  ARCHITECTURE.md             system overview, the flows that matter, trust boundaries
  backend/
    api.md                   every HTTP endpoint, grouped by router
    security.md              roles, the 18 permissions, session tokens, crypto
    data-model.md            every table, relationship and migration
    services.md              every service module and its public functions
    repositories.md          every repository class and method
    configuration.md         every settings field and env var
  frontend/
    routing.md               route table, guards, redirects, provider order
    pages.md                 every page: purpose, data, state, defects
    components.md            every UI component and every icon
    state-and-data.md        contexts, hooks, API client, TypeScript types
    design-system.md         colour tokens, component classes, theme, i18n
  operations/
    README.md                local dev, seeding, testing, migrations, deployment
  decisions/
    README.md                architecture decision records
```

29 component references, 6 ADRs, five narrative pages.

## The documentation contract

Documentation is only useful if it cannot silently go stale. TRAYA enforces
three rules mechanically via `npm run docs:check`.

### Rule 1 - every component is named

Every router endpoint, ORM model, table, migration, repository method, service
function, settings field, permission, role, page, UI component, icon, API
client method and exported TypeScript type must be named on its owning docs
page. Adding a component without adding it here fails the check.

### Rule 2 - no broken links

Every relative markdown link inside `docs/` must resolve to a file that exists.

### Rule 3 - consistent page shape

Every page has exactly one H1, at least one H2, and a breadcrumb back to this
index.

### Running the check

```bash
npm run docs:check
```

It exits non-zero and lists every uncovered identifier with the page that should
own it. Currently 20 checks over 29 pages, covering 47 endpoints, 38 models, 4
migrations, 73 repository identifiers, 70 service identifiers, 37 settings,
25 permission and role identifiers, 20 pages and components, 17 icons, 43 API
methods, 26 types, 11 routes, 34 design tokens and i18n namespaces.

`npm run verify` at the root is an alias for the same check.

Run it in the same commit as any component change. This is part of the
project's definition of done, alongside the backend test suite and the frontend
build.

## Writing conventions

- **Component contract first.** Start with what the component exposes and what
  it guarantees, not with how it is implemented internally.
- **Document the reason, not the obvious.** "Calls the database" is noise.
  "Never commits implicitly, so a domain write and its audit row share one
  transaction" is the reason that prevents a future bug.
- **Record the sharp edges.** Every repository here has at least one behaviour
  that will surprise a reasonable reader (an unused permission, a race-prone
  sequence generator, a type that lies). Those are written down.
- **Never document intent that is not implemented.** Where a feature is
  incomplete or a component is dead code, the docs say so plainly and point at
  the tracking item. A doc that describes an aspiration is worse than no doc.
- **Match the code.** Names, signatures and paths are copied from source, not
  paraphrased. When code and docs disagree, code is right and the docs are a bug.

## Accuracy status

Some parts of this codebase are deliberately incomplete. The docs state this
rather than hiding it. The most important caveat:

> **Two engines exist, and neither is a validated biometric.** A real one (YuNet
> + SFace, 128-dimensional) is selected when its weight files are present; the
> original simulation remains selectable and is what runs when they are not. The
> real engine's thresholds are **still the simulation's** — nothing is calibrated,
> and it has been measured on three photographs of two people, which is not an
> accuracy claim. It must not be used to identify a real person. See
> [decisions/0008-real-biometric-engine.md](decisions/0008-real-biometric-engine.md),
> [decisions/0001-simulation-biometric-engine.md](decisions/0001-simulation-biometric-engine.md),
> and the measurements in [MODEL_EVALUATION.md](MODEL_EVALUATION.md).

`engine_mode` and `demo_mode` are returned on every identification result and
surfaced by the UI, so which engine produced a match is never a guess. Templates
are tagged with the engine's version, so the two vector spaces can never be
compared with each other.

Beyond the engine, the docs name several other places where the code does not
do what you would assume. They are documented as they are, not as intended:

| Known gap | Where |
|---|---|
| `database/` SQL and RLS assets do not exist | [operations](operations/README.md#sql-assets) |
| No row-level security; authorization is Python-only | [architecture](ARCHITECTURE.md#database) |
| `SimulationNotice` is never rendered | [components](frontend/components.md#simulationnotice) |
| Five pages still hardcode English | [pages](frontend/pages.md#legacy-pages) |
| `.env.example` covers 20 of 36 settings | [operations](operations/README.md#env-example-is-incomplete) |
| No frontend test runner | [operations](operations/README.md#testing) |
| No browser, camera or E2E run | [audit](AUDIT.md#still-not-verified) |

**Closed in Phase 1**, and no longer gaps: the emergency flow's 403s, the blank
Match Result tab, Logout being reachable during an emergency, the
`<alpha-value>` bug that made every opacity modifier a no-op, and the six files
still on the removed palette. See the
[Phase 1 outcome](AUDIT.md#phase-1-outcome-the-emergency-flow-was-broken-end-to-end).

**Closed in Phase 2**: `.tap` was purged because no component referenced it, the
app bar and tab bar were translucent, five colour tokens sat below 4.5:1 — two of
them only on their own badge tint — and the camera-error bar used `text-text` on
`bg-danger/90` at 3.18:1. Contrast is now asserted by
`backend/tests/test_contrast.py` rather than eyeballed. See the
[design system](frontend/design-system.md#contrast-is-measured-against-the-background-that-actually-renders).

**Still open, and not fixed by either phase**: the five legacy pages hardcode
English, and `SimulationNotice` is still dead code next to the `EngineDisclosure`
that replaced its job inline.
