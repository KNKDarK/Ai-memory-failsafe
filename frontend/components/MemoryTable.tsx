"use client";

import { Fragment, useState } from "react";

import { categoryLabel, causeLabel, causeTone, pct, shortId, statusTone } from "@/lib/format";
import type { FailureMemory } from "@/lib/types";

import { MemoryCard } from "./MemoryCard";
import { Badge } from "./ui";

// The Memory Bank table: one row per learned failure lesson, showing the
// failure, its extracted root cause, and the learned prevention strategy.
// Rows expand inline to the full memory card so feedback / lifecycle actions
// stay available without leaving the table.
export function MemoryTable({
  memories,
  onChanged,
  onDeleted,
}: {
  memories: FailureMemory[];
  onChanged: (updated: FailureMemory) => void;
  onDeleted: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <div className="table-scroll">
      <table className="table">
        <thead>
          <tr>
            <th>Failure</th>
            <th>Root cause</th>
            <th>Learned prevention</th>
            <th>Category</th>
            <th>Status</th>
            <th>Trust</th>
            <th>Seen</th>
            <th>Applied</th>
            <th>Success</th>
            <th aria-label="details" />
          </tr>
        </thead>
        <tbody>
          {memories.map((memory) => {
            const open = expanded === memory.id;
            return (
              <Fragment key={memory.id}>
                <tr>
                  <td>
                    <div className="memory-title">{memory.failure}</div>
                    <div className="small faint mono">
                      {memory.task_type}
                      {memory.action ? ` · ${memory.action}` : ""}
                    </div>
                  </td>
                  <td>
                    <div className="small">{memory.root_cause}</div>
                    <Badge tone={causeTone(memory.cause_status)}>
                      {causeLabel(memory.cause_status)}
                    </Badge>
                  </td>
                  <td className="small">{memory.prevention}</td>
                  <td>
                    <Badge tone="muted">{categoryLabel(memory.failure_category)}</Badge>
                  </td>
                  <td>
                    <Badge tone={statusTone(memory.status)}>{memory.status}</Badge>
                  </td>
                  <td className="mono small">{pct(memory.effective_confidence, 0)}</td>
                  <td className="mono small">{memory.occurrence_count}</td>
                  <td className="mono small">{memory.uses}</td>
                  <td className="mono small">{pct(memory.success_rate, 0)}</td>
                  <td className="nowrap">
                    <button
                      className="btn ghost small"
                      onClick={() => setExpanded(open ? null : memory.id)}
                      aria-expanded={open}
                    >
                      {open ? "▾" : "▸"} Details
                    </button>
                  </td>
                </tr>
                {open && (
                  <tr>
                    <td
                      colSpan={10}
                      style={{ background: "rgba(7, 11, 22, 0.45)", padding: 12 }}
                    >
                      <div className="small faint mono" style={{ marginBottom: 8 }}>
                        {shortId(memory.id, 14)} · updated{" "}
                        {new Date(memory.updated_at).toLocaleString()}
                      </div>
                      <MemoryCard
                        memory={memory}
                        onChanged={onChanged}
                        onDeleted={onDeleted}
                      />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
