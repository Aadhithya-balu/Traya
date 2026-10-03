import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const backendDir = path.join(root, "backend");
const frontendDir = path.join(root, "frontend");
const isWin = process.platform === "win32";

const python = isWin
  ? path.join(backendDir, ".venv", "Scripts", "python.exe")
  : path.join(backendDir, ".venv", "bin", "python");

const vite = path.join(frontendDir, "node_modules", "vite", "bin", "vite.js");
const tsc = path.join(frontendDir, "node_modules", "typescript", "bin", "tsc");

const children = new Set();
let stopping = false;

function prefixLines(label, stream) {
  const prefix = `[${label}] `;
  stream?.on("data", (d) => process.stdout.write(prefix + d));
}

function run(label, cmd, args, cwd) {
  const child = spawn(cmd, args, { cwd, shell: false, windowsHide: true });
  children.add(child);
  prefixLines(label, child.stdout);
  prefixLines(label, child.stderr);
  child.on("exit", (code, signal) => {
    children.delete(child);
    if (stopping) return;
    const why = signal ? `signal ${signal}` : `code ${code}`;
    console.log(`\n[${label}] exited with ${why}`);
    shutdown(code ?? 1);
  });
  child.on("error", (err) => {
    console.error(`[${label}] failed to start: ${err.message}`);
    shutdown(1);
  });
  return child;
}

function shutdown(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    if (child.exitCode !== null || child.signalCode !== null) continue;
    try {
      if (isWin) {
        spawn("taskkill", ["/pid", String(child.pid), "/T", "/F"], { windowsHide: true });
      } else {
        child.kill("SIGTERM");
      }
    } catch {
      /* ignore */
    }
  }
  setTimeout(() => process.exit(code), 300);
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

console.log("Starting TRAYA dev servers...");
console.log("  App        -> http://localhost:5173   (open this in your browser)");
console.log(`  Backend    -> http://localhost:8000  (${python})`);
console.log("  Built app  -> http://localhost:8000   (served by FastAPI when frontend/dist is built)");
console.log("Press Ctrl+C to stop both.\n");

buildIfNeeded()
  .then(() => {
    run("backend", python, ["-m", "uvicorn", "app.main:app", "--port", "8000"], backendDir);
    run("frontend", process.execPath, [vite], frontendDir);
  })
  .catch((err) => {
    console.error(`[build] failed: ${err.message}`);
    process.exit(1);
  });

async function runStep(label, cmd, args, cwd) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { cwd, shell: false, windowsHide: true });
    prefixLines("build", child.stdout);
    prefixLines("build", child.stderr);
    child.on("error", reject);
    child.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`${label} exited ${code}`))));
  });
}

async function buildIfNeeded() {
  if (existsSync(path.join(frontendDir, "dist", "index.html"))) return;
  if (!existsSync(vite) || !existsSync(tsc)) {
    throw new Error("frontend dependencies are missing - run `npm install` in frontend/");
  }
  console.log("[build] Frontend not built yet - building once...");
  await runStep("tsc", process.execPath, [tsc, "--noEmit"], frontendDir);
  await runStep("vite build", process.execPath, [vite, "build"], frontendDir);
}
