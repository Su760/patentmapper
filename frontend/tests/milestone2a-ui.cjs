const { test, expect } = require("@playwright/test");
const job = "10000000-0000-0000-0000-000000000001";
const owner = "00000000-0000-0000-0000-000000000001";
const claim = {
  patent_id: "US1",
  title: "Saved claim title",
  likely_claims: ["Cached wording"],
  overlap_level: "low",
  overlap_explanation: "Saved overlap",
  differentiators: "Saved differences",
};
async function setup(page, context, overrides = {}) {
  const host = new URL(
    process.env.NEXT_PUBLIC_SUPABASE_URL || "https://example.supabase.co",
  ).hostname.split(".")[0];
  await context.addCookies([
    {
      name: `sb-${host}-auth-token`,
      value: encodeURIComponent(
        JSON.stringify({
          access_token: "fixture-token",
          refresh_token: "fixture-refresh",
          expires_at: Math.floor(Date.now() / 1000) + 3600,
          expires_in: 3600,
          token_type: "bearer",
          user: {
            id: owner,
            email: "fixture@example.test",
            aud: "authenticated",
          },
        }),
      ),
      domain: "127.0.0.1",
      path: "/",
    },
  ]);
  const calls = { get: 0, post: 0, status: 0 };
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("analyze-claims")) {
      expect(route.request().headers().authorization).toBe(
        "Bearer fixture-token",
      );
      calls[route.request().method() === "POST" ? "post" : "get"]++;
      return route.fulfill({ json: { claims: [claim] } });
    }
    if (path.endsWith(job)) {
      calls.status++;
      return route.fulfill({ json: { job_id: job, status: "completed" } });
    }
    return route.fulfill({
      status: 503,
      json: { detail: "Test usage unavailable" },
    });
  });
  await page.route("**/rest/v1/**", (route) =>
    route.fulfill({
      json: route.request().url().includes("search_results")
        ? {
            clusters: [],
            citation_links: [],
            white_space_analysis: "Separate saved gap text",
            final_report: "# Exact saved report\n\nReport body α",
            retrieval_outcome: "partial",
            coverage_warnings: ["Partial coverage fixture"],
            ...overrides,
          }
        : {
            invention_idea: "Synthetic saved invention",
            created_at: "2026-01-01T00:00:00Z",
          },
    }),
  );
  return calls;
}
test("saved report and cached claims reopen without paid work; regeneration is explicit", async ({
  page,
  context,
}) => {
  const calls = await setup(page, context);
  await page.goto(`/results/${job}`);
  const brief = page
    .locator("section")
    .filter({
      has: page.getByRole("heading", { name: "Full analysis brief" }),
    });
  await expect(brief).toContainText("Exact saved report");
  await expect(brief).not.toContainText("Separate saved gap text");
  await expect(page.getByText("Partial coverage fixture")).toBeVisible();
  await expect(page.getByText("Saved claim title")).toBeVisible();
  expect(calls.post).toBe(0);
  expect(calls.get).toBe(1);
  await page.reload();
  await expect(page.getByText("Saved claim title")).toBeVisible();
  expect(calls.post).toBe(0);
  expect(calls.get).toBe(2);
  await expect(page.getByText(/Uses 1 claims allowance/)).toBeVisible();
  await page.getByRole("button", { name: "Regenerate claims" }).click();
  await expect.poll(() => calls.post).toBe(1);
});
test("legacy missing report is honest and never regenerated", async ({
  page,
  context,
}) => {
  const calls = await setup(page, context, { final_report: null });
  await page.goto(`/results/${job}`);
  await expect(
    page.getByText(
      "No saved full report is available for this older analysis.",
    ),
  ).toBeVisible();
  expect(calls.post).toBe(0);
});
test("initial transient errors are visible; authorization errors stop polling", async ({
  page,
  context,
}) => {
  await setup(page, context);
  let polls = 0;
  await page.route(`**/api/jobs/${job}`, (route) => {
    polls++;
    return route.fulfill({
      status: polls === 1 ? 503 : 401,
      json: { detail: "Synthetic status outage" },
    });
  });
  await page.goto(`/results/${job}`);
  await expect(
    page.locator('p[role="alert"]').filter({ hasText: /Status unavailable/ }),
  ).toBeVisible();
  await expect(page.getByText(/session is missing or expired/)).toBeVisible();
  const stopped = polls;
  await page.waitForTimeout(3500);
  expect(polls).toBe(stopped);
});
test("progress follows persisted stages and transient polling errors recover visibly", async ({
  page,
  context,
}) => {
  await setup(page, context);
  await page.clock.install();
  let polls = 0,
    fail = false,
    stage = "fetching_patents";
  await page.route(`**/api/jobs/${job}`, (route) => {
    polls++;
    return fail
      ? route.fulfill({
          status: 503,
          json: { detail: "Temporary status failure" },
        })
      : route.fulfill({
          json: { job_id: job, status: "processing", current_step: stage },
        });
  });
  await page.goto(`/results/${job}`);
  await expect(page.locator('[aria-current="step"]')).toContainText(
    "Fetching patents",
  );
  await page.clock.runFor(7000);
  await expect(page.locator('[aria-current="step"]')).toContainText(
    "Fetching patents",
  );
  fail = true;
  await page.clock.runFor(3500);
  await expect(page.locator('p[role="alert"]')).toContainText(
    "Temporary status failure",
  );
  fail = false;
  stage = "writing_report";
  await page.clock.runFor(3500);
  await expect(page.locator('[aria-current="step"]')).toContainText(
    "Writing your brief",
  );
  await expect(page.locator('p[role="alert"]')).toHaveCount(0);
  expect(polls).toBeGreaterThan(2);
});
test("consecutive polling failures pause and Retry status only reads", async ({
  page,
  context,
}) => {
  const calls = await setup(page, context);
  await page.clock.install();
  let polls = 0;
  await page.route(`**/api/jobs/${job}`, (route) => {
    polls++;
    return route.fulfill({
      status: 503,
      json: { detail: "Persistent status outage" },
    });
  });
  await page.goto(`/results/${job}`);
  await expect(page.locator('p[role="alert"]')).toBeVisible();
  await page.clock.runFor(10000);
  await expect(
    page.getByRole("button", { name: "Retry status" }),
  ).toBeVisible();
  expect(polls).toBe(3);
  await page.clock.runFor(30000);
  expect(polls).toBe(3);
  await page.getByRole("button", { name: "Retry status" }).click();
  await expect.poll(() => polls).toBe(4);
  expect(calls.post).toBe(0);
});
test("navigation cancels an in-flight status request without overlapping polls", async ({
  page,
  context,
}) => {
  await setup(page, context);
  await page.clock.install();
  let polls = 0;
  await page.route(`**/api/jobs/${job}`, () => {
    polls++;
  });
  await page.goto(`/results/${job}`);
  await expect.poll(() => polls).toBe(1);
  await page.clock.runFor(10000);
  expect(polls).toBe(1);
  const aborted = page.waitForEvent("requestfailed", (r) =>
    r.url().endsWith(`/jobs/${job}`),
  );
  await page.goto("/");
  await aborted;
  await page.clock.runFor(30000);
  expect(polls).toBe(1);
});
test("cached claims failure offers a free retry, whose timeout is visible", async ({
  page,
  context,
}) => {
  const calls = await setup(page, context);
  await page.clock.install();
  let reads = 0;
  await page.route(`**/api/jobs/${job}/analyze-claims`, (route) => {
    expect(route.request().method()).toBe("GET");
    reads++;
    if (reads === 1)
      return route.fulfill({
        status: 503,
        json: { detail: "Cached claims unavailable" },
      });
  });
  await page.goto(`/results/${job}`);
  await expect(page.locator('p[role="alert"]')).toContainText(
    "Cached claims unavailable",
  );
  await page.getByRole("button", { name: "Retry saved claims" }).click();
  await expect.poll(() => reads).toBe(2);
  await page.clock.runFor(16000);
  await expect(page.locator('p[role="alert"]')).toContainText(
    "Saved claims timed out",
  );
  await expect(
    page.getByRole("button", { name: "Retry saved claims" }),
  ).toBeVisible();
  expect(calls.post).toBe(0);
});
test("account change cancels pending cached claims and hides the previous report", async ({
  page,
  context,
}) => {
  await setup(page, context);
  let pending;
  await page.route(`**/api/jobs/${job}/analyze-claims`, (route) => {
    pending = route;
  });
  await page.goto(`/results/${job}`);
  await expect(page.getByText("Exact saved report")).toBeVisible();
  await expect.poll(() => !!pending).toBe(true);
  await page.route(`**/api/jobs/${job}`, (route) =>
    route.fulfill({ status: 404, json: { detail: "Unavailable" } }),
  );
  const aborted = page.waitForEvent("requestfailed", (r) =>
    r.url().endsWith("analyze-claims"),
  );
  const host = new URL(
    process.env.NEXT_PUBLIC_SUPABASE_URL || "https://example.supabase.co",
  ).hostname.split(".")[0];
  await page.evaluate(
    ({ host }) => {
      const channel = new BroadcastChannel(`sb-${host}-auth-token`);
      channel.postMessage({
        event: "SIGNED_IN",
        session: {
          access_token: "other-token",
          user: {
            id: "00000000-0000-0000-0000-000000000002",
            email: "other@example.test",
          },
        },
      });
      channel.close();
    },
    { host },
  );
  await aborted;
  await expect(page.getByText(/unavailable to your account/)).toBeVisible();
  await pending.fulfill({ json: { claims: [claim] } }).catch(() => {});
  await expect(page.getByText("Exact saved report")).toHaveCount(0);
  await expect(page.getByText("Saved claim title")).toHaveCount(0);
});
test("insufficient evidence exposes no generated conclusions or claims action", async ({
  page,
  context,
}) => {
  const calls = await setup(page, context, {
    retrieval_outcome: "insufficient_evidence",
    final_report: null,
    clusters: [],
    white_space_analysis: "",
    coverage_warnings: ["A provider failed; coverage incomplete."],
  });
  await page.goto(`/results/${job}`);
  await expect(
    page.getByText(/Insufficient evidence: retrieval succeeded/),
  ).toBeVisible();
  await expect(
    page.getByText("A provider failed; coverage incomplete."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: /Generate claims|Regenerate claims|Generate idea/,
    }),
  ).toHaveCount(0);
  expect(calls.post).toBe(0);
});
test("initial cached claims timeout retains the saved report and offers a free retry", async ({
  page,
  context,
}) => {
  const calls = await setup(page, context);
  await page.clock.install();
  let reads = 0;
  await page.route(`**/api/jobs/${job}/analyze-claims`, () => {
    reads++;
  });
  await page.goto(`/results/${job}`);
  await expect(page.getByText("Exact saved report")).toBeVisible();
  await expect.poll(() => reads).toBe(1);
  await page.clock.runFor(16000);
  await expect(page.locator('p[role="alert"]')).toContainText(
    "Saved claims timed out",
  );
  await expect(page.getByText("Exact saved report")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Retry saved claims" }),
  ).toBeVisible();
  expect(calls.post).toBe(0);
});
