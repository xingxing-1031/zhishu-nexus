const baseUrl = new URL(process.env.VITE_BASE_URL || "http://127.0.0.1:8000/");

let sessionCookie = "";

async function get(path) {
  const response = await fetch(new URL(path, baseUrl), {
    headers: sessionCookie ? { Cookie: sessionCookie } : {},
  });
  const body = await response.text();
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}: ${body.slice(0, 160)}`);
  }
  return { response, body };
}

const home = await get("/");
for (const marker of ["企析 · 企业专业智能助理", "/static/assets/"]) {
  if (!home.body.includes(marker)) throw new Error(`homepage is missing marker: ${marker}`);
}

const scriptPath = home.body.match(/src="([^"]+\.js)"/)?.[1];
if (!scriptPath) throw new Error("homepage does not reference a JavaScript bundle");
const script = await get(scriptPath);
if (script.body.includes("demo-path-rail")) throw new Error("bundle still contains the removed guided demo rail");
for (const marker of ["最近对话", "智能工作台", "任务详情", "基于结果追问", "analyst-demo", "admin-demo"]) {
  if (!script.body.includes(marker)) throw new Error(`bundle is missing workspace marker: ${marker}`);
}

let session;
try {
  session = await get("/session");
} catch (error) {
  if (!String(error).includes("returned 401")) throw error;
  const login = await fetch(new URL("/auth/login", baseUrl), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "analyst-demo", password: "DemoAnalyst2026!" }),
  });
  if (!login.ok) throw new Error(`demo login returned ${login.status}: ${(await login.text()).slice(0, 160)}`);
  sessionCookie = login.headers.get("set-cookie")?.split(";", 1)[0] || "";
  if (!sessionCookie) throw new Error("demo login did not return a session cookie");
  session = await get("/session");
}
const sessionData = JSON.parse(session.body);
if (sessionData.public_demo_mode !== true) throw new Error("public demo session is not in public mode");
if (sessionData.role !== "analyst") throw new Error("public demo analyst login has the wrong role");

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
