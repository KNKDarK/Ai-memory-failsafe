import type {
  CauseStatus,
  FailureCategory,
  MemoryStatus,
  OutcomeType,
} from "./types";

export type Tone = "success" | "danger" | "warn" | "info" | "accent" | "muted";

export function outcomeTone(outcome: OutcomeType | string): Tone {
  switch (outcome) {
    case "success":
      return "success";
    case "task_failure":
    case "tool_failure":
      return "danger";
    case "timeout":
      return "warn";
    case "invalid_output":
      return "warn";
    default:
      return "muted";
  }
}

export function outcomeLabel(outcome: OutcomeType | string): string {
  switch (outcome) {
    case "task_failure":
      return "Task failure";
    case "tool_failure":
      return "Tool failure";
    case "invalid_output":
      return "Invalid output";
    case "timeout":
      return "Timeout";
    case "success":
      return "Success";
    default:
      return outcome;
  }
}

export function causeTone(status: CauseStatus | string): Tone {
  return status === "confirmed" ? "success" : "warn";
}

export function causeLabel(status: CauseStatus | string): string {
  return status === "confirmed" ? "Confirmed cause" : "Hypothesis";
}

export function statusTone(status: MemoryStatus | string): Tone {
  switch (status) {
    case "active":
      return "success";
    case "outdated":
      return "warn";
    case "incorrect":
      return "danger";
    case "archived":
      return "muted";
    default:
      return "muted";
  }
}

export function categoryTone(category: string): Tone {
  switch (category) {
    case "fixable":
      return "success";
    case "restraint":
      return "accent";
    case "detection":
      return "info";
    default:
      return "muted";
  }
}

export function humanize(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function num(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
}

export function signed(value: number, digits = 3): string {
  const fixed = value.toFixed(digits);
  return value > 0 ? `+${fixed}` : fixed;
}

export function shortId(id: string, length = 10): string {
  if (!id) return "—";
  if (id.length <= length) return id;
  return `${id.slice(0, length)}…`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null || Number.isNaN(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

export function categoryLabel(category: FailureCategory | string): string {
  return humanize(category);
}
