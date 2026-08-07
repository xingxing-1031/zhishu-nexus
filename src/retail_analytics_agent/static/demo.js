const STAGES = [
  ["plan", "计划"],
  ["retrieve", "检索"],
  ["generate_sql", "生成查询"],
  ["validate_sql", "安全校验"],
  ["validate_business_sql", "业务校验"],
  ["execute_sql", "执行"],
  ["summarize", "总结"],
];

const ROLE_LABELS = {
  analyst: "分析员",
  admin: "管理员",
};

const FIELD_LABELS = {
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
};

const VALUE_LABELS = {
  pending: "待处理",
  paid: "已支付",
  shipped: "已发货",
  completed: "已完成",
  cancelled: "已取消",
  requested: "已申请",
  approved: "已批准",
  rejected: "已拒绝",
};

const TRACE_COMPONENT_LABELS = {
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

const TRACE_STATUS_LABELS = {
  started: "已开始",
  succeeded: "已完成",
  failed: "失败",
  retry_scheduled: "等待重试",
  rejected: "已拒绝",
  pending: "等待处理",
  degraded: "已降级",
};

const CHART_TYPE_LABELS = {
  bar: "柱状图",
  line: "趋势图",
  kpi: "指标卡",
};

const stageAliases = {
  assess_risk: "validate_business_sql",
  request_approval: "execute_sql",
  fail: "summarize",
};

const state = {
  session: null,
  requestId: null,
  approval: null,
  running: false,
};

const elements = {
  form: document.querySelector("#analysis-form"),
  question: document.querySelector("#question"),
  maxRows: document.querySelector("#max-rows"),
  runButton: document.querySelector("#run-button"),
  requestId: document.querySelector("#request-id"),
  serverDot: document.querySelector("#server-dot"),
  serverStatus: document.querySelector("#server-status"),
  sessionRole: document.querySelector("#session-role"),
  sessionUser: document.querySelector("#session-user"),
  workflowSteps: document.querySelector("#workflow-steps"),
  workflowMessage: document.querySelector("#workflow-message"),
  answerText: document.querySelector("#answer-text"),
  resultStatus: document.querySelector("#result-status"),
  degradation: document.querySelector("#degradation"),
  chartStage: document.querySelector("#chart-stage"),
  chartKind: document.querySelector("#chart-kind"),
  tableStage: document.querySelector("#table-stage"),
  rowCount: document.querySelector("#row-count"),
  planOutput: document.querySelector("#plan-output"),
  evidenceList: document.querySelector("#evidence-list"),
  retryCount: document.querySelector("#retry-count"),
  traceButton: document.querySelector("#trace-button"),
  traceBand: document.querySelector("#trace-band"),
  traceList: document.querySelector("#trace-list"),
  closeTrace: document.querySelector("#close-trace"),
  approvalPane: document.querySelector("#approval-pane"),
  approvalReasons: document.querySelector("#approval-reasons"),
  approvalSql: document.querySelector("#approval-sql"),
  approvalReason: document.querySelector("#approval-reason"),
  approveButton: document.querySelector("#approve-button"),
  rejectButton: document.querySelector("#reject-button"),
};

function initializeStages() {
  elements.workflowSteps.replaceChildren(
    ...STAGES.map(([node, label]) => {
      const item = document.createElement("li");
      item.dataset.node = node;
      item.textContent = label;
      return item;
    }),
  );
}

function makeRequestId() {
  if (globalThis.crypto?.randomUUID) {
    return `请求-${crypto.randomUUID()}`;
  }
  return `请求-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function loadSession() {
  try {
    const [healthResponse, sessionResponse] = await Promise.all([
      fetch("/health"),
      fetch("/session"),
    ]);
    if (!healthResponse.ok || !sessionResponse.ok) {
      throw new Error("服务状态不可用");
    }
    state.session = await sessionResponse.json();
    elements.serverDot.className = "status-dot online";
    elements.serverStatus.textContent = "服务在线";
    elements.sessionRole.textContent = ROLE_LABELS[state.session.role] || "当前用户";
    elements.sessionUser.textContent = "已认证";
  } catch (error) {
    elements.serverDot.className = "status-dot offline";
    elements.serverStatus.textContent = "服务离线";
    elements.sessionRole.textContent = "--";
    elements.sessionUser.textContent = "无法读取登录状态";
    elements.runButton.disabled = true;
  }
}

function setRunning(running) {
  state.running = running;
  elements.runButton.disabled = running || !state.session;
  elements.runButton.textContent = running ? "分析进行中" : "运行分析";
}

function resetOutput() {
  for (const item of elements.workflowSteps.children) {
    item.className = "";
  }
  elements.workflowMessage.textContent = "分析请求已发送";
  elements.answerText.textContent = "正在等待工作流返回可信结果。";
  elements.answerText.className = "answer-text empty";
  elements.resultStatus.textContent = "运行中";
  elements.degradation.hidden = true;
  elements.chartStage.innerHTML = '<p class="empty-state">正在准备图表</p>';
  elements.chartKind.textContent = "--";
  elements.tableStage.innerHTML = '<p class="empty-state">正在查询数据</p>';
  elements.rowCount.textContent = "0 行";
  elements.planOutput.textContent = "等待计划";
  elements.evidenceList.innerHTML = "<li>等待证据</li>";
  elements.retryCount.textContent = "重试 0 次";
  elements.traceButton.disabled = true;
  elements.traceBand.hidden = true;
  elements.approvalPane.hidden = true;
  state.approval = null;
}

function setActiveStage(node) {
  const normalized = stageAliases[node] || node;
  const index = STAGES.findIndex(([stage]) => stage === normalized);
  if (index < 0) return;
  [...elements.workflowSteps.children].forEach((item, itemIndex) => {
    item.className = itemIndex < index ? "done" : itemIndex === index ? "active" : "";
  });
}

function completeStages() {
  for (const item of elements.workflowSteps.children) {
    item.className = "done";
  }
}

function parseSseBlock(block) {
  const lines = block.split("\n");
  const data = lines
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  return data ? JSON.parse(data) : null;
}

async function streamAnalysis(payload) {
  const response = await fetch("/analysis/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `请求失败：HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    buffer = buffer.replaceAll("\r\n", "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const event = parseSseBlock(block);
      if (event) handleStreamEvent(event);
      boundary = buffer.indexOf("\n\n");
    }
    if (done) break;
  }
}

function handleStreamEvent(event) {
  elements.workflowMessage.textContent = event.message;
  if (event.node) setActiveStage(event.node);

  if (event.event === "result" && event.response) {
    completeStages();
    renderResult(event.response);
  } else if (event.event === "approval_required" && event.approval) {
    renderApproval(event.approval);
  } else if (event.event === "rejected" && event.rejection) {
    renderRejection(event.rejection);
  } else if (event.event === "assistant_message" && event.assistant) {
    renderAssistant(event.assistant);
  } else if (event.event === "error") {
    renderError(event.message);
  }
}

function localizeField(field) {
  return FIELD_LABELS[field] || "其他数据";
}

function localizeValue(value) {
  if (Array.isArray(value)) return value.map(localizeValue).join("、");
  if (typeof value === "string") return VALUE_LABELS[value] || value;
  return String(value);
}

function formatPlan(plan) {
  if (!plan) return "未生成分析计划";
  const metrics = (plan.metrics || []).map(localizeField).join("、") || "未指定";
  const dimensions = (plan.dimensions || []).map(localizeField).join("、") || "不分组";
  const filters = (plan.filters || []).map((item) => {
    const operator = item.operator === "in" ? "属于" : "等于";
    return `${localizeField(item.field)}${operator}${localizeValue(item.value)}`;
  }).join("；") || "无额外筛选";
  const timeRange = plan.time_range?.days
    ? `最近 ${plan.time_range.days} 天`
    : "未限定";
  const sort = (plan.sort || []).map((item) => {
    const direction = item.direction === "ascending" ? "从低到高" : "从高到低";
    return `${localizeField(item.field)}（${direction}）`;
  }).join("；") || "不额外排序";
  return [
    `分析目标：${plan.analysis_goal}`,
    `计算指标：${metrics}`,
    `分组维度：${dimensions}`,
    `筛选条件：${filters}`,
    `时间范围：${timeRange}`,
    `排序方式：${sort}`,
    `返回上限：${plan.limit} 行`,
  ].join("\n");
}

function localizeEvidence(sourceId) {
  const metricMatch = /^metric\.([a-z_]+)(?:\.v(\d+))?$/i.exec(sourceId);
  if (metricMatch) {
    const version = metricMatch[2] ? `（第 ${metricMatch[2]} 版）` : "";
    return `指标口径：${localizeField(metricMatch[1])}${version}`;
  }
  const tableLabels = {
    orders: "订单表",
    products: "商品表",
    order_items: "订单明细表",
    refunds: "退款表",
  };
  const joinMatch = /^schema\.join\.([a-z_]+)\.([a-z_]+)$/i.exec(sourceId);
  if (joinMatch) {
    const left = tableLabels[joinMatch[1]] || "业务数据表";
    const right = tableLabels[joinMatch[2]] || "业务数据表";
    return `关联规则：${left}与${right}`;
  }
  const tableMatch = /^schema\.([a-z_]+)$/i.exec(sourceId);
  if (tableMatch) return `数据来源：${tableLabels[tableMatch[1]] || "业务数据表"}`;
  return "业务规则证据";
}

function localizeErrorMessage(message) {
  const text = String(message || "").trim();
  const normalized = text.toLowerCase();
  if (normalized.includes("does not support dimensions")) {
    return "当前指标不支持所选分组维度，请调整指标或分组方式。";
  }
  if (normalized.includes("already bound") || normalized.includes("different analysis input")) {
    return "这个请求编号已经对应其他问题，请重新发起分析。";
  }
  if (normalized.includes("timeout") || normalized.includes("timed out") || normalized.includes("deadline")) {
    return "分析服务响应超时，请稍后重试。";
  }
  if (normalized.includes("ollama") || normalized.includes("model invocation")) {
    return "分析模型暂时不可用，请稍后重试。";
  }
  if (normalized.includes("query reads sensitive columns")) {
    return "查询包含敏感字段，需要管理员审批后才能执行。";
  }
  if (normalized.includes("result limit") || normalized.includes("approval threshold")) {
    return "本次查询返回范围较大，需要管理员审批后才能执行。";
  }
  if (normalized.includes("database") || normalized.includes("postgres") || normalized.includes("connection")) {
    return "数据服务暂时不可用，请稍后重试。";
  }
  if (normalized.includes("sql") || normalized.includes("unsafe") || normalized.includes("validation failed")) {
    return "生成的查询未通过安全或业务校验，系统已停止执行。";
  }
  if (normalized.includes("http") || normalized.includes("request failed")) {
    return "请求未能完成，请稍后重试。";
  }
  if (/[一-鿿]/.test(text) && !/[A-Za-z]{3,}/.test(text)) return text;
  return "内部处理未能完成，请调整问题后重试。";
}

function renderResult(result) {
  state.requestId = result.request_id;
  elements.requestId.textContent = state.requestId;
  elements.answerText.textContent = result.answer;
  elements.answerText.className = "answer-text";
  elements.resultStatus.textContent = result.status === "degraded" ? "已降级返回" : "分析成功";
  elements.degradation.hidden = !result.degradation_reason;
  elements.degradation.textContent = result.degradation_reason || "";
  elements.planOutput.textContent = formatPlan(result.plan);
  elements.retryCount.textContent = `重试 ${result.retry_count} 次`;
  renderEvidence(result.evidence_source_ids);
  renderTable(result.rows, result.plan);
  renderChart(result.chart_spec, result.rows);
  elements.traceButton.disabled = false;
  setRunning(false);
}

function renderEvidence(sourceIds) {
  elements.evidenceList.replaceChildren(
    ...(sourceIds.length ? sourceIds : ["无检索证据"]).map((sourceId) => {
      const item = document.createElement("li");
      item.textContent = localizeEvidence(sourceId);
      return item;
    }),
  );
}

function renderTable(rows, plan = null) {
  elements.rowCount.textContent = `${rows.length} 行`;
  if (!rows.length) {
    elements.tableStage.innerHTML = '<p class="empty-state">查询成功，结果为 0 行</p>';
    return;
  }
  const availableColumns = Object.keys(rows[0]);
  const preferredColumns = plan
    ? [...(plan.dimensions || []), ...(plan.metrics || [])]
    : [];
  const columns = [
    ...preferredColumns.filter((column) => availableColumns.includes(column)),
    ...availableColumns.filter((column) => !preferredColumns.includes(column)),
  ];
  const table = document.createElement("table");
  const head = table.createTHead().insertRow();
  columns.forEach((column) => {
    const cell = document.createElement("th");
    cell.textContent = localizeField(column);
    head.append(cell);
  });
  const body = table.createTBody();
  rows.forEach((row) => {
    const tableRow = body.insertRow();
    columns.forEach((column) => {
      const cell = tableRow.insertCell();
      cell.textContent = formatCell(row[column]);
    });
  });
  elements.tableStage.replaceChildren(table);
}

function formatCell(value) {
  if (value === null || value === undefined) return "--";
  if (typeof value === "object") return JSON.stringify(value);
  return localizeValue(value);
}

function numericValue(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function renderChart(spec, rows) {
  if (!spec || !rows.length) {
    elements.chartKind.textContent = "--";
    elements.chartStage.innerHTML = '<p class="empty-state">当前结果没有图表规格</p>';
    return;
  }
  elements.chartKind.textContent = CHART_TYPE_LABELS[spec.chart_type] || "数据图表";
  if (spec.chart_type === "kpi") {
    const field = spec.y_fields[0];
    const value = document.createElement("div");
    value.className = "kpi-value";
    value.textContent = formatCell(rows[0][field]);
    const label = document.createElement("span");
    label.textContent = `${spec.title} / ${localizeField(field)}`;
    value.append(label);
    elements.chartStage.replaceChildren(value);
    return;
  }

  const canvas = document.createElement("canvas");
  canvas.setAttribute("aria-label", spec.title);
  canvas.setAttribute("role", "img");
  elements.chartStage.replaceChildren(canvas);
  requestAnimationFrame(() => drawChart(canvas, spec, rows));
}

function drawChart(canvas, spec, rows) {
  const ratio = globalThis.devicePixelRatio || 1;
  const width = Math.max(canvas.clientWidth, 320);
  const height = 280;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  context.clearRect(0, 0, width, height);

  const xField = spec.x_field;
  const yField = spec.y_fields[0];
  const labels = rows.map((row) => formatCell(row[xField]));
  const values = rows.map((row) => numericValue(row[yField]));
  const maxValue = Math.max(...values, 1);
  const plot = { left: 52, right: 18, top: 25, bottom: 52 };
  const plotWidth = width - plot.left - plot.right;
  const plotHeight = height - plot.top - plot.bottom;

  context.strokeStyle = "#d9dee2";
  context.fillStyle = "#667078";
  context.font = '11px "Microsoft YaHei", sans-serif';
  context.lineWidth = 1;
  for (let tick = 0; tick <= 4; tick += 1) {
    const y = plot.top + (plotHeight * tick) / 4;
    const value = maxValue * (1 - tick / 4);
    context.beginPath();
    context.moveTo(plot.left, y);
    context.lineTo(width - plot.right, y);
    context.stroke();
    context.fillText(formatCompactNumber(value), 4, y + 4);
  }

  if (spec.chart_type === "line") {
    drawLine(context, labels, values, maxValue, plot, plotWidth, plotHeight);
  } else {
    drawBars(context, labels, values, maxValue, plot, plotWidth, plotHeight);
  }
}

function drawBars(context, labels, values, maxValue, plot, plotWidth, plotHeight) {
  const slot = plotWidth / Math.max(values.length, 1);
  const barWidth = Math.max(12, Math.min(52, slot * 0.58));
  values.forEach((value, index) => {
    const barHeight = (value / maxValue) * plotHeight;
    const x = plot.left + slot * index + (slot - barWidth) / 2;
    const y = plot.top + plotHeight - barHeight;
    context.fillStyle = index % 2 === 0 ? "#176b5b" : "#2563a9";
    context.fillRect(x, y, barWidth, barHeight);
    context.fillStyle = "#3f484e";
    context.textAlign = "center";
    context.fillText(truncate(labels[index], 9), x + barWidth / 2, plot.top + plotHeight + 20);
  });
  context.textAlign = "start";
}

function drawLine(context, labels, values, maxValue, plot, plotWidth, plotHeight) {
  const step = values.length > 1 ? plotWidth / (values.length - 1) : plotWidth;
  context.strokeStyle = "#2563a9";
  context.fillStyle = "#2563a9";
  context.lineWidth = 2;
  context.beginPath();
  values.forEach((value, index) => {
    const x = plot.left + (values.length > 1 ? step * index : plotWidth / 2);
    const y = plot.top + plotHeight - (value / maxValue) * plotHeight;
    if (index === 0) context.moveTo(x, y);
    else context.lineTo(x, y);
  });
  context.stroke();
  values.forEach((value, index) => {
    const x = plot.left + (values.length > 1 ? step * index : plotWidth / 2);
    const y = plot.top + plotHeight - (value / maxValue) * plotHeight;
    context.beginPath();
    context.arc(x, y, 4, 0, Math.PI * 2);
    context.fill();
    context.fillStyle = "#3f484e";
    context.textAlign = "center";
    context.fillText(truncate(labels[index], 9), x, plot.top + plotHeight + 20);
    context.fillStyle = "#2563a9";
  });
  context.textAlign = "start";
}

function formatCompactNumber(value) {
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1, notation: "compact" }).format(value);
}

function truncate(value, length) {
  return value.length > length ? `${value.slice(0, length - 1)}…` : value;
}

function renderApproval(approval) {
  state.approval = approval;
  state.requestId = approval.request_id;
  elements.requestId.textContent = state.requestId;
  elements.resultStatus.textContent = "等待人工审批";
  elements.answerText.textContent = "查询已暂停，审批通过后才会访问数据库。";
  elements.answerText.className = "answer-text";
  elements.chartStage.innerHTML = '<p class="empty-state">审批前不生成数据图表</p>';
  elements.tableStage.innerHTML = '<p class="empty-state">审批前不访问数据库</p>';
  elements.rowCount.textContent = "0 行";
  elements.chartKind.textContent = "--";
  elements.planOutput.textContent = "等待审批，不展示分析计划";
  elements.evidenceList.innerHTML = "<li>审批前不展示业务证据</li>";
  elements.retryCount.textContent = "重试 0 次";
  elements.approvalReasons.textContent = approval.reasons.map(localizeErrorMessage).join("；");
  elements.approvalSql.textContent = approval.sql;
  elements.approvalPane.hidden = false;
  const isAdmin = state.session?.role === "admin";
  elements.approveButton.disabled = !isAdmin;
  elements.rejectButton.disabled = !isAdmin;
  elements.traceButton.disabled = false;
  setRunning(false);
}

function renderRejection(rejection) {
  state.requestId = rejection.request_id;
  elements.requestId.textContent = state.requestId;
  elements.resultStatus.textContent = "请求已拒绝";
  elements.answerText.textContent = rejection.reason;
  elements.answerText.className = "answer-text";
  elements.chartStage.innerHTML = '<p class="empty-state">拒绝请求没有数据图表</p>';
  elements.tableStage.innerHTML = '<p class="empty-state">拒绝请求未访问数据库</p>';
  elements.rowCount.textContent = "0 行";
  elements.chartKind.textContent = "--";
  elements.planOutput.textContent = "请求在生成分析计划前被拒绝";
  elements.evidenceList.innerHTML = "<li>未检索业务证据</li>";
  elements.retryCount.textContent = "重试 0 次";
  elements.workflowMessage.textContent = "工作流在安全边界终止";
  elements.traceButton.disabled = false;
  setRunning(false);
}

function renderAssistant(assistant) {
  state.requestId = assistant.request_id;
  elements.requestId.textContent = state.requestId;
  for (const item of elements.workflowSteps.children) item.className = "";
  elements.resultStatus.textContent = assistant.status === "needs_clarification"
    ? "需要补充信息"
    : "助手答复";
  elements.answerText.textContent = assistant.answer;
  elements.answerText.className = "answer-text";
  elements.workflowMessage.textContent = "请求未进入数据查询流程";
  elements.chartKind.textContent = "--";
  elements.chartStage.innerHTML = '<p class="empty-state">本次答复不需要数据图表</p>';
  elements.tableStage.innerHTML = '<p class="empty-state">本次答复未访问数据库</p>';
  elements.rowCount.textContent = "0 行";
  elements.planOutput.textContent = "未生成分析计划";
  elements.evidenceList.innerHTML = "<li>未检索业务证据</li>";
  elements.retryCount.textContent = "重试 0 次";
  elements.traceButton.disabled = false;
  setRunning(false);
}

function renderError(message) {
  elements.resultStatus.textContent = "分析失败";
  elements.answerText.textContent = localizeErrorMessage(message);
  elements.answerText.className = "answer-text";
  elements.workflowMessage.textContent = "请求未能完成";
  elements.chartKind.textContent = "--";
  elements.chartStage.innerHTML = '<p class="empty-state">分析失败，未生成图表</p>';
  elements.tableStage.innerHTML = '<p class="empty-state">分析失败，未返回可信数据</p>';
  elements.rowCount.textContent = "0 行";
  elements.planOutput.textContent = "未生成分析计划";
  elements.evidenceList.innerHTML = "<li>未检索业务证据</li>";
  elements.retryCount.textContent = "重试 0 次";
  elements.approvalPane.hidden = true;
  elements.traceButton.disabled = !state.requestId;
  setRunning(false);
}

async function resolveApproval(decision) {
  if (!state.approval) return;
  const reason = elements.approvalReason.value.trim();
  if (decision === "reject" && !reason) {
    elements.approvalReason.focus();
    return;
  }
  elements.approveButton.disabled = true;
  elements.rejectButton.disabled = true;
  try {
    const response = await fetch(`/analysis/${encodeURIComponent(state.approval.request_id)}/approval`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, reason: reason || null }),
    });
    const outcome = await response.json();
    if (!response.ok) throw new Error(outcome.detail || "审批失败");
    elements.approvalPane.hidden = true;
    if (outcome.answer) renderResult(outcome);
    else renderRejection(outcome);
  } catch (error) {
    renderError(error.message);
    elements.approveButton.disabled = false;
    elements.rejectButton.disabled = false;
  }
}

async function loadTrace() {
  if (!state.requestId) return;
  elements.traceButton.disabled = true;
  try {
    const response = await fetch(`/analysis/${encodeURIComponent(state.requestId)}/trace`);
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || "执行记录读取失败");
    renderTrace(body.events);
    elements.traceBand.hidden = false;
    elements.traceBand.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    elements.traceList.textContent = localizeErrorMessage(error.message);
    elements.traceBand.hidden = false;
  } finally {
    elements.traceButton.disabled = false;
  }
}

function renderTrace(events) {
  if (!events.length) {
    elements.traceList.textContent = "当前请求没有执行记录。";
    return;
  }
  elements.traceList.replaceChildren(
    ...events.map((event) => {
      const row = document.createElement("div");
      row.className = "trace-event";
      const component = document.createElement("code");
      component.textContent = TRACE_COMPONENT_LABELS[event.component] || "内部处理步骤";
      const status = document.createElement("span");
      status.className = `trace-status ${event.status}`;
      status.textContent = TRACE_STATUS_LABELS[event.status] || "处理中";
      const duration = document.createElement("span");
      duration.textContent = event.duration_ms === null ? "--" : `${event.duration_ms} 毫秒`;
      const detail = document.createElement("span");
      detail.textContent = event.error_message
        ? localizeErrorMessage(event.error_message)
        : `第 ${event.attempt} 次处理`;
      row.append(component, status, duration, detail);
      return row;
    }),
  );
}

elements.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.running || !state.session) return;
  state.requestId = makeRequestId();
  elements.requestId.textContent = state.requestId;
  resetOutput();
  setRunning(true);
  try {
    await streamAnalysis({
      request_id: state.requestId,
      user_id: state.session.user_id,
      question: elements.question.value.trim(),
      max_rows: Number(elements.maxRows.value),
    });
  } catch (error) {
    renderError(error.message);
  } finally {
    if (state.running) setRunning(false);
  }
});

document.querySelectorAll("[data-question]").forEach((button) => {
  button.addEventListener("click", () => {
    elements.question.value = button.dataset.question;
    elements.question.focus();
  });
});

elements.approveButton.addEventListener("click", () => resolveApproval("approve"));
elements.rejectButton.addEventListener("click", () => resolveApproval("reject"));
elements.traceButton.addEventListener("click", loadTrace);
elements.closeTrace.addEventListener("click", () => {
  elements.traceBand.hidden = true;
});

initializeStages();
loadSession();
