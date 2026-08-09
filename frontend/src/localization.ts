export const fieldLabels: Record<string, string> = {
  sales_amount: "销售额",
  order_count: "订单数",
  units_sold: "销售件数",
  refund_amount: "退款金额",
  refund_count: "退款笔数",
  average_order_value: "平均订单金额",
  channel: "销售渠道",
  product: "商品",
  category: "品类",
  order_status: "订单状态",
  refund_status: "退款状态",
  day: "日期",
  product_id: "商品编号",
  order_id: "订单编号",
  refund_id: "退款编号",
  product_name: "商品名称",
  reason: "退款原因",
  status: "状态",
  quantity: "数量",
  unit_price: "成交单价",
};

export const valueLabels: Record<string, string> = {
  pending: "待处理",
  paid: "已支付",
  shipped: "已发货",
  completed: "已完成",
  cancelled: "已取消",
  requested: "已申请",
  approved: "已批准",
  rejected: "已拒绝",
};

export const traceComponentLabels: Record<string, string> = {
  "node.scope": "请求范围检查",
  "node.respond": "助手答复",
  "node.plan": "分析计划",
  "node.retrieve": "业务证据检索",
  "node.generate_sql": "查询生成",
  "node.validate_sql": "查询安全校验",
  "node.validate_business_sql": "业务一致性校验",
  "node.assess_risk": "风险评估",
  "node.request_approval": "人工审批",
  "node.execute_sql": "数据查询",
  "node.summarize": "结果总结",
  "node.fail": "失败处理",
  "model.plan": "计划模型",
  "model.generate_sql": "查询生成模型",
  "model.summarize": "结果总结模型",
};

export function label(value: string): string {
  return fieldLabels[value] ?? valueLabels[value] ?? value;
}

export function localizeEvidence(sourceId: string): string {
  const metric = sourceId.match(/^metric\.([^.]+)\.(v\d+)$/);
  if (metric) return `指标口径：${label(metric[1])} · ${metric[2]}`;
  if (sourceId.startsWith("schema.join.")) return `关联关系：${sourceId.slice(12)}`;
  if (sourceId.startsWith("schema.")) return `数据表：${sourceId.slice(7)}`;
  return sourceId;
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return value.toLocaleString("zh-CN");
  if (Array.isArray(value)) return value.map(formatValue).join("、");
  return label(String(value));
}

/** Backend summaries may contain enum values; keep source identifiers unchanged but localize user-facing status words. */
export function localizeAnswer(value: string): string {
  return value
    .replace(/\bcompleted\b/gi, "已完成")
    .replace(/\brejected\b/gi, "已拒绝")
    .replace(/\bapproved\b/gi, "已批准")
    .replace(/\brequested\b/gi, "已申请")
    .replace(/\bpaid\b/gi, "已支付")
    .replace(/\bshipped\b/gi, "已发货")
    .replace(/\bcancelled\b/gi, "已取消")
    .replace(/\bpending\b/gi, "待处理");
}

/** 将后端错误转换为普通用户可理解的提示，技术标识仍保留在审计记录中。 */
export function localizeUserMessage(value: string): string {
  const message = value.trim();
  if (!message) return "请求未能完成，请稍后重试。";
  if (/[\u4e00-\u9fff]/.test(message)) return localizeAnswer(message);
  if (/failed to fetch|network request failed|fetch failed/i.test(message)) return "暂时无法连接数据服务，请稍后重试。";
  if (/unauthorized|401/i.test(message)) return "登录状态已失效，请重新登录。";
  if (/forbidden|403/i.test(message)) return "当前账号无权执行此操作。";
  if (/does not support dimensions/i.test(message)) return "当前指标不支持所选维度，请调整问题后重试。";
  if (/out.?of.?domain|unsupported|not supported/i.test(message)) return "这个问题超出当前零售数据范围，暂时无法分析。";
  if (/timeout|timed out/i.test(message)) return "数据服务响应超时，请稍后重试。";
  if (/required|invalid|validation/i.test(message)) return "请求信息不完整或格式不正确，请调整后重试。";
  return "本次请求未能完成，请稍后重试。";
}
