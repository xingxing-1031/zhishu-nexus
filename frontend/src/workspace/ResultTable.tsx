import { EmptyState } from "../components";
import { formatValue, label } from "../localization";

export default function ResultTable({ rows }: { rows: Array<Record<string, unknown>> }) {
  if (rows.length === 0) return <EmptyState>当前查询没有可展示的数据行</EmptyState>;
  const columns = Object.keys(rows[0]);
  return (
    <div className="inline-table-scroll">
      <table className="inline-result-table">
        <thead><tr>{columns.map((column) => <th key={column}>{label(column)}</th>)}</tr></thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {columns.map((column) => (
                <td className={isNumeric(row[column]) ? "numeric mono" : ""} key={column}>{formatValue(row[column])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function isNumeric(value: unknown) {
  return typeof value === "number" || (typeof value === "string" && /^-?\d+(\.\d+)?$/.test(value));
}
