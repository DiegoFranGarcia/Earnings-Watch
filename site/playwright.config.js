// Browser tests of the built site, served the way GitHub Pages serves it (tests/serve.mjs):
// only under /Earnings-Watch/. Build first, against the fixture export:
//   uv run python scripts/make_site_fixture.py --out site/fixture
//   EW_DATA_DIR=fixture npm run build && npm test
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "tests",
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [["list"], ["github"]] : "list",
  use: { baseURL: "http://localhost:4173/Earnings-Watch/", trace: "retain-on-failure" },
  // PW_CHROMIUM_PATH: a Chromium already on the machine, for running these where Playwright
  // cannot download its own; unset in CI, where it installs one.
  projects: [{
    name: "chromium",
    use: { ...devices["Desktop Chrome"], launchOptions: { executablePath: process.env.PW_CHROMIUM_PATH || undefined } },
  }],
  webServer: { command: "node tests/serve.mjs", url: "http://localhost:4173/Earnings-Watch/", reuseExistingServer: !process.env.CI },
});
