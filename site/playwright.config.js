// Browser tests of the assembled site, served the way GitHub Pages serves it (tests/serve.mjs):
// only under /Earnings-Watch/, with the app beside the export's files as the deploy puts it.
// From the repository's root:
//   uv run python scripts/make_site_fixture.py --out site/fixture
//   cd site && EW_DATA_DIR=fixture npm run build
//   python3 ../scripts/build_site.py --add-app build --out fixture && npm test
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "tests",
  testIgnore: "unit/**",  // node --test (npm run test:unit)
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
