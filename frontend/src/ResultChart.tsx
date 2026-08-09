import { BarChart, LineChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
} from "echarts/components";
import { init, use } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";
import { EmptyState } from "./components";
import { formatValue, label, localizeAnswer } from "./localization";
import type { ChartSpec } from "./types";

use([BarChart, LineChart, GridComponent, TooltipComponent, CanvasRenderer]);

export default function ResultChart({
  spec,
  rows,
}: {
  spec?: ChartSpec | null;
  rows: Array<Record<string, unknown>>;
}) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!container.current || !spec || rows.length === 0 || spec.chart_type === "kpi") return;
    const chart = init(container.current, undefined, { renderer: "canvas" });
    const xField = spec.x_field ?? Object.keys(rows[0])[0];
    const xValues = rows.map((row) => formatValue(row[xField]));
    const labelInterval = Math.max(0, Math.ceil(xValues.length / 7) - 1);
    const series = spec.y_fields.map((field) => ({
      name: label(field),
      type: spec.chart_type === "line" ? "line" : "bar",
      data: rows.map((row) => Number(row[field] ?? 0)),
      barMaxWidth: 48,
      smooth: spec.chart_type === "line",
      symbolSize: 7,
      itemStyle: {
        color: "#1D4ED8",
        borderRadius: spec.chart_type === "bar" ? [2, 2, 0, 0] : 0,
      },
      lineStyle: { color: "#1D4ED8", width: 2 },
      label: {
        show: rows.length <= 10,
        position: "top",
        color: "#1E293B",
        fontFamily: "JetBrains Mono, monospace",
        fontSize: 10,
      },
    }));
    chart.setOption({
      animationDuration: 400,
      tooltip: { trigger: "axis" },
      grid: { left: 54, right: 18, top: 28, bottom: 44, containLabel: true },
      xAxis: {
        type: "category",
        data: xValues,
        axisLabel: {
          color: "#64748B",
          fontSize: 11,
          interval: labelInterval,
          hideOverlap: true,
          formatter: (value: string) => shortAxisLabel(value),
        },
        axisLine: { lineStyle: { color: "#CBD5E1" } },
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        axisLabel: {
          color: "#94A3B8",
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 10,
        },
        splitLine: { lineStyle: { color: "#E5E7EB", type: "dashed" } },
      },
      series,
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(container.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [rows, spec]);

  if (!spec || rows.length === 0) {
    return <EmptyState>当前结果不适合绘制图表，先查看结果表格</EmptyState>;
  }
  if (spec.chart_type === "kpi") {
    const field = spec.y_fields[0];
    return (
      <div className="kpi-chart">
        <span>{label(field)}</span>
        <strong className="mono">{formatValue(rows[0]?.[field])}</strong>
      </div>
    );
  }
  return <div className="chart-canvas" ref={container} aria-label={localizeAnswer(spec.title)} />;
}

function shortAxisLabel(value: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:T|$)/.exec(value);
  return match ? `${match[2]}-${match[3]}` : value;
}
