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
