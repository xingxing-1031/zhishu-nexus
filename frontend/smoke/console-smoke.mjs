const baseUrl = new URL(process.env.VITE_BASE_URL || "http://127.0.0.1:8000/");

async function get(path) {
  const response = await fetch(new URL(path, baseUrl));
  const body = await response.text();
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}: ${body.slice(0, 160)}`);
  }
  return { response, body };
}

const home = await get("/");
for (const marker of ["零售运营分析台", "/static/assets/"]) {
  if (!home.body.includes(marker)) throw new Error(`homepage is missing marker: ${marker}`);
}

const scriptPath = home.body.match(/src="([^"]+\.js)"/)?.[1];
if (!scriptPath) throw new Error("homepage does not reference a JavaScript bundle");
const script = await get(scriptPath);
if (!script.body.includes("demo-path-rail")) throw new Error("bundle is missing guided demo paths");

const session = await get("/session");
const sessionData = JSON.parse(session.body);
if (sessionData.public_demo_mode !== true) throw new Error("public demo session is not in public mode");
if (sessionData.trace_visible !== false) throw new Error("public demo exposes Trace visibility");

const overview = await get("/demo/overview");
const overviewData = JSON.parse(overview.body);
if (overviewData.order_count < 100) throw new Error("demo dataset has fewer than 100 orders");
if (overviewData.channel_count < 4) throw new Error("demo dataset has fewer than four channels");
if (overviewData.refund_count < 10) throw new Error("demo dataset has too few refund records");

console.log(JSON.stringify({
  base_url: baseUrl.toString(),
  bundle: scriptPath,
  public_demo_mode: sessionData.public_demo_mode,
  trace_visible: sessionData.trace_visible,
  overview: overviewData,
}));
