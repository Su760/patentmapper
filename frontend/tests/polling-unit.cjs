// Deterministic Node tests of the real TypeScript poller; no browser/network used.
const { test, expect } = require("@playwright/test");
const ts = require("typescript");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
function harness(
  config = { intervalMs: 3, timeoutMs: 15, maxRequests: 3, maxErrors: 2 },
) {
  let now = 0,
    id = 0;
  const timers = new Map();
  const setTimeout = (fn, delay) => {
    timers.set(++id, { at: now + delay, fn });
    return id;
  };
  const clearTimeout = (id) => timers.delete(id);
  const exports = {};
  const code = ts.transpileModule(
    fs.readFileSync(path.join(__dirname, "../src/lib/poll-job.ts"), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS } },
  ).outputText;
  vm.runInNewContext(code, {
    exports,
    require: () => ({ RESULTS_POLLING: config }),
    setTimeout,
    clearTimeout,
    AbortController,
    Error,
  });
  const flush = async () => {
    for (let i = 0; i < 20; i++) await Promise.resolve();
  };
  const tick = async (ms) => {
    const end = now + ms;
    await flush();
    for (;;) {
      const next = [...timers].sort((a, b) => a[1].at - b[1].at)[0];
      if (!next || next[1].at > end) break;
      now = next[1].at;
      timers.delete(next[0]);
      next[1].fn();
      await flush();
    }
    now = end;
    await flush();
  };
  return { start: exports.startJobPolling, tick, flush, timers };
}
test("poller never overlaps; cleanup aborts current request and removes timers", async () => {
  const h = harness();
  let calls = 0,
    signal,
    resolve,
    seen = 0;
  const stop = h.start({
    read: (s) => {
      calls++;
      signal = s;
      return new Promise((r) => (resolve = r));
    },
    onStatus: () => seen++,
    onError: () => {},
  });
  await h.tick(10);
  expect(calls).toBe(1);
  stop();
  expect(signal.aborted).toBe(true);
  resolve({ status: "processing" });
  await h.tick(100);
  expect(seen).toBe(0);
  expect(calls).toBe(1);
  expect(h.timers.size).toBe(0);
});
test("poller is bounded even for endlessly processing jobs", async () => {
  const h = harness();
  let reads = 0;
  const errors = [];
  h.start({
    read: async () => {
      reads++;
      return { status: "processing" };
    },
    onStatus: () => {},
    onError: (...e) => errors.push(e),
  });
  await h.tick(100);
  expect(reads).toBe(3);
  expect(errors.at(-1)[1]).toBe(true);
  expect(h.timers.size).toBe(0);
});
test("poll timeouts and transient failures stop at the configured error bound", async () => {
  const h = harness();
  let reads = 0;
  const errors = [];
  h.start({
    read: (signal) => {
      reads++;
      return new Promise((_, reject) =>
        signal.addEventListener("abort", () => reject(new Error("abort"))),
      );
    },
    onStatus: () => {},
    onError: (...e) => errors.push(e),
  });
  await h.tick(100);
  expect(reads).toBe(2);
  expect(errors[0]).toEqual(["The request timed out.", false, false]);
  expect(errors[1][1]).toBe(true);
  expect(h.timers.size).toBe(0);
});
test("authorization failures stop immediately; transient recovery clears the failure streak", async () => {
  for (const status of [401, 403, 404]) {
    const h = harness();
    let reads = 0;
    const errors = [];
    h.start({
      read: async () => {
        reads++;
        throw Object.assign(new Error("denied"), { status });
      },
      onStatus: () => {},
      onError: (...e) => errors.push(e),
    });
    await h.tick(100);
    expect(reads).toBe(1);
    expect(errors).toEqual([["denied", true, true]]);
  }
  const h = harness();
  let reads = 0;
  const seen = [];
  h.start({
    read: async () => {
      if (++reads === 1) throw new Error("outage");
      return { status: reads === 2 ? "processing" : "completed" };
    },
    onStatus: (s) => seen.push(s.status),
    onError: () => {},
  });
  await h.tick(100);
  expect(seen).toEqual(["processing", "completed"]);
  expect(h.timers.size).toBe(0);
});
test("a stalled non-abortable SDK wait still reaches the polling deadline", async () => {
  const h = harness({
    intervalMs: 3,
    timeoutMs: 5,
    maxRequests: 3,
    maxErrors: 1,
  });
  const errors = [];
  let late,
    seen = 0;
  h.start({
    read: () => new Promise((resolve) => (late = resolve)),
    onStatus: () => seen++,
    onError: (...e) => errors.push(e),
  });
  await h.tick(40);
  expect(errors).toEqual([["The request timed out.", true, false]]);
  late({ status: "completed" });
  await h.flush();
  expect(seen).toBe(0);
  expect(h.timers.size).toBe(0);
});
test("cancelling a session wait prevents late status, claims and paid API calls", async () => {
  let resolveSession;
  let fetches = 0;
  const exports = {};
  const session = new Promise((resolve) => (resolveSession = resolve));
  const code = ts.transpileModule(
    fs.readFileSync(path.join(__dirname, "../src/lib/api.ts"), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS } },
  ).outputText;
  vm.runInNewContext(code, {
    exports,
    require: (name) =>
      name.includes("supabase")
        ? { createClient: () => ({ auth: { getSession: () => session } }) }
        : { DEMO_JOB_ID: "demo" },
    process: { env: {} },
    fetch: () => {
      fetches++;
    },
    Error,
  });
  for (const start of [
    (s) => exports.getJobStatus("job", s),
    (s) => exports.getClaimsAnalysis("job", s),
    (s) => exports.analyzeClaimsRequest("job", s),
    (s) => exports.ideateWhiteSpace("job", "Gap", "Description", s),
  ]) {
    const controller = new AbortController();
    const pending = start(controller.signal);
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  }
  resolveSession({
    data: { session: { access_token: "fixture" } },
    error: null,
  });
  for (let i = 0; i < 10; i++) await Promise.resolve();
  expect(fetches).toBe(0);
});
