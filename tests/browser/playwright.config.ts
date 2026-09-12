import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

const app = path.resolve(import.meta.dirname, "../..");
const python = process.env.SGC_EXAMPLE_PYTHON ?? path.join(app, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");
export default defineConfig({
  testDir: ".",
  testMatch: "example-app.spec.ts",
  outputDir: "./test-results",
  workers: 1,
  timeout: 120_000,
  use: {
    baseURL: "http://127.0.0.1:8515",
    viewport: { width: 1600, height: 1200 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: `"${python}" "${path.join(app, "tests/browser/run_app.py")}"`,
    url: "http://127.0.0.1:8515/_stcore/health",
    timeout: 120_000,
    reuseExistingServer: false,
  },
  projects: [{
    name: "chromium",
    use: {
      ...devices["Desktop Chrome"],
      viewport: { width: 1600, height: 1200 },
      ...(process.env.SGC_CHROMIUM_EXECUTABLE ? { launchOptions: { executablePath: process.env.SGC_CHROMIUM_EXECUTABLE } } : {}),
    },
  }],
});
