const statusCards = document.getElementById("statusCards");
const logStream = document.getElementById("logStream");
const levelFilter = document.getElementById("levelFilter");
const serverFilter = document.getElementById("serverFilter");
const btnRunOnce = document.getElementById("btnRunOnce");
const btnToggleSync = document.getElementById("btnToggleSync");
const toggleDry = document.getElementById("toggleDry");
const btnClear = document.getElementById("btnClear");
const btnOpenConfig = document.getElementById("btnOpenConfig");
const btnValidate = document.getElementById("btnValidate");
const validateStatus = document.getElementById("validateStatus");
const historyContainer = document.getElementById("history");
const syncDot = document.getElementById("syncDot");
const syncStatusText = document.getElementById("syncStatusText");
const tabs = document.querySelectorAll(".tab");
const panels = document.querySelectorAll(".tab-panel");
const configForm = document.getElementById("configForm");
const btnAddServer = document.getElementById("btnAddServer");
const btnSaveConfig = document.getElementById("btnSaveConfig");
const saveStatus = document.getElementById("saveStatus");

let currentConfig = null;
let eventSource = null;
let pausedState = false;

function setSyncStatus(paused) {
  pausedState = paused;
  if (paused) {
    syncDot.classList.add("paused");
    syncStatusText.textContent = "Paused";
    btnToggleSync.textContent = "Resume";
  } else {
    syncDot.classList.remove("paused");
    syncStatusText.textContent = "Running";
    btnToggleSync.textContent = "Pause";
  }
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
      <div class="tag">Duration: ${server.last_duration_seconds ? server.last_duration_seconds.toFixed(2) + "s" : "—"}</div>
      <div class="tag">Error: ${server.last_error || "—"}</div>
    `;
    const status = document.createElement("div");
    status.className = server.last_status === "ERROR" ? "err" : "ok";
    status.textContent = server.last_status || "UNKNOWN";
    row.appendChild(meta);
    row.appendChild(status);
    statusCards.appendChild(row);
  });
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

function selectTab(tabId) {
  tabs.forEach((tab) => tab.classList.remove("active"));
  panels.forEach((panel) => panel.classList.remove("active"));
  const activeTab = document.querySelector(`.tab[data-tab="${tabId}"]`);
  const activePanel = document.getElementById(`tab-${tabId}`);
  if (activeTab && activePanel) {
    activeTab.classList.add("active");
    activePanel.classList.add("active");
  }
}

function createRow(label, input) {
  const labelEl = document.createElement("label");
  labelEl.textContent = label;
  const row = document.createElement("div");
  row.className = "form-grid";
  row.appendChild(labelEl);
  row.appendChild(input);
  return row;
}

function textInput(value = "") {
  const input = document.createElement("input");
  input.type = "text";
  input.value = value;
  return input;
}

function numberInput(value = "") {
  const input = document.createElement("input");
  input.type = "number";
  input.value = value;
  return input;
}

function checkboxInput(value = false) {
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = value;
  return input;
}

function renderConfigForm(cfg) {
  currentConfig = cfg;
  configForm.innerHTML = "";

  const globalSection = document.createElement("div");
  globalSection.className = "form-section";
  globalSection.innerHTML = `<div class="section-header">Global settings</div>`;

  const fields = [
    ["LogPath", textInput(cfg.LogPath || "")],
    ["IntervalSeconds", numberInput(cfg.IntervalSeconds || 120)],
    ["Branch", textInput(cfg.Branch || "main")],
    ["GitRetryCount", numberInput(cfg.GitRetryCount || 3)],
    ["GitRetryDelaySeconds", numberInput(cfg.GitRetryDelaySeconds || 10)],
    ["GitTimeoutSeconds", numberInput(cfg.GitTimeoutSeconds || 30)],
    ["StartupDelaySeconds", numberInput(cfg.StartupDelaySeconds || 1)],
    ["DryRun", checkboxInput(cfg.DryRun || false)],
  ];

  fields.forEach(([label, input]) => {
    input.dataset.key = label;
    globalSection.appendChild(createRow(label, input));
  });

  configForm.appendChild(globalSection);

  const servers = Array.isArray(cfg.Servers) ? cfg.Servers : [];
  servers.forEach((server, idx) => {
    const section = document.createElement("div");
    section.className = "form-section";
    section.dataset.index = idx;

    const header = document.createElement("div");
    header.className = "section-header";
    header.innerHTML = `<span>Server ${idx + 1}</span>`;
    const removeBtn = document.createElement("button");
    removeBtn.className = "secondary";
    removeBtn.textContent = "Remove";
    removeBtn.addEventListener("click", () => {
      section.remove();
    });
    header.appendChild(removeBtn);
    section.appendChild(header);

    const serverFields = [
      ["Name", textInput(server.Name || "")],
      ["RepoPath", textInput(server.RepoPath || "")],
      ["ServerRoot", textInput(server.ServerRoot || "")],
      ["PluginsTarget", textInput(server.PluginsTarget || "")],
      ["ConfigTarget", textInput(server.ConfigTarget || "")],
      ["Branch", textInput(server.Branch || "")],
      ["PluginsPattern", textInput((server.PluginsPattern || []).join(", "))],
      ["ConfigPattern", textInput((server.ConfigPattern || []).join(", "))],
      ["ExcludePatterns", textInput((server.ExcludePatterns || []).join(", "))],
      ["DeleteExtraneous", checkboxInput(server.DeleteExtraneous || false)],
      ["Enabled", checkboxInput(server.Enabled !== false)],
    ];

    serverFields.forEach(([label, input]) => {
      input.dataset.key = label;
      section.appendChild(createRow(label, input));
    });

    configForm.appendChild(section);
  });
}

function buildConfigFromForm() {
  const globalSection = configForm.querySelector(".form-section");
  const getGlobal = (key) => {
    const input = globalSection.querySelector(`[data-key="${key}"]`);
    if (!input) return null;
    if (input.type === "checkbox") return input.checked;
    if (input.type === "number") return Number(input.value || 0);
    return input.value.trim();
  };

  const newConfig = {
    LogPath: getGlobal("LogPath"),
    IntervalSeconds: getGlobal("IntervalSeconds"),
    Branch: getGlobal("Branch"),
    GitRetryCount: getGlobal("GitRetryCount"),
    GitRetryDelaySeconds: getGlobal("GitRetryDelaySeconds"),
    GitTimeoutSeconds: getGlobal("GitTimeoutSeconds"),
    StartupDelaySeconds: getGlobal("StartupDelaySeconds"),
    DryRun: getGlobal("DryRun"),
    Servers: [],
  };

  const serverSections = Array.from(configForm.querySelectorAll(".form-section")).slice(1);
  serverSections.forEach((section) => {
    const getServer = (key) => {
      const input = section.querySelector(`[data-key="${key}"]`);
      if (!input) return null;
      if (input.type === "checkbox") return input.checked;
      if (input.type === "number") return Number(input.value || 0);
      return input.value.trim();
    };

    const splitList = (value) => {
      if (!value) return null;
      const parts = value.split(",").map((p) => p.trim()).filter(Boolean);
      return parts.length ? parts : null;
    };

    const server = {
      Name: getServer("Name"),
      RepoPath: getServer("RepoPath"),
      ServerRoot: getServer("ServerRoot"),
    };

    const pluginsTarget = getServer("PluginsTarget");
    const configTarget = getServer("ConfigTarget");
    const branch = getServer("Branch");
    const pluginsPattern = splitList(getServer("PluginsPattern"));
    const configPattern = splitList(getServer("ConfigPattern"));
    const excludePatterns = splitList(getServer("ExcludePatterns"));

    if (pluginsTarget) server.PluginsTarget = pluginsTarget;
    if (configTarget) server.ConfigTarget = configTarget;
    if (branch) server.Branch = branch;
    if (pluginsPattern) server.PluginsPattern = pluginsPattern;
    if (configPattern) server.ConfigPattern = configPattern;
    if (excludePatterns) server.ExcludePatterns = excludePatterns;

    server.DeleteExtraneous = getServer("DeleteExtraneous");
    server.Enabled = getServer("Enabled");

    newConfig.Servers.push(server);
  });

  return newConfig;
}

async function fetchStatus() {
  const res = await fetch("/api/status");
  const data = await res.json();
  renderStatus(data.servers);
  toggleDry.checked = data.dry_run;
  updateServerFilter(data.servers);
  setSyncStatus(data.paused);
}

async function fetchHistory() {
  const res = await fetch("/api/history");
  const data = await res.json();
  renderHistory(data.items || []);
}

async function fetchConfig() {
  const res = await fetch("/api/config");
  const cfg = await res.json();
  renderConfigForm(cfg);
}

btnRunOnce.addEventListener("click", async () => {
  await fetch("/api/run-once", { method: "POST" });
});

btnToggleSync.addEventListener("click", async () => {
  if (pausedState) {
    await fetch("/api/resume", { method: "POST" });
  } else {
    await fetch("/api/pause", { method: "POST" });
  }
  await fetchStatus();
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
  const payload = buildConfigFromForm();
  const res = await fetch("/api/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  validateStatus.textContent = data.ok ? "OK" : `ERROR: ${data.errors.join("; ")}`;
});

btnAddServer.addEventListener("click", () => {
  if (!currentConfig) return;
  currentConfig.Servers = currentConfig.Servers || [];
  currentConfig.Servers.push({
    Name: "",
    RepoPath: "",
    ServerRoot: "",
    PluginsTarget: "",
    ConfigTarget: "",
    Branch: "",
    PluginsPattern: ["*.cs"],
    ConfigPattern: ["*.json"],
    ExcludePatterns: [],
    DeleteExtraneous: false,
    Enabled: true,
  });
  renderConfigForm(currentConfig);
});

btnSaveConfig.addEventListener("click", async () => {
  const payload = buildConfigFromForm();
  saveStatus.textContent = "Saving...";
  const res = await fetch("/api/config/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (data.ok) {
    saveStatus.textContent = "Saved. Restarted.";
  } else {
    saveStatus.textContent = `ERROR: ${data.errors ? data.errors.join("; ") : "unknown"}`;
  }
});

levelFilter.addEventListener("change", startLogStream);
serverFilter.addEventListener("change", startLogStream);

tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    selectTab(tab.dataset.tab);
  });
});

async function boot() {
  await fetchStatus();
  await fetchHistory();
  await fetchConfig();
  startLogStream();
  setInterval(fetchStatus, 5000);
  setInterval(fetchHistory, 10000);
}

boot();
