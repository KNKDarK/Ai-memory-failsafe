"use client";

import type { ReactNode } from "react";

import type { Tone } from "@/lib/format";

export function Badge({
  tone = "muted",
  children,
}: {
  tone?: Tone;
  children: ReactNode;
}) {
  return <span className={`badge tone-${tone}`}>{children}</span>;
}

export function Dot({ tone = "muted" }: { tone?: Tone }) {
  return <span className={`dot tone-${tone}`} />;
}

export function Card({
  title,
  subtitle,
  actions,
  children,
  className,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card${className ? ` ${className}` : ""}`}>
      {(title || actions) && (
        <header className="card-head">
          <div className="grow">
            {title && <h2 className="card-title">{title}</h2>}
            {subtitle && <div className="card-sub">{subtitle}</div>}
          </div>
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      <div className="card-body">{children}</div>
    </section>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: Tone;
}) {
  const color =
    tone === "success"
      ? "var(--success)"
      : tone === "danger"
        ? "var(--danger)"
        : tone === "warn"
          ? "var(--warn)"
          : undefined;
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value mono" style={color ? { color } : undefined}>
        {value}
      </div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

export function Bar({
  value,
  max = 1,
  tone,
}: {
  value: number;
  max?: number;
  tone?: "success" | "danger" | "warn";
}) {
  const ratio = max <= 0 ? 0 : Math.max(0, Math.min(1, value / max));
  return (
    <div className="bar">
      <div
        className={`bar-fill${tone ? ` ${tone}` : ""}`}
        style={{ width: `${ratio * 100}%` }}
      />
    </div>
  );
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="error-banner" role="alert">
      <span aria-hidden>⚠</span>
      <span className="wrap-anywhere">{message}</span>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Spinner() {
  return <span className="spinner" aria-label="loading" role="status" />;
}

export function JsonBlock({ data, label = "Raw JSON" }: { data: unknown; label?: string }) {
  return (
    <details className="json">
      <summary>{label}</summary>
      <pre>{JSON.stringify(data, null, 2)}</pre>
    </details>
  );
}

export function KeyValue({ rows }: { rows: Array<[string, ReactNode]> }) {
  return (
    <div className="kv">
      {rows.map(([key, value]) => (
        <div className="kv-row" key={key}>
          <span className="kv-key">{key}</span>
          <span className="kv-val">{value}</span>
        </div>
      ))}
    </div>
  );
}
