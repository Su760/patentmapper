const { test, expect } = require("@playwright/test");
const owner = "00000000-0000-0000-0000-000000000001",
  job = "10000000-0000-0000-0000-000000000001";
async function setup(page, context) {
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
  await page.route("**/api/**", (route) =>
    route.fulfill({ status: 503, json: { detail: "Test usage unavailable" } }),
  );
}
test("lost submission response and page reload reuse the same key without automatic POST", async ({
  page,
  context,
}) => {
  await setup(page, context);
  const bodies = [];
  await page.route("**/api/jobs", async (route) => {
    bodies.push(route.request().postDataJSON());
    expect(route.request().headers().authorization).toBe(
      "Bearer fixture-token",
    );
    if (bodies.length === 1) return route.abort("failed");
    return route.fulfill({
      status: 202,
      json: { job_id: job, status: "queued" },
    });
  });
  await page.route(`**/api/jobs/${job}`, (route) =>
    route.fulfill({
      json: { job_id: job, status: "queued", current_step: "queued" },
    }),
  );
  await page.goto("/");
  await page
    .getByRole("textbox")
    .fill("Synthetic durable irrigation controller invention");
  await page
    .getByRole("button", { name: /Map|Analy/i })
    .last()
    .click();
  await expect(
    page.getByText(/earlier submission is unconfirmed/),
  ).toBeVisible();
  expect(bodies).toHaveLength(1);
  await page.reload();
  await expect(page.getByRole("textbox")).toHaveValue(
    "Synthetic durable irrigation controller invention",
  );
  expect(bodies).toHaveLength(1);
  await page
    .getByRole("button", { name: /Map|Analy/i })
    .last()
    .click();
  await expect(
    page.getByRole("heading", { name: "Analysis queued" }),
  ).toBeVisible();
  expect(bodies).toHaveLength(2);
  expect(bodies[1]).toEqual(bodies[0]);
  expect(bodies[0].submission_key).toMatch(/^[0-9a-f-]{36}$/);
});
test("queued running finalizing and interrupted are accurate; retry status starts no paid work", async ({
  page,
  context,
}) => {
  await setup(page, context);
  await page.clock.install();
  let status = "queued",
    posts = 0;
  await page.route(`**/api/jobs/${job}`, (route) => {
    if (route.request().method() === "POST") posts++;
    return route.fulfill({
      json: {
        job_id: job,
        status,
        current_step: status === "running" ? "fetching_patents" : status,
        error_message:
          status === "interrupted" ? "Execution was interrupted." : null,
      },
    });
  });
  await page.goto(`/results/${job}`);
  await expect(
    page.getByRole("heading", { name: "Analysis queued" }),
  ).toBeVisible();
  status = "running";
  await page.clock.fastForward(3100);
  await expect(
    page.getByRole("heading", { name: "Analyzing your invention..." }),
  ).toBeVisible();
  status = "finalizing";
  await page.clock.fastForward(3100);
  await expect(
    page.getByRole("heading", { name: "Saving completed analysis" }),
  ).toBeVisible();
  status = "interrupted";
  await page.clock.fastForward(3100);
  await expect(
    page.getByRole("heading", { name: "Analysis interrupted" }),
  ).toBeVisible();
  await expect(page.getByText(/reservation is retained/)).toBeVisible();
  await page.getByRole("button", { name: "Retry status" }).click();
  await expect(
    page.getByRole("heading", { name: "Analysis interrupted" }),
  ).toBeVisible();
  expect(posts).toBe(0);
});
test("dashboard follows durable states and cancels monitoring on navigation", async ({
  page,
  context,
}) => {
  await setup(page, context);
  await page.clock.install();
  let calls = 0,
    status = "queued";
  await page.route("**/rest/v1/searches*", (route) =>
    route.fulfill({
      json: [
        {
          id: job,
          user_id: owner,
          invention_idea: "Durable fixture",
          status: "queued",
          current_step: "queued",
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
    }),
  );
  await page.route(`**/api/jobs/${job}`, (route) => {
    calls++;
    return route.fulfill({
      json: {
        job_id: job,
        status,
        current_step: status,
        error_message:
          status === "interrupted"
            ? "Execution interrupted; fresh paid analysis required."
            : null,
      },
    });
  });
  await page.goto("/dashboard");
  await expect(
    page.locator(".pm-badge").getByText("Queued", { exact: true }),
  ).toBeVisible();
  status = "interrupted";
  await page.clock.fastForward(3100);
  await expect(
    page.locator(".pm-badge").getByText("Interrupted", { exact: true }),
  ).toBeVisible();
  await page.goto("/");
  const stopped = calls;
  await page.clock.fastForward(12000);
  expect(calls).toBe(stopped);
});
test("account switch aborts uncertain submission and isolates the next key and inputs", async ({
  page,
  context,
}) => {
  await setup(page, context);
  let pending;
  const sent = [];
  await page.route("**/api/jobs", (route) => {
    sent.push({
      body: route.request().postDataJSON(),
      token: route.request().headers().authorization,
    });
    if (sent.length === 1) {
      pending = route;
      return;
    }
    return route.fulfill({
      status: 503,
      json: { detail: "Submission unconfirmed" },
    });
  });
  await page.goto("/");
  await page
    .getByRole("textbox")
    .fill("Private invention for the original account");
  await page
    .getByRole("button", { name: /Map|Analy/i })
    .last()
    .click();
  await expect.poll(() => !!pending).toBe(true);
  const aborted = page.waitForEvent("requestfailed", (request) =>
    request.url().endsWith("/api/jobs"),
  );
  const host = new URL(
    process.env.NEXT_PUBLIC_SUPABASE_URL || "https://example.supabase.co",
  ).hostname.split(".")[0];
  await page.evaluate((host) => {
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
  }, host);
  await aborted;
  await expect(page.getByRole("textbox")).toHaveValue("");
  await pending
    .fulfill({ status: 202, json: { job_id: job, status: "queued" } })
    .catch(() => {});
  await expect(page).toHaveURL("/");
  await page
    .getByRole("textbox")
    .fill("Private invention for the second account");
  await page
    .getByRole("button", { name: /Map|Analy/i })
    .last()
    .click();
  await expect.poll(() => sent.length).toBe(2);
  expect(sent[1].token).toBe("Bearer other-token");
  expect(sent[1].body.submission_key).not.toBe(sent[0].body.submission_key);
  expect(sent[1].body.invention_idea).toBe(
    "Private invention for the second account",
  );
});
