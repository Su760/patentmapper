const { test, expect } = require("@playwright/test");
const owner = "00000000-0000-0000-0000-000000000001";
const job = "10000000-0000-0000-0000-000000000001";
const status = {
  plan: "free",
  window_seconds: 604800,
  as_of: new Date().toISOString(),
  usage: {
    job: { used: 2, limit: 4, remaining: 2 },
    claims: { used: 1, limit: 3, remaining: 2 },
    ideation: { used: 4, limit: 6, remaining: 2 },
  },
};
async function signIn(context) {
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
}
async function fixtures(page) {
  await page.route("**/api/**", async (route) => {
    expect(route.request().headers().authorization).toBe(
      "Bearer fixture-token",
    );
    const url = route.request().url();
    await route.fulfill({
      json: url.includes("subscription-status")
        ? status
        : url.includes("analyze-claims")
          ? { claims: null }
          : { job_id: job, status: "completed" },
    });
  });
  await page.route("**/rest/v1/**", async (route) => {
    const url = new URL(route.request().url());
    let data = url.pathname.includes("search_results")
      ? {
          clusters: [],
          citation_links: [],
          white_space_analysis:
            "### Gap 1: First gap\n**Viability: High**\nFirst synthetic gap.\n### Gap 2: Second gap\n**Viability: High**\nSecond synthetic gap.\n",
        }
      : {
          id: job,
          invention_idea: "Synthetic owner invention",
          status: "completed",
          created_at: "2026-01-01T00:00:00Z",
        };
    if (url.searchParams.has("order")) data = [data];
    await route.fulfill({ json: data });
  });
}

test("signed-out demo makes no private API or database requests", async ({
  page,
}) => {
  let privateCalls = 0;
  page.on("request", (r) => {
    if (/\/api\/|\/rest\/v1\//.test(r.url())) privateCalls++;
  });
  await page.goto("/results/demo");
  await page.getByRole("button", { name: /Generate idea/ }).click();
  await expect(
    page.getByText("Synthetic calibration controller"),
  ).toBeVisible();
  await page.goto("/dashboard");
  await expect(
    page.getByText("A fixed synthetic demo. Sign in for private analyses."),
  ).toBeVisible();
  await page.goto(`/results/${job}`);
  await expect(page.getByText(/A job link alone/)).toBeVisible();
  expect(privateCalls).toBe(0);
});

test("dashboard and pricing show authoritative rolling counts and actionable failures", async ({
  page,
  context,
}) => {
  await signIn(context);
  await fixtures(page);
  await page.goto("/dashboard");
  await expect(page.getByLabel("Usage allowance")).toContainText(
    "Free · rolling 7 days",
  );
  await expect(page.getByLabel("Usage allowance")).toContainText(
    "Analyses: 2/4 used (2 remaining)",
  );
  await expect(page.getByLabel("Usage allowance")).toContainText(
    "Ideas: 4/6 used",
  );
  await page.route("**/stripe/subscription-status", (route) =>
    route.fulfill({
      status: 503,
      json: {
        detail:
          "Usage status unavailable. Reload to retry; your allowance has not been reset.",
      },
    }),
  );
  await page.getByRole("button", { name: "Refresh usage" }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Usage status unavailable" }),
  ).toContainText("allowance has not been reset");
  await expect(page.getByLabel("Usage allowance")).toHaveCount(0);
  await page.goto("/pricing");
  await expect(page.getByRole("button", { name: "Retry usage" })).toBeVisible();
  await page.route("**/rest/v1/searches*", (route) =>
    route.fulfill({ status: 403, json: { message: "Fixture denial" } }),
  );
  await page.goto("/dashboard");
  await expect(
    page.getByText(
      "Could not load your analyses. Reload to retry or sign in again.",
    ),
  ).toBeVisible();
});

test("ideation errors are visible and concurrent cards retain independent loading", async ({
  page,
  context,
}) => {
  await signIn(context);
  await fixtures(page);
  const pending = [];
  await page.route("**/api/jobs/*/ideate", (route) => {
    pending.push(route);
  });
  await page.goto(`/results/${job}`);
  const cards = page.locator(".pm-ws-card");
  await expect(cards).toHaveCount(2);
  await cards.nth(0).getByRole("button").click();
  await cards.nth(1).getByRole("button").click();
  await expect.poll(() => pending.length).toBe(2);
  await expect(cards.nth(0).getByRole("button")).toBeDisabled();
  await expect(cards.nth(1).getByRole("button")).toBeDisabled();
  await pending[0].fulfill({
    status: 402,
    json: {
      detail: {
        message:
          "Usage limit reached. Check your plan or try after the rolling window.",
      },
    },
  });
  await expect(cards.nth(0).getByRole("alert")).toContainText(
    "Check your plan",
  );
  await expect(cards.nth(0).getByRole("button")).toBeEnabled();
  await expect(cards.nth(1).getByRole("button")).toBeDisabled();
  await pending[1].fulfill({ status: 401, json: { detail: "expired" } });
  await expect(cards.nth(1).getByRole("alert")).toContainText("Sign in again");
  await expect(cards.nth(1).getByRole("button")).toBeEnabled();
  await cards.nth(0).getByRole("button").click();
  await expect(cards.nth(0).getByRole("alert")).toHaveCount(0);
  await expect.poll(() => pending.length).toBe(3);
  await pending[2].fulfill({
    status: 503,
    json: { detail: "Usage store unavailable; no paid work started" },
  });
  await expect(cards.nth(0).getByRole("alert")).toContainText(
    "no paid work started",
  );
  await expect(cards.nth(0).getByRole("button")).toBeEnabled();
});
