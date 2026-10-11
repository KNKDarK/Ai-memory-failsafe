"use client";

// Zero-dependency, offline SVG charts.
//
// Everything is rendered from the real numbers passed in by the caller (which
// come from the backend endpoints), themed with the dashboard's CSS variables.
// No charting library is bundled, no external request is made, and the output
// is deterministic — which keeps the whole demo runnable with no network.

const TONES: Record<string, string> = {
  accent: "var(--accent, #6ea8fe)",
  success: "var(--success, #38d39f)",
  danger: "var(--danger, #ff6b81)",
  warn: "var(--warn, #ffc66d)",
  info: "var(--info, #67c9ff)",
  muted: "var(--text-faint, #64718c)",
};

function toneColor(tone?: string): string {
  if (!tone) return TONES.accent;
  return TONES[tone] ?? tone;
}

export interface ChartSeries {
  key: string;
  label: string;
  tone?: string;
  values: number[];
}

function isNumber(value: number): boolean {
  return Number.isFinite(value);
}

// Vertical grouped bar chart. Good for a handful of categories with a small
// number of series (e.g. baseline/naive/memory, or precision/recall per method).
export function ColumnChart({
  categories,
  series,
  max,
  format = (value: number) => String(value),
  height = 180,
}: {
  categories: string[];
  series: ChartSeries[];
  max?: number;
  format?: (value: number) => string;
  height?: number;
}) {
  if (categories.length === 0 || series.length === 0) {
    return <div className="empty">No data to chart yet.</div>;
  }

  const width = 640;
  const padTop = 22;
  const padBottom = 44;
  const padLeft = 6;
  const padRight = 6;
  const plotH = height - padTop - padBottom;
  const plotW = width - padLeft - padRight;
  const peak = Math.max(
    1,
    ...series.flatMap((s) => s.values.map((value) => (isNumber(value) ? value : 0))),
  );
  const top = max ?? peak;
  const groupW = plotW / categories.length;
  const barGap = 4;
  const barW = Math.max(6, Math.min(40, (groupW - 22) / series.length - barGap));
  const grid = [0, 0.25, 0.5, 0.75, 1];

  return (
    <div className="chart-wrap">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="chart-svg"
        role="img"
        preserveAspectRatio="xMidYMid meet"
      >
        {grid.map((level) => {
          const y = padTop + plotH - level * plotH;
          return (
            <g key={level}>
              <line
                x1={padLeft}
                y1={y}
                x2={width - padRight}
                y2={y}
                className="chart-grid"
              />
              <text x={padLeft} y={y - 4} className="chart-axis">
                {format(level * top)}
              </text>
            </g>
          );
        })}
        {categories.map((category, ci) => {
          const groupX = padLeft + ci * groupW;
          const barsW = series.length * barW + (series.length - 1) * barGap;
          const startX = groupX + (groupW - barsW) / 2;
          return (
            <g key={category}>
              {series.map((s, si) => {
                const raw = s.values[ci];
                const value = isNumber(raw) ? raw : 0;
                const ratio = top <= 0 ? 0 : Math.max(0, Math.min(1, value / top));
                const barH = ratio * plotH;
                const x = startX + si * (barW + barGap);
                const y = padTop + plotH - barH;
                return (
                  <g key={s.key}>
                    <rect
                      x={x}
                      y={y}
                      width={barW}
                      height={Math.max(0, barH)}
                      rx={3}
                      fill={toneColor(s.tone)}
                      opacity={0.92}
                    />
                    <text
                      x={x + barW / 2}
                      y={y - 5}
                      className="chart-value"
                      textAnchor="middle"
                    >
                      {format(value)}
                    </text>
                  </g>
                );
              })}
              <text
                x={groupX + groupW / 2}
                y={height - padBottom + 20}
                className="chart-cat"
                textAnchor="middle"
              >
                {category}
              </text>
            </g>
          );
        })}
        <line
          x1={padLeft}
          y1={padTop + plotH}
          x2={width - padRight}
          y2={padTop + plotH}
          className="chart-axis-line"
        />
      </svg>
      <div className="chart-legend">
        {series.map((s) => (
          <span className="chart-legend-item" key={s.key}>
            <span className="chart-swatch" style={{ background: toneColor(s.tone) }} />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  );
}

// Single-series line/area chart, used for memory growth over time.
export function LineChart({
  points,
  format = (value: number) => String(value),
  height = 190,
  tone = "accent",
}: {
  points: Array<{ label: string; value: number }>;
  format?: (value: number) => string;
  height?: number;
  tone?: string;
}) {
  if (points.length === 0) {
    return <div className="empty">No data to chart yet.</div>;
  }

  const width = 640;
  const padTop = 18;
  const padBottom = 40;
  const padLeft = 40;
  const padRight = 16;
  const plotH = height - padTop - padBottom;
  const plotW = width - padLeft - padRight;
  const top = Math.max(1, ...points.map((point) => (isNumber(point.value) ? point.value : 0)));
  const stepX = points.length > 1 ? plotW / (points.length - 1) : 0;
  const coords = points.map((point, index) => {
    const value = isNumber(point.value) ? point.value : 0;
    return {
      label: point.label,
      value,
      x: padLeft + index * stepX,
      y: padTop + plotH - (value / top) * plotH,
    };
  });
  const path = coords
    .map((c, i) => `${i === 0 ? "M" : "L"} ${c.x.toFixed(1)} ${c.y.toFixed(1)}`)
    .join(" ");
  const area = `${path} L ${coords[coords.length - 1].x.toFixed(1)} ${
    padTop + plotH
  } L ${coords[0].x.toFixed(1)} ${padTop + plotH} Z`;

  const grid = [0, 0.5, 1];
  const labelStride = Math.max(1, Math.ceil(points.length / 6));

  return (
    <div className="chart-wrap">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="chart-svg"
        role="img"
        preserveAspectRatio="xMidYMid meet"
      >
        {grid.map((level) => {
          const y = padTop + plotH - level * plotH;
          return (
            <g key={level}>
              <line
                x1={padLeft}
                y1={y}
                x2={width - padRight}
                y2={y}
                className="chart-grid"
              />
              <text x={padLeft - 6} y={y + 4} className="chart-axis" textAnchor="end">
                {format(level * top)}
              </text>
            </g>
          );
        })}
        <path d={area} fill={toneColor(tone)} opacity={0.12} />
        <path
          d={path}
          fill="none"
          stroke={toneColor(tone)}
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {coords.map((c, i) => (
          <g key={`${c.label}-${i}`}>
            <circle cx={c.x} cy={c.y} r={2.5} fill={toneColor(tone)} />
            {i % labelStride === 0 && (
              <text
                x={c.x}
                y={height - padBottom + 18}
                className="chart-cat"
                textAnchor="middle"
              >
                {c.label}
              </text>
            )}
          </g>
        ))}
      </svg>
    </div>
  );
}

// Horizontal bar list for longer categorical distributions (failure
// categories, most-applied lessons, lifecycle buckets).
export function BarList({
  items,
  max,
  format = (value: number) => String(value),
  emptyText = "No data yet.",
}: {
  items: Array<{ label: string; value: number; tone?: string; hint?: string }>;
  max?: number;
  format?: (value: number) => string;
  emptyText?: string;
}) {
  if (items.length === 0) {
    return <div className="empty">{emptyText}</div>;
  }
  const top = max ?? Math.max(1, ...items.map((item) => (isNumber(item.value) ? item.value : 0)));
  return (
    <div className="chart-bar-list">
      {items.map((item, index) => {
        const ratio = top <= 0 ? 0 : Math.max(0, Math.min(1, item.value / top));
        return (
          <div className="chart-row" key={`${item.label}-${index}`}>
            <span className="chart-row-label" title={item.hint ?? item.label}>
              {item.label}
            </span>
            <span className="chart-row-track">
              <span
                className="chart-row-fill"
                style={{ width: `${ratio * 100}%`, background: toneColor(item.tone) }}
              />
            </span>
            <span className="chart-row-value mono">{format(item.value)}</span>
          </div>
        );
      })}
    </div>
  );
}
