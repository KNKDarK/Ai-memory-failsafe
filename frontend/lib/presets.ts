import type { EnvironmentSpec } from "./types";

export interface TaskPreset {
  id: string;
  label: string;
  description: string;
  task: string;
  environment: EnvironmentSpec;
}

// Deterministic, sandboxed fault presets. They map 1:1 to the simulated
// scenarios exercised by the backend test suite, so the UI can demonstrate a
// failing run, a recovered run, and a correctly-restrained run without a real
// environment.
export const TASK_PRESETS: TaskPreset[] = [
  {
    id: "deploy_missing_config",
    label: "Deploy — missing configuration",
    description:
      "DATABASE_URL is absent from the environment but present in the secret store. A learned prevention loads it.",
    task: "Deploy the application",
    environment: {
      id: "ui_deploy_missing_config",
      config: { APP_ENV: "production" },
      secrets: { DATABASE_URL: "postgres://secret-local" },
      registry: { requests: "2.31.0" },
      services: { billing_api: { required_env: [], mode: "ok" } },
      faults: { deploy_requires: { app: { env: ["DATABASE_URL"] } } },
    },
  },
  {
    id: "build_missing_dependency",
    label: "Build — missing dependency",
    description:
      "The build requires 'pandas', which is in the registry but not installed.",
    task: "Build the project",
    environment: {
      id: "ui_build_missing_dependency",
      registry: { pandas: "2.2.0", requests: "2.31.0" },
      packages: {},
      faults: { build_requires: ["pandas"] },
    },
  },
  {
    id: "transient_api",
    label: "API — transient failure",
    description:
      "billing_api returns a transient 503; retry with backoff recovers.",
    task: "Fetch data from the billing api",
    environment: {
      id: "ui_transient_api",
      registry: { requests: "2.31.0" },
      services: { billing_api: { required_env: [], mode: "ok" } },
      faults: { api_modes: { billing_api: "transient" } },
    },
  },
  {
    id: "tool_timeout",
    label: "API — tool timeout",
    description:
      "call_api times out on the default 5s budget; an adequate timeout fixes it.",
    task: "Fetch data from the billing api",
    environment: {
      id: "ui_tool_timeout",
      registry: { requests: "2.31.0" },
      services: { billing_api: { required_env: [], mode: "ok" } },
      faults: { timeout_tools: ["call_api"], required_timeout_seconds: 30 },
    },
  },
  {
    id: "invalid_payload",
    label: "API — malformed payload",
    description: "billing_api returns a malformed payload that only a retry resolves.",
    task: "Fetch data from the billing api",
    environment: {
      id: "ui_invalid_payload",
      registry: { requests: "2.31.0" },
      services: { billing_api: { required_env: [], mode: "ok" } },
      faults: { api_modes: { billing_api: "flaky_invalid_payload" } },
    },
  },
  {
    id: "silent_task_failure",
    label: "Deploy — silent task failure",
    description:
      "The deploy tool reports success but does not change state, so the post-condition fails.",
    task: "Deploy the application",
    environment: {
      id: "ui_silent_task_failure",
      config: { APP_ENV: "production", DATABASE_URL: "postgres://ok" },
      services: {},
      faults: { deploy_requires: { app: { env: ["DATABASE_URL"], silent: true } } },
    },
  },
  {
    id: "permanent_api",
    label: "API — permanent failure",
    description:
      "billing_api returns HTTP 500 on every attempt. No prevention can fix it.",
    task: "Fetch data from the billing api",
    environment: {
      id: "ui_permanent_api",
      registry: { requests: "2.31.0" },
      services: { billing_api: { required_env: [], mode: "ok" } },
      faults: { api_modes: { billing_api: "permanent_failure" } },
    },
  },
  {
    id: "benign",
    label: "Benign — no injected fault",
    description: "A clean environment; expected to succeed on the first attempt.",
    task: "Fetch data from the inventory api",
    environment: {
      id: "ui_benign",
      registry: { requests: "2.31.0" },
      services: { inventory_api: { required_env: [], mode: "ok" } },
      faults: {},
    },
  },
];

export const PRESET_BY_ID: Record<string, TaskPreset> = Object.fromEntries(
  TASK_PRESETS.map((preset) => [preset.id, preset]),
);
