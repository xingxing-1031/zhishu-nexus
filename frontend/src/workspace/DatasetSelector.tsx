import { Database } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { DatasetView } from "../types";

function selectorValue(dataset: DatasetView | null): string {
  return dataset ? `${dataset.dataset_id}@${dataset.version}` : "";
}

export default function DatasetSelector({
  value,
  onChange,
}: {
  value: DatasetView | null;
  onChange: (dataset: DatasetView | null) => void;
}) {
  const [datasets, setDatasets] = useState<DatasetView[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.datasets().then(setDatasets).catch((reason: unknown) => {
      setError(reason instanceof Error ? reason.message : "数据集读取失败。");
      setDatasets([]);
    });
  }, []);

  const currentValue = selectorValue(value);

  return (
    <div className="dataset-selector">
      <label className="dataset-selector-label"><Database size={14} /><span>数据范围</span></label>
      <select
        className="dataset-selector-select"
        value={currentValue}
        onChange={(event) => {
          if (!datasets) return;
          const [id, version] = event.target.value.split("@");
          onChange(datasets.find((dataset) => dataset.dataset_id === id && String(dataset.version) === version) ?? null);
        }}
        disabled={datasets !== null && datasets.length === 0}
      >
        <option value="">自动（全部就绪数据集）</option>
        {datasets?.map((dataset) => (
          <option key={`${dataset.dataset_id}@${dataset.version}`} value={`${dataset.dataset_id}@${dataset.version}`}>
            {dataset.dataset_name}（v{dataset.version}）
          </option>
        ))}
      </select>
      {error ? (
        <span className="dataset-selector-note danger">{error}</span>
      ) : datasets === null ? (
        <span className="dataset-selector-note">正在读取数据集…</span>
      ) : datasets.length === 0 ? (
        <span className="dataset-selector-note">暂无就绪数据集，请管理员先完成数据接入。</span>
      ) : value && value.metrics.length > 0 ? (
        <div className="dataset-metrics">
          <span>可用指标：</span>
          {value.metrics.map((metric) => (
            <span className="metric-chip" key={metric.metric_id} title={`${metric.definition}\n公式：${metric.formula}`}>{metric.name}</span>
          ))}
        </div>
      ) : null}
    </div>
  );
}
