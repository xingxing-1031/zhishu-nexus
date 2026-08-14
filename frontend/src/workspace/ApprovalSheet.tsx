import { Check, X } from "lucide-react";
import { useState } from "react";
import { StatusPill } from "../components";
import type { ApprovalRequired } from "../types";

export default function ApprovalSheet({ approval, onClose, onResolve }: { approval: ApprovalRequired; onClose: () => void; onResolve: (decision: "approve" | "reject", reason?: string) => void }) {
  const [reason, setReason] = useState("");
  return (
    <div className="sheet-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="approval-sheet" role="dialog" aria-modal="true" aria-labelledby="approval-title" onMouseDown={(event) => event.stopPropagation()}>
        <header><div><span>人工审批</span><h2 id="approval-title">高风险查询等待确认</h2><p>数据库尚未执行，批准后会从暂停节点继续。</p></div><button type="button" onClick={onClose} aria-label="关闭审批面板" title="关闭"><X size={18} /></button></header>
        <dl className="approval-facts"><div><dt>请求编号</dt><dd><code>{approval.request_id}</code></dd></div><div><dt>预计返回</dt><dd>{approval.result_limit} 行</dd></div><div><dt>SQL 指纹</dt><dd><code>{approval.sql_fingerprint.slice(0, 12)}…{approval.sql_fingerprint.slice(-6)}</code></dd></div></dl>
        <div className="approval-sensitive"><span>触发审批的字段</span><div>{approval.sensitive_columns.map((field) => <StatusPill status="danger" key={field}>{field}</StatusPill>)}</div></div>
        <label className="approval-sql-label">只读 SQL 预览</label>
        <pre className="approval-sql">{approval.sql}</pre>
        <label htmlFor="approvalRejectReason">拒绝原因</label>
        <textarea id="approvalRejectReason" rows={3} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="拒绝时必须填写，例如：超出当前数据权限范围" />
        <footer><button className="approval-reject" type="button" disabled={!reason.trim()} onClick={() => onResolve("reject", reason.trim())}>拒绝请求</button><button className="approval-approve" type="button" onClick={() => onResolve("approve")}><Check size={16} />批准并执行</button></footer>
      </section>
    </div>
  );
}
