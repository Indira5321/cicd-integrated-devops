const sampleHistory = [];
let activeFilter = "all";
let tasksCache = [];
let toastTimer;

const byId = (id) => document.getElementById(id);
const formatCount = (value) => new Intl.NumberFormat().format(value ?? 0);

function showToast(message) {
  const toast = byId("toast");
  toast.textContent = message;
  toast.classList.add("is-visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("is-visible"), 2600);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]')?.content || "",
      ...options.headers,
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

function renderTasks(target, tasks, compact = false) {
  target.replaceChildren();
  if (!tasks.length) {
    const empty = document.createElement("div");
    empty.className = compact ? "compact-empty" : "empty-state";
    empty.textContent = compact ? "No tasks yet" : "Nothing on the board";
    target.append(empty);
    return;
  }
  tasks.forEach((task) => {
    const row = document.createElement("div");
    row.className = `task-row${compact ? " compact-task-row" : ""}${task.completed ? " is-complete" : ""}`;
    const toggle = document.createElement("button");
    toggle.className = "task-check";
    toggle.type = "button";
    toggle.setAttribute("aria-label", task.completed ? "Mark task open" : "Mark task complete");
    toggle.textContent = task.completed ? "✓" : "";
    toggle.addEventListener("click", async () => {
      try {
        await api(`/api/tasks/${task.id}`, {
          method: "PATCH",
          body: JSON.stringify({ completed: !task.completed }),
        });
        await refreshData();
      } catch (error) { showToast(error.message); }
    });
    const title = document.createElement("span");
    title.className = "task-title";
    title.textContent = task.title;
    row.append(toggle, title);
    if (!compact) {
      const date = document.createElement("time");
      date.className = "task-date";
      date.dateTime = task.created_at;
      date.textContent = new Date(task.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" });
      const remove = document.createElement("button");
      remove.className = "task-delete";
      remove.type = "button";
      remove.setAttribute("aria-label", `Delete ${task.title}`);
      remove.title = "Delete task";
      remove.textContent = "×";
      remove.addEventListener("click", async () => {
        try {
          await api(`/api/tasks/${task.id}`, { method: "DELETE" });
          showToast("Task removed");
          await refreshData();
        } catch (error) { showToast(error.message); }
      });
      row.append(date, remove);
    }
    target.append(row);
  });
}

function renderChart(value) {
  sampleHistory.push(value);
  if (sampleHistory.length > 24) sampleHistory.shift();
  const chart = byId("traffic-bars");
  const max = Math.max(1, ...sampleHistory);
  chart.replaceChildren();
  sampleHistory.forEach((sample, index) => {
    const bar = document.createElement("span");
    bar.className = "chart-bar";
    bar.style.height = `${Math.max(3, (sample / max) * 100)}%`;
    bar.style.opacity = `${0.38 + (index / sampleHistory.length) * 0.62}`;
    bar.title = `${sample} requests / min`;
    chart.append(bar);
  });
  const monitorChart = byId("monitor-chart");
  if (monitorChart) {
    monitorChart.replaceChildren();
    sampleHistory.forEach((sample, index) => {
      const bar = document.createElement("span");
      bar.className = "monitor-bar";
      bar.style.height = `${Math.max(3, (sample / max) * 100)}%`;
      bar.style.opacity = `${0.38 + (index / sampleHistory.length) * 0.62}`;
      monitorChart.append(bar);
    });
  }
}

function renderOverview(overview) {
  byId("requests-value").textContent = formatCount(overview.requests_per_minute);
  byId("latency-value").textContent = formatCount(overview.p95_latency_ms);
  byId("error-value").textContent = Number(overview.error_rate).toFixed(1);
  byId("chart-current").textContent = formatCount(overview.requests_per_minute);
  byId("monitor-requests").textContent = formatCount(overview.requests_per_minute);
  byId("monitor-latency").textContent = formatCount(overview.p95_latency_ms);
  byId("monitor-error").textContent = Number(overview.error_rate).toFixed(1);
  byId("release-sha").textContent = overview.deploy_sha || "local";
  byId("deploy-commit").textContent = overview.deploy_sha === "local" ? "local build" : overview.deploy_sha;
  byId("deployment-image").textContent = overview.deploy_sha === "local" ? "local" : `ghcr.io · ${overview.deploy_sha}`;
  byId("deployment-sha").textContent = overview.deploy_sha || "local";
  byId("task-open-count").textContent = formatCount(overview.tasks_open);
  byId("task-done-count").textContent = `${formatCount(overview.tasks_completed)} completed`;
  byId("all-task-count").textContent = formatCount(overview.tasks_total);
  const errorIndicator = byId("error-indicator");
  errorIndicator.className = `metric-indicator ${overview.error_rate > 1 ? "coral" : "green"}`;
  byId("error-caption").textContent = `${formatCount(overview.error_count)} 5xx responses · rolling 60s`;
  const deployedAt = Date.parse(overview.deployed_at);
  const deployAge = Number.isFinite(deployedAt) ? Math.max(0, Math.floor((Date.now() - deployedAt) / 60000)) : null;
  byId("deploy-time").textContent = deployAge === null ? "Local run" : deployAge < 1 ? "Just now" : deployAge < 60 ? `${deployAge} min ago` : `${Math.floor(deployAge / 60)} hr ago`;
  const startedAt = new Date(overview.started_at).getTime();
  const minutes = Math.max(0, Math.floor((Date.now() - startedAt) / 60000));
  byId("uptime").textContent = minutes < 60 ? `${minutes}m` : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
  renderChart(overview.requests_per_minute);
}

async function refreshData() {
  try {
    const [overview, tasks, health] = await Promise.all([
      api("/api/overview"), api("/api/tasks"), api("/api/health"),
    ]);
    tasksCache = tasks;
    renderOverview(overview);
    renderTasks(byId("overview-tasks"), tasks.slice(0, 3), true);
    const filtered = tasks.filter((task) => activeFilter === "all" || (activeFilter === "done" ? task.completed : !task.completed));
    renderTasks(byId("all-tasks"), filtered);
    const healthy = health.status === "healthy";
    byId("service-status").textContent = healthy ? "Operational" : "Degraded";
    document.body.classList.toggle("is-degraded", !healthy);
    byId("sidebar-checked").textContent = "just now";
  } catch (error) {
    byId("service-status").textContent = "Connection lost";
    document.body.classList.add("is-degraded");
    showToast(error.message);
  }
}

function navigate(view) {
  document.querySelectorAll("[data-panel]").forEach((panel) => {
    const isCurrent = panel.dataset.panel === view;
    panel.hidden = !isCurrent;
    panel.classList.toggle("is-visible", isCurrent);
  });
  document.querySelectorAll(".nav-item").forEach((button) => {
    const isCurrent = button.dataset.view === view;
    button.classList.toggle("is-active", isCurrent);
    if (isCurrent) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  const titles = { overview: "Control room", deployments: "Deployments", monitoring: "Monitoring", tasks: "Task API" };
  document.querySelector(".breadcrumbs strong").textContent = titles[view] || "Control room";
}

document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.view)));
document.querySelectorAll("[data-go]").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.go)));
document.querySelectorAll(".filter-button").forEach((button) => button.addEventListener("click", () => {
  activeFilter = button.dataset.filter;
  document.querySelectorAll(".filter-button").forEach((item) => item.classList.toggle("is-selected", item === button));
  renderTasks(byId("all-tasks"), tasksCache.filter((task) => activeFilter === "all" || (activeFilter === "done" ? task.completed : !task.completed)));
}));

byId("task-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = byId("task-title");
  try {
    await api("/api/tasks", { method: "POST", body: JSON.stringify({ title: input.value }) });
    input.value = "";
    showToast("Task added");
    await refreshData();
  } catch (error) { showToast(error.message); }
});

byId("refresh-button").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.classList.add("is-loading");
  await refreshData();
  button.classList.remove("is-loading");
});

function updateClock() {
  byId("clock").textContent = `${new Intl.DateTimeFormat("en", { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "UTC", hour12: false }).format(new Date())} UTC`;
}

const grafanaLink = byId("grafana-link");
if (location.hostname && location.hostname !== "localhost" && location.hostname !== "127.0.0.1") {
  grafanaLink.href = `${location.protocol}//${location.hostname}:3000`;
}
updateClock();
refreshData();
setInterval(updateClock, 1000);
setInterval(refreshData, 10000);
