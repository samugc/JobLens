#!/usr/bin/env node
/**
 * Capture the screenshots used by the public README through Chrome DevTools.
 *
 * Prerequisite: start the demo first, for example:
 *   python3 -m joblens_public --port 8765
 * Then:
 *   node scripts/capture_screenshots.mjs
 *
 * The script only talks to the local demo. It launches a temporary headless
 * Chrome profile, sets exact viewport metrics, and saves real app screenshots.
 * No result is mocked: every report screenshot comes from /api/analyze.
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const BASE_URL = process.env.JOBLENS_URL || "http://127.0.0.1:8765/";
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const OUTPUT_DIR = path.join(ROOT, "docs", "screenshots");
const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/google-chrome",
  "/usr/bin/google-chrome-stable",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
].filter(Boolean);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function findChrome() {
  const found = CHROME_CANDIDATES.find((candidate) => fs.existsSync(candidate));
  if (!found) {
    throw new Error("Chrome not found. Set CHROME_PATH to a Chrome/Chromium binary.");
  }
  return found;
}

async function waitForHttp(url, timeoutMs = 10_000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url);
      if (response.ok) return response;
    } catch {
      // Chrome is still starting.
    }
    await sleep(100);
  }
  throw new Error(`Timed out waiting for ${url}`);
}

function connect(webSocketUrl) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(webSocketUrl);
    const pending = new Map();
    let nextId = 1;
    const events = new Map();

    socket.addEventListener("open", () => {
      resolve({
        send(method, params = {}) {
          return new Promise((res, rej) => {
            const id = nextId++;
            pending.set(id, { resolve: res, reject: rej });
            socket.send(JSON.stringify({ id, method, params }));
          });
        },
        waitForEvent(method, timeoutMs = 15_000) {
          return new Promise((res, rej) => {
            const timer = setTimeout(() => rej(new Error(`Timed out waiting for ${method}`)), timeoutMs);
            const list = events.get(method) || [];
            list.push((params) => {
              clearTimeout(timer);
              res(params);
            });
            events.set(method, list);
          });
        },
        close() {
          socket.close();
        },
      });
    });

    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (message.id && pending.has(message.id)) {
        const { resolve: res, reject: rej } = pending.get(message.id);
        pending.delete(message.id);
        if (message.error) rej(new Error(message.error.message));
        else res(message.result);
        return;
      }
      const listeners = events.get(message.method);
      if (listeners?.length) {
        const listener = listeners.shift();
        listener(message.params);
      }
    });

    socket.addEventListener("error", () => reject(new Error("Chrome DevTools WebSocket failed")));
  });
}

async function waitForFunction(client, expression, timeoutMs = 15_000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const result = await client.send("Runtime.evaluate", {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    if (result.result?.value) return;
    await sleep(100);
  }
  throw new Error(`Timed out waiting for: ${expression}`);
}

async function capture(
  client,
  file,
  width,
  height,
  deviceScaleFactor,
  mobile,
  url,
  scrollToReport,
  scrollSelector = "#results",
) {
  await client.send("Emulation.setDeviceMetricsOverride", {
    width,
    height,
    deviceScaleFactor,
    mobile,
    screenWidth: width,
    screenHeight: height,
  });
  await client.send("Page.navigate", { url });
  await waitForFunction(
    client,
    "document.readyState === 'complete' && document.querySelectorAll('#candidate option').length > 0",
  );
  if (scrollToReport) {
    await waitForFunction(
      client,
      "!document.getElementById('report').hidden && document.querySelectorAll('#required-list .skill-card').length > 0 && !document.getElementById('analyze').disabled",
    );
    await client.send("Runtime.evaluate", {
      expression: `(() => { const el = document.querySelector(${JSON.stringify(scrollSelector)}); const top = el.getBoundingClientRect().top + window.scrollY - 18; document.documentElement.scrollTop = top; document.body.scrollTop = top; })()`,
    });
  } else {
    await client.send("Runtime.evaluate", { expression: "window.scrollTo(0, 0)" });
  }
  await sleep(scrollToReport ? 900 : 250);
  const { data } = await client.send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: false,
  });
  fs.writeFileSync(path.join(OUTPUT_DIR, file), Buffer.from(data, "base64"));
  console.log(`Saved ${file} (${width}x${height} CSS px)`);
}

async function main() {
  if (!BASE_URL.endsWith("/")) throw new Error("JOBLENS_URL must end with /");
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  const chromePath = findChrome();
  const port = 9333 + Math.floor(Math.random() * 300);
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "joblens-cdp-"));
  const chrome = spawn(chromePath, [
    "--headless=new",
    "--disable-gpu",
    "--hide-scrollbars",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-networking",
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    "about:blank",
  ], { stdio: "ignore" });

  let client;
  try {
    await waitForHttp(`http://127.0.0.1:${port}/json/version`);
    const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
    const page = targets.find((target) => target.type === "page");
    if (!page) throw new Error("Chrome did not expose a page target");
    client = await connect(page.webSocketDebuggerUrl);
    await client.send("Page.enable");
    await client.send("Runtime.enable");

    await capture(
      client,
      "overview-desktop.png",
      1440,
      1000,
      1,
      false,
      `${BASE_URL}?candidate=alex-rivera&job=junior-ai-engineer-aster`,
      false,
    );
    await capture(
      client,
      "report-desktop.png",
      1440,
      1600,
      1,
      false,
      `${BASE_URL}?candidate=alex-rivera&job=junior-ai-engineer-aster&analyze=1&view=report`,
      true,
    );
    await capture(
      client,
      "review-desktop.png",
      1440,
      1000,
      1,
      false,
      `${BASE_URL}?candidate=alex-rivera&job=junior-ai-engineer-aster&analyze=1&view=report`,
      true,
      '[aria-labelledby="review-heading"]',
    );
    await capture(
      client,
      "overview-mobile.png",
      390,
      844,
      2,
      true,
      `${BASE_URL}?candidate=jordan-lee&job=data-analyst-harbor`,
      false,
    );
    await capture(
      client,
      "report-mobile.png",
      390,
      900,
      2,
      true,
      `${BASE_URL}?candidate=alex-rivera&job=junior-ai-engineer-aster&analyze=1&view=report`,
      true,
    );
  } finally {
    client?.close();
    chrome.kill("SIGTERM");
    await sleep(300);
    fs.rmSync(profile, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
