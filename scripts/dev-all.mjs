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

const children = new Set();
let stopping = false;

function run(label, cmd, args, cwd) {
  const child = spawn(cmd, args, { cwd, shell: isWin });
  children.add(child);
  const prefix = `[${label}] `;
  child.stdout?.on("data", (d) => process.stdout.write(prefix + d));
  child.stderr?.on("data", (d) => process.stderr.write(prefix + d));
  child.on("exit", (code, signal) => {
    children.delete(child);
    const why = signal ? `signal ${signal}` : `code ${code}`;
    console.log(`\n[${label}] exited with ${why}`);
    shutdown(code ?? 0);
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
    run("frontend", isWin ? "npm.cmd" : "npm", ["run", "dev"], frontendDir);
  })
  .catch((err) => {
    console.error(`[build] failed: ${err.message}`);
    process.exit(1);
  });

async function buildIfNeeded() {
  if (existsSync(path.join(frontendDir, "dist", "index.html"))) return;
  console.log("[build] Frontend not built yet - building once (~5s)...");
  await new Promise((resolve, reject) => {
    const child = spawn(isWin ? "npm.cmd" : "npm", ["run", "build"], {
      cwd: frontendDir,
      shell: isWin,
    });
    child.stdout?.on("data", (d) => process.stdout.write("[build] " + d));
    child.stderr?.on("data", (d) => process.stderr.write("[build] " + d));
    child.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`npm run build exited ${code}`))));
  });
}
