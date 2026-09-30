#!/usr/bin/env node
/**
 * Documentation coverage and integrity check.
 *
 * Documentation rots silently. This script makes rot fail loudly:
 *
 *   1. COVERAGE  - every router endpoint, model, migration, repository method,
 *                  service function, settings field, permission, page, UI
 *                  component, icon, API client method and exported TS type
 *                  must be mentioned by name in its owning doc page.
 *   2. LINKS     - every relative markdown link inside docs/ must resolve.
 *   3. HEADINGS  - every docs page must have exactly one H1 and an H2, and must
 *                  start with a breadcrumb back to docs/README.md.
 *
 * Run with `npm run docs:check` from the repository root.
 * Exits 0 when documentation is complete, 1 otherwise.
 */

import { readFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { join, dirname, relative, extname, resolve, basename } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DOCS = join(ROOT, "docs");
const BACKEND = join(ROOT, "backend");
const FRONTEND = join(ROOT, "frontend");

const read = (p) => readFileSync(p, "utf8");
const failures = [];
const notes = [];

/** Recursively list files under `dir` matching `exts`, skipping noise dirs. */
function walk(dir, exts, skip = new Set(["__pycache__", ".venv", "node_modules", "dist", ".git"])) {
  if (!existsSync(dir)) return [];
  const out = [];
  for (const entry of readdirSync(dir)) {
    if (skip.has(entry)) continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full, exts, skip));
    else if (exts.includes(extname(full))) out.push(full);
  }
  return out;
}

/** Deduplicate while preserving order. */
const uniq = (arr) => [...new Set(arr)];

/**
 * Register a doc page as a coverage target.
 * `extract` returns the identifiers that must appear in that page.
 */
function cover(name, docRelPath, extract) {
  const docAbs = join(DOCS, docRelPath);
  if (!existsSync(docAbs)) {
    failures.push(`MISSING DOC   ${name}: docs/${docRelPath} does not exist`);
    return;
  }
  const body = read(docAbs);
  const identifiers = uniq(extract()).filter(Boolean);
  const missing = identifiers.filter((id) => !body.includes(String(id)));
  if (missing.length) {
    failures.push(
      `UNCOVERED     ${name}: ${missing.length} identifier(s) absent from docs/${docRelPath}\n` +
        missing.map((m) => `                 - ${m}`).join("\n"),
    );
  } else {
    notes.push(`  ok  ${name.padEnd(26)} ${identifiers.length} identifier(s) -> docs/${docRelPath}`);
  }
}

// ---------------------------------------------------------------------------
// 1. BACKEND API ROUTERS
// ---------------------------------------------------------------------------

function routerPrefix(source) {
  const m = source.match(/APIRouter\(([\s\S]*?)\)\s*$/m) || source.match(/APIRouter\(([\s\S]*?)\)/);
  if (!m) return "";
  const p = m[1].match(/prefix\s*=\s*["']([^"']+)["']/);
  return p ? p[1] : "";
}

const ROUTER_DOC = "backend/api.md";
const routerFiles = walk(join(BACKEND, "app", "api"), [".py"]);

cover("backend routers", ROUTER_DOC, () => {
  const endpoints = [];
  for (const file of routerFiles) {
    if (file.endsWith("__init__.py")) continue;
    const src = read(file);
    const prefix = routerPrefix(src);
    const re = /@router\.(get|post|put|patch|delete)\(\s*["']([^"']*)["']/g;
    let m;
    while ((m = re.exec(src))) endpoints.push(`${prefix}${m[2] || ""}`.replace(/\/+$/, "") || prefix);
  }
  return endpoints;
});

cover("backend router modules", ROUTER_DOC, () =>
  routerFiles.filter((f) => !f.endsWith("__init__.py")).map((f) => `app/api/${basename(f)}`),
);

// ---------------------------------------------------------------------------
// 2. MODELS + MIGRATIONS
// ---------------------------------------------------------------------------

const entities = read(join(BACKEND, "app", "models", "entities.py"));
cover("orm models", "backend/data-model.md", () => {
  const classes = [...entities.matchAll(/^class\s+(\w+)\s*\(/gm)].map((m) => m[1]);
  const tables = [...entities.matchAll(/__tablename__\s*=\s*["'](\w+)["']/g)].map((m) => m[1]);
  return [...classes, ...tables];
});

const migrationFiles = walk(join(BACKEND, "migrations", "versions"), [".py"]);
cover("migrations", "backend/data-model.md", () =>
  migrationFiles.map((f) => basename(f).split("_")[0]),
);

// ---------------------------------------------------------------------------
// 3. REPOSITORIES
// ---------------------------------------------------------------------------

const repoFiles = walk(join(BACKEND, "app", "repositories"), [".py"]).filter(
  (f) => !f.endsWith("__init__.py"),
);

/**
 * Section-aware coverage: a method counts as documented only if it appears in
 * the markdown section whose heading names its class. This keeps generic names
 * like `get`, `list` and `count` from passing on a coincidental mention
 * elsewhere in the page.
 */
function coverBySection(name, docRelPath, groups) {
  const docAbs = join(DOCS, docRelPath);
  if (!existsSync(docAbs)) {
    failures.push(`MISSING DOC   ${name}: docs/${docRelPath} does not exist`);
    return;
  }
  const body = read(docAbs);
  // Section boundaries are H1/H2 only, so a class's own H3 subsections count as
  // part of that class's section.
  const chunks = body.split(/^(#{1,2}\s+.*)$/m);
  const sections = [];
  for (let i = 1; i < chunks.length; i += 2) {
    sections.push({ heading: chunks[i], text: chunks[i + 1] ?? "" });
  }
  const headings = uniq(groups.map((g) => g.key));

  const missingHeadings = headings.filter((h) => !sections.some((s) => s.heading.includes(h)));
  if (missingHeadings.length) {
    failures.push(
      `UNCOVERED     ${name}: no section heading for ${missingHeadings.join(", ")} in docs/${docRelPath}`,
    );
    return;
  }

  const missing = [];
  for (const group of groups) {
    // Every section whose heading mentions the class name, so a class split
    // across two sections is still fully searched.
    const owned = sections
      .filter((s) => s.heading.includes(group.key))
      .map((s) => s.text)
      .join("\n");
    for (const member of uniq(group.members)) {
      if (!owned.includes(member)) missing.push(`${group.key}.${member}`);
    }
  }
  if (missing.length) {
    failures.push(
      `UNCOVERED     ${name}: ${missing.length} identifier(s) absent from docs/${docRelPath}\n` +
        missing.map((m) => `                 - ${m}`).join("\n"),
    );
  } else {
    const total = uniq(groups.flatMap((g) => g.members)).length;
    notes.push(`  ok  ${name.padEnd(26)} ${total} identifier(s) -> docs/${docRelPath}`);
  }
}

/**
 * Every top-level `def` (public only) plus every class and its public methods.
 * Classes are delimited properly: a method belongs to the nearest preceding
 * `class`, not to whichever class happens to be first in the file.
 */
function pythonSurface(src) {
  const lines = src.split(/\r?\n/);
  const moduleFns = [];
  const classes = [];
  let current = null;
  for (const line of lines) {
    const fn = line.match(/^def\s+(\w+)\s*\(/);
    if (fn) {
      if (!fn[1].startsWith("_")) moduleFns.push(fn[1]);
      continue;
    }
    const cls = line.match(/^class\s+(\w+)\b/);
    if (cls) {
      current = { name: cls[1], methods: [] };
      classes.push(current);
      continue;
    }
    const method = line.match(/^    def\s+(\w+)\s*\(/);
    if (method && current && !method[1].startsWith("_")) {
      current.methods.push(method[1]);
    }
  }
  return { moduleFns, classes };
}

coverBySection(
  "repositories",
  "backend/repositories.md",
  repoFiles.map((file) => {
    const { moduleFns, classes } = pythonSurface(read(file));
    // A repository module is named after its `*Repository` class; supporting
    // dataclasses in the same file (e.g. EnrolledProfile) belong to that section.
    const primary = classes.find((c) => /Repository$/.test(c.name)) ?? classes[0];
    return {
      key: primary?.name,
      members: [
        ...moduleFns,
        ...classes.map((c) => c.name),
        ...primary?.methods ?? [],
      ],
    };
  }),
);

// ---------------------------------------------------------------------------
// 4. SERVICES
// ---------------------------------------------------------------------------

const serviceFiles = walk(join(BACKEND, "app", "services"), [".py"]).filter(
  (f) => !f.endsWith("__init__.py"),
);

coverBySection(
  "backend services",
  "backend/services.md",
  serviceFiles.map((file) => {
    const { moduleFns, classes } = pythonSurface(read(file));
    const key = relative(BACKEND, file).replace(/\\/g, "/").replace(/\.py$/, "");
    // Members are unscoped: the section heading already names the module, and
    // dotted `Class.method` strings would need verbatim prose to match.
    return {
      key,
      members: [...moduleFns, ...classes.flatMap((c) => [c.name, ...c.methods])],
    };
  }),
);

// ---------------------------------------------------------------------------
// 5. SETTINGS + PERMISSIONS
// ---------------------------------------------------------------------------

cover("settings fields", "backend/configuration.md", () => {
  const src = read(join(BACKEND, "app", "config", "settings.py"));
  return [...src.matchAll(/^\s{4}([A-Z][A-Z0-9_]+)\s*:/gm)].map((m) => m[1]);
});

/** Extract the body of a top-level `NAME: type = { ... }` or `NAME = { ... }` literal. */
function dictBody(src, name) {
  const start = src.search(new RegExp(`^${name}\\b[^=\\n]*=`, "m"));
  if (start < 0) return null;
  const open = src.indexOf("{", start);
  if (open < 0) return null;
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}") {
      depth--;
      if (depth === 0) return src.slice(open + 1, i);
    }
  }
  return null;
}

const dictKeys = (src, name) => {
  const body = dictBody(src, name);
  if (!body) return [];
  return uniq([...body.matchAll(/["'](\w+)["']\s*:/g)].map((m) => m[1]));
};

cover("permissions", "backend/security.md", () => {
  const src = read(join(BACKEND, "app", "security", "permissions.py"));
  return [
    ...dictKeys(src, "PERMISSION_DESCRIPTIONS"),
    ...dictKeys(src, "ROLE_PERMISSIONS"),
  ];
});

cover("roles", "backend/security.md", () =>
  dictKeys(read(join(BACKEND, "app", "security", "auth.py")), "ROLE_DESCRIPTIONS"),
);

// ---------------------------------------------------------------------------
// 6. FRONTEND PAGES + COMPONENTS + ICONS
// ---------------------------------------------------------------------------

const pageFiles = walk(join(FRONTEND, "src", "pages"), [".tsx"]);
cover("frontend pages", "frontend/pages.md", () => {
  const names = [];
  for (const file of pageFiles) {
    const src = read(file);
    names.push(`pages/${basename(file)}`);
    for (const m of src.matchAll(/^export function\s+(\w+)/gm)) names.push(m[1]);
  }
  return names;
});

const componentFiles = walk(join(FRONTEND, "src", "components"), [".tsx"]);
cover("frontend components", "frontend/components.md", () => {
  const names = [];
  for (const file of componentFiles) {
    const src = read(file);
    names.push(`components/${basename(file)}`);
    for (const m of src.matchAll(/^export function\s+(\w+)/gm)) names.push(m[1]);
  }
  return names;
});

cover("frontend icons", "frontend/components.md", () => {
  const src = read(join(FRONTEND, "src", "components", "icons.tsx"));
  const fns = [...src.matchAll(/^export function\s+(\w+Icon)\b/gm)].map((m) => m[1]);
  const consts = [...src.matchAll(/^export const\s+(\w+Icon)\b/gm)].map((m) => m[1]);
  return [...fns, ...consts];
});

// ---------------------------------------------------------------------------
// 7. CONTEXTS, HOOKS, API CLIENT, TYPES
// ---------------------------------------------------------------------------

cover("frontend contexts", "frontend/state-and-data.md", () => {
  const names = [];
  for (const file of walk(join(FRONTEND, "src", "context"), [".tsx"])) {
    const src = read(file);
    names.push(`context/${basename(file)}`);
    for (const m of src.matchAll(/^export function\s+(\w+)/gm)) names.push(m[1]);
  }
  return names;
});

cover("frontend hooks", "frontend/state-and-data.md", () => {
  const names = [];
  for (const file of walk(join(FRONTEND, "src", "hooks"), [".ts"])) {
    const src = read(file);
    names.push(`hooks/${basename(file)}`);
    for (const m of src.matchAll(/^export function\s+(\w+)/gm)) names.push(m[1]);
  }
  return names;
});

const clientSrc = read(join(FRONTEND, "src", "api", "client.ts"));
cover("api client methods", "frontend/state-and-data.md", () =>
  [...clientSrc.matchAll(/^  (\w+):\s*(?:\(|request)/gm)].map((m) => m[1]),
);

cover("api types", "frontend/state-and-data.md", () =>
  [...read(join(FRONTEND, "src", "api", "types.ts")).matchAll(/^export interface\s+(\w+)/gm)].map(
    (m) => m[1],
  ),
);

// ---------------------------------------------------------------------------
// 8. ROUTES
// ---------------------------------------------------------------------------

cover("frontend routes", "frontend/routing.md", () => {
  const src = read(join(FRONTEND, "src", "App.tsx"));
  return [...src.matchAll(/<Route\s+path="([^"]*)"/g)].map((m) => m[1]);
});

// ---------------------------------------------------------------------------
// 9. DESIGN SYSTEM
// ---------------------------------------------------------------------------

cover("design tokens", "frontend/design-system.md", () => {
  const css = read(join(FRONTEND, "src", "index.css"));
  return uniq([...css.matchAll(/^\s*(--c-[\w-]+)\s*:/gm)].map((m) => m[1]));
});

cover("component classes", "frontend/design-system.md", () =>
  uniq([...read(join(FRONTEND, "src", "index.css")).matchAll(/^\s{2}\.([\w-]+)\s*\{/gm)].map((m) => m[1])),
);

cover("i18n namespaces", "frontend/design-system.md", () => {
  const src = read(join(FRONTEND, "src", "i18n", "strings.ts"));
  const en = src.match(/export const en\s*=\s*\{([\s\S]*?)\n\};/);
  if (!en) return [];
  // Keys are flat and namespaced by a dotted prefix: "nav.home", "nav.more".
  return uniq([...en[1].matchAll(/["']([a-z0-9_]+)\./g)].map((m) => m[1]));
});

// ---------------------------------------------------------------------------
// 10. STRUCTURAL CHECKS: LINKS + HEADINGS
// ---------------------------------------------------------------------------

const docFiles = walk(DOCS, [".md"]);

for (const file of docFiles) {
  const rel = relative(ROOT, file).replace(/\\/g, "/");
  const src = read(file);
  const name = basename(file);

  const h1 = (src.match(/^# .+$/gm) || []).length;
  const h2 = (src.match(/^## .+$/gm) || []).length;
  if (h1 !== 1) failures.push(`STRUCTURE     ${rel}: expected exactly 1 H1 heading, found ${h1}`);
  if (h2 < 1) failures.push(`STRUCTURE     ${rel}: needs at least one H2 section`);

  const links = [...src.matchAll(/\]\(([^)\s]+)\)/g)].map((m) => m[1]);
  const resolvesTo = (target) => {
    const clean = target.split("#")[0];
    return clean ? resolve(dirname(file), clean) : null;
  };

  // Breadcrumb: the page must link back to the docs index. Resolved rather than
  // string-matched, so `../README.md` and `docs/README.md` both count.
  if (name !== "README.md" && !links.some((t) => resolvesTo(t) === join(DOCS, "README.md"))) {
    failures.push(`STRUCTURE     ${rel}: no link back to docs/README.md`);
  }

  for (const target of links) {
    if (/^(https?:|mailto:|#)/.test(target)) continue;
    const abs = resolvesTo(target);
    if (abs && !existsSync(abs)) {
      failures.push(`BROKEN LINK   ${rel}: ${target}`);
    }
  }
}

// README at the repo root must point into docs/.
const rootReadme = read(join(ROOT, "README.md"));
if (!/docs\/README\.md/.test(rootReadme)) {
  failures.push("STRUCTURE     README.md: does not link to docs/README.md");
}

// ---------------------------------------------------------------------------
// REPORT
// ---------------------------------------------------------------------------

console.log("TRAYA documentation check\n");
for (const n of notes) console.log(n);
console.log("");

if (failures.length) {
  for (const f of failures) console.error(f);
  console.error(`\n${failures.length} documentation problem(s).`);
  process.exit(1);
}

console.log(`All checks passed across ${docFiles.length} docs page(s).`);
