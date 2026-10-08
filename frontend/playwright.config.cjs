const { defineConfig } = require("@playwright/test");
module.exports = defineConfig({
  testDir: "./tests",
  testMatch: "**/*.cjs",
  testIgnore: "**/integrated-flow.cjs",
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  use: { baseURL: "http://127.0.0.1:3109", browserName: "chromium" },
  webServer: {
    command: "npm run start -- --hostname 127.0.0.1 --port 3109",
    url: "http://127.0.0.1:3109",
    reuseExistingServer: false,
  },
});
