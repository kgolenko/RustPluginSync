const statusCards = document.getElementById("statusCards");
const globalStatus = document.getElementById("globalStatus");
const logStream = document.getElementById("logStream");
const levelFilter = document.getElementById("levelFilter");
const serverFilter = document.getElementById("serverFilter");
const btnPause = document.getElementById("btnPause");
const btnResume = document.getElementById("btnResume");
const btnRunOnce = document.getElementById("btnRunOnce");
const toggleDry = document.getElementById("toggleDry");
const btnClear = document.getElementById("btnClear");
const btnOpenConfig = document.getElementById("btnOpenConfig");
const btnValidate = document.getElementById("btnValidate");
const validateStatus = document.getElementById("validateStatus");
const configText = document.getElementById("configText");
const historyContainer = document.getElementById("history");

let currentConfig = null;
let eventSource = null;

function setGlobalStatus(servers) {
  const anyError = servers.some((s) => s.last_status === "ERROR");
  const anyUnknown = servers.some((s) => s.last_status === "UNKNOWN");
  if (anyError) {
    globalStatus.textContent = "ERROR";
    globalStatus.className = "status-pill err";
    return;
  }
  if (anyUnknown) {
    globalStatus.textContent = "UNKNOWN";
    globalStatus.className = "status-pill";
    return;
  }
  globalStatus.textContent = "OK";
  globalStatus.className = "status-pill ok";
}

function renderStatus(servers) {
  statusCards.innerHTML = "";
  servers.forEach((server) => {
    const row = document.createElement("div");
    row.className = "status-row";
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.innerHTML = `
      <div><strong>${server.name}</strong></div>
      <div class="tag">Commit: ${server.last_commit || "—"}</div>
      <div class="tag">Last deploy: ${server.last_deploy_time || "—"}</div>
      <div class="tag">Last run: ${server.last_run_time || "—"}</div>
    `;
    const status = document.createElement("div");
    status.className = server.last_status === "ERROR" ? "err" : "ok";
    status.textContent = server.last_status || "UNKNOWN";
    row.appendChild(meta);
    row.appendChild(status);
    statusCards.appendChild(row);
  });
  setGlobalStatus(servers);
}

function renderHistory(items) {
  historyContainer.innerHTML = "";
  items.slice().reverse().forEach((item) => {
    const div = document.createElement("div");
    div.className = "history-item";
    div.innerHTML = `
      <div><strong>${item.server}</strong> — ${item.commit}</div>
      <div class="line">Автор: ${item.author || "—"}</div>
      <div class="line">Файлы: ${item.files.length ? item.files.join(", ") : "—"}</div>
      <div class="line">Длительность: ${item.duration_seconds.toFixed(2)}s</div>
      <div class="line">Время: ${item.timestamp}</div>
    `;
    historyContainer.appendChild(div);
  });
}

async function fetchStatus() {
  const res = await fetch("/api/status");
  const data = await res.json();
  renderStatus(data.servers);
  toggleDry.checked = data.dry_run;
  updateServerFilter(data.servers);
}

async function fetchHistory() {
  const res = await fetch("/api/history");
  const data = await res.json();
  renderHistory(data.items || []);
}

async function fetchConfig() {
  const res = await fetch("/api/config");
  currentConfig = await res.json();
  configText.value = JSON.stringify(currentConfig, null, 2);
}

function updateServerFilter(servers) {
  const existing = new Set(Array.from(serverFilter.options).map((o) => o.value));
  servers.forEach((s) => {
    if (!existing.has(s.name)) {
      const opt = document.createElement("option");
      opt.value = s.name;
      opt.textContent = s.name;
      serverFilter.appendChild(opt);
    }
  });
}

function startLogStream() {
  if (eventSource) {
    eventSource.close();
  }
  const level = encodeURIComponent(levelFilter.value || "");
  const server = encodeURIComponent(serverFilter.value || "");
  eventSource = new EventSource(`/api/logs/stream?level=${level}&server=${server}&tail=200`);
  eventSource.onmessage = (event) => {
    logStream.textContent += event.data + "\n";
    logStream.scrollTop = logStream.scrollHeight;
  };
  eventSource.onerror = () => {
    eventSource.close();
  };
}

btnPause.addEventListener("click", async () => {
  await fetch("/api/pause", { method: "POST" });
  await fetchStatus();
});

btnResume.addEventListener("click", async () => {
  await fetch("/api/resume", { method: "POST" });
  await fetchStatus();
});

btnRunOnce.addEventListener("click", async () => {
  await fetch("/api/run-once", { method: "POST" });
});

toggleDry.addEventListener("change", async (e) => {
  await fetch("/api/dry-run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled: e.target.checked }),
  });
});

btnClear.addEventListener("click", () => {
  logStream.textContent = "";
});

btnOpenConfig.addEventListener("click", async () => {
  await fetch("/api/open-config", { method: "POST" });
});

btnValidate.addEventListener("click", async () => {
  if (!currentConfig) return;
  const res = await fetch("/api/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(currentConfig),
  });
  const data = await res.json();
  validateStatus.textContent = data.ok ? "OK" : `ERROR: ${data.errors.join("; ")}`;
});

levelFilter.addEventListener("change", startLogStream);
serverFilter.addEventListener("change", startLogStream);

async function boot() {
  await fetchStatus();
  await fetchHistory();
  await fetchConfig();
  startLogStream();
  setInterval(fetchStatus, 5000);
  setInterval(fetchHistory, 10000);
}

boot();
