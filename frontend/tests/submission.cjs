const { test, expect } = require("@playwright/test");
const fs = require("node:fs"),
  vm = require("node:vm"),
  ts = require("typescript");
function load(storage = new Map()) {
  const module = { exports: {} };
  let ids = 0;
  const code = ts.transpileModule(
    fs.readFileSync("src/lib/submission.ts", "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS } },
  ).outputText;
  vm.runInNewContext(code, {
    module,
    exports: module.exports,
    crypto: { randomUUID: () => `key-${++ids}` },
    sessionStorage: {
      getItem: (k) => storage.get(k) || null,
      setItem: (k, v) => storage.set(k, v),
      removeItem: (k) => storage.delete(k),
    },
    Map,
    JSON,
  });
  return module.exports;
}
test("uncertain submission retains owner-scoped key across reload; changes get new keys", () => {
  const storage = new Map(),
    a = load(storage);
  const first = a.prepareSubmission("A", " Original invention ", "us");
  expect(a.prepareSubmission("A", "Original invention", "us").key).toBe(
    first.key,
  );
  expect(
    load(storage).prepareSubmission("A", "Original invention", "us").key,
  ).toBe(first.key);
  expect(a.prepareSubmission("B", "Original invention", "us").key).not.toBe(
    first.key,
  );
  expect(a.prepareSubmission("A", "Changed invention", "us").key).not.toBe(
    first.key,
  );
  const latest = a.pendingSubmission("A");
  a.confirmSubmission("A", first.key);
  expect(a.pendingSubmission("A").key).toBe(latest.key);
  a.confirmSubmission("A", latest.key);
  expect(a.pendingSubmission("A")).toBeNull();
  expect(a.prepareSubmission("A", "Changed invention", "us").key).not.toBe(
    latest.key,
  );
});
