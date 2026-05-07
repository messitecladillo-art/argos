const terminalShell = document.getElementById("terminal-shell");
const terminalViewport = document.getElementById("terminal-viewport");
const terminalTitle = document.getElementById("terminal-title");
const eventList = terminalShell;
const agentList = document.getElementById("agent-list");
const agentEmpty = document.getElementById("agent-empty");
const eventEmpty = document.getElementById("event-empty");
const sidebarStats = document.getElementById("sidebar-stats");
const openCreateAgent = document.getElementById("open-create-agent");
const openTeamSettings = document.getElementById("open-team-settings");
const modal = document.getElementById("create-agent-modal");
const createAgentForm = document.getElementById("create-agent-form");
const createAgentError = document.getElementById("create-agent-error");
const transferModal = document.getElementById("team-transfer-modal");
const transferAgentList = document.getElementById("transfer-agent-list");
const transferInlineSkills = document.getElementById("transfer-inline-skills");
const transferIncludeWorkspace = document.getElementById("transfer-include-workspace");
const transferExportSubmit = document.getElementById("transfer-export-submit");
const transferExportStatus = document.getElementById("transfer-export-status");
const transferImportFile = document.getElementById("transfer-import-file");
const transferFileName = document.getElementById("transfer-file-name");
const transferInspectSubmit = document.getElementById("transfer-inspect-submit");
const transferImportSubmit = document.getElementById("transfer-import-submit");
const transferImportStatus = document.getElementById("transfer-import-status");
const transferImportPreview = document.getElementById("transfer-import-preview");
const terminalDrawer = document.getElementById("terminal-drawer");
const openHistoryDrawer = document.getElementById("open-history-drawer");
const historyDrawer = document.getElementById("history-drawer");
const historyDrawerAgent = document.getElementById("history-drawer-agent");
const historyEmpty = document.getElementById("history-empty");
const interactionList = document.getElementById("interaction-list");
const soulDrawer = document.getElementById("soul-drawer");
const soulDrawerAgent = document.getElementById("soul-drawer-agent");
const soulDrawerPath = document.getElementById("soul-drawer-path");
const soulStatus = document.getElementById("soul-status");
const soulEditor = document.getElementById("soul-editor");
const soulPreview = document.getElementById("soul-preview");
const soulDirtyHint = document.getElementById("soul-dirty-hint");
const saveSoul = document.getElementById("save-soul");
const skillsDrawer = document.getElementById("skills-drawer");
const skillsDrawerAgent = document.getElementById("skills-drawer-agent");
const skillsStatus = document.getElementById("skills-status");
const openSkillsInstall = document.getElementById("open-skills-install");
const skillsInstallModal = document.getElementById("skills-install-modal");
const skillsInstallForm = document.getElementById("skills-install-form");
const skillsAlphaNav = document.getElementById("skills-alpha-nav");
const skillsList = document.getElementById("skills-list");
const skillsEmpty = document.getElementById("skills-empty");
const skillsRefresh = document.getElementById("skills-refresh");
const skillsDetailTitle = document.getElementById("skills-detail-title");
const skillsDetailMeta = document.getElementById("skills-detail-meta");
const skillsDetailPath = document.getElementById("skills-detail-path");
const skillsPreview = document.getElementById("skills-preview");
const skillsReinstall = document.getElementById("skills-reinstall");
const skillsUninstall = document.getElementById("skills-uninstall");
const mcpDrawer = document.getElementById("mcp-drawer");
const mcpDrawerAgent = document.getElementById("mcp-drawer-agent");
const mcpStatus = document.getElementById("mcp-status");
const mcpList = document.getElementById("mcp-list");
const mcpEmpty = document.getElementById("mcp-empty");
const mcpRefresh = document.getElementById("mcp-refresh");
const openMcpEdit = document.getElementById("open-mcp-edit");
const mcpEditModal = document.getElementById("mcp-edit-modal");
const mcpEditForm = document.getElementById("mcp-edit-form");
const mcpEditTitle = document.getElementById("mcp-edit-title");
const mcpSaveTest = document.getElementById("mcp-save-test");
const kanbanTaskForm = document.getElementById("kanban-task-form");
const kanbanTaskInput = document.getElementById("kanban-task-input");
const kanbanTaskStatus = document.getElementById("kanban-task-status");
const kanbanTaskList = document.getElementById("kanban-task-list");
const kanbanTaskEmpty = document.getElementById("kanban-task-empty");
const kanbanRefresh = document.getElementById("kanban-refresh");
const kanbanAutoDispatch = document.getElementById("kanban-auto-dispatch");
const kanbanDispatch = document.getElementById("kanban-dispatch");
const terminalSessions = new Map();
const chatEventsByAgent = new Map();
const defaultTerminalCols = 120;
const defaultTerminalRows = 36;
const terminalReconnectDelay = 900;
const hermesDebug = window.localStorage?.getItem("hermesDebug") !== "0";
let agentContextMenu = null;
let deletingAgentId = "";
let confirmModal = null;
let resizeTimer = 0;
let hermesStatusPromise = null;
const overlayAnimationMs = 220;
const overlayCloseTimers = new WeakMap();

function openAnimatedLayer(element, focusTarget = null) {
  if (!element) return;
  const closeTimer = overlayCloseTimers.get(element);
  if (closeTimer) window.clearTimeout(closeTimer);
  element.hidden = false;
  element.classList.remove("is-closing");
  requestAnimationFrame(() => {
    element.classList.add("is-open");
    if (focusTarget) window.setTimeout(() => focusTarget.focus(), 80);
  });
}

function closeAnimatedLayer(element, afterClose = null) {
  if (!element || element.hidden) return;
  element.classList.remove("is-open");
  element.classList.add("is-closing");
  const closeTimer = window.setTimeout(() => {
    if (!element.classList.contains("is-open")) {
      element.hidden = true;
      element.classList.remove("is-closing");
      if (afterClose) afterClose();
    }
  }, overlayAnimationMs);
  overlayCloseTimers.set(element, closeTimer);
}

function checkHermesStatus() {
  if (!hermesStatusPromise) {
    hermesStatusPromise = fetch("/api/hermes/status")
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.ok) hermesStatusPromise = null;
        return { response, data };
      })
      .catch((error) => {
        hermesStatusPromise = null;
        throw error;
      });
  }
  return hermesStatusPromise;
}
const soulState = {
  agentId: "",
  runtimeStatus: "stopped",
  originalContent: "",
  saving: false,
  scrollSyncSource: "",
  scrollSyncTimer: 0,
};
const skillsState = {
  agentId: "",
  agentName: "",
  items: [],
  selectedSlug: "",
  loading: false,
  detailRequestId: 0,
  activeLetter: "ALL",
};
const mcpState = {
  agentId: "",
  agentName: "",
  items: [],
  editingName: "",
};
const kanbanState = {
  links: Array.isArray(window.__BOOTSTRAP__?.kanban_task_links)
    ? window.__BOOTSTRAP__.kanban_task_links
    : [],
  loading: false,
  autoDispatchEnabled: false,
  autoDispatchIntervalMs: 5000,
  autoDispatchTimer: 0,
  autoDispatchRunning: false,
};
let transferLastInspectedFile = null;
const notificationAgentStates = new Map();
const notificationLastPlayedAt = new Map();
const notificationInteractionStates = new Set(["awaiting_approval", "awaiting_selection", "awaiting_input"]);
let notificationAudioContext = null;

const SKILL_ALPHA_OPTIONS = ["ALL", ...Array.from({ length: 26 }, (_item, index) => String.fromCharCode(65 + index))];

function debugLog(event, payload) {
  if (!hermesDebug) return;
  console.log(`[hermes-debug] ${event}`, payload);
}

function getNotificationAudioContext() {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) return null;
  if (!notificationAudioContext) notificationAudioContext = new AudioContextClass();
  return notificationAudioContext;
}

function unlockNotificationAudio() {
  const context = getNotificationAudioContext();
  if (context?.state === "suspended") context.resume().catch(() => {});
}

function playTone(context, { start, duration, frequency, type = "sine", volume = 0.055 }) {
  const oscillator = context.createOscillator();
  const gain = context.createGain();
  oscillator.type = type;
  oscillator.frequency.setValueAtTime(frequency, start);
  gain.gain.setValueAtTime(0.0001, start);
  gain.gain.exponentialRampToValueAtTime(volume, start + 0.015);
  gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
  oscillator.connect(gain).connect(context.destination);
  oscillator.start(start);
  oscillator.stop(start + duration + 0.02);
}

function playNotificationSound(kind, agentId) {
  if (window.localStorage?.getItem("hermesSound") === "0") return;
  const now = Date.now();
  const dedupeKey = `${kind}:${agentId || "global"}`;
  if (now - (notificationLastPlayedAt.get(dedupeKey) || 0) < 3000) return;
  notificationLastPlayedAt.set(dedupeKey, now);
  const context = getNotificationAudioContext();
  if (!context) return;
  if (context.state === "suspended") context.resume().catch(() => {});
  const start = context.currentTime + 0.02;
  if (kind === "taskDone") {
    playTone(context, { start, duration: 0.11, frequency: 660, type: "sine", volume: 0.045 });
    playTone(context, { start: start + 0.105, duration: 0.14, frequency: 880, type: "sine", volume: 0.05 });
    return;
  }
  playTone(context, { start, duration: 0.12, frequency: 523.25, type: "triangle", volume: 0.06 });
  playTone(context, { start: start + 0.16, duration: 0.12, frequency: 392, type: "triangle", volume: 0.06 });
}

function isLeaderAgent(agent) {
  return agent?.is_leader || agent?.role === "leader";
}

function getNotificationSnapshot(agent) {
  const displayStatus = getAgentDisplayStatus(agent).className;
  const interactionState = agent.interaction_state || "idle";
  return {
    displayStatus,
    needsIntervention: notificationInteractionStates.has(interactionState),
  };
}

function hydrateNotificationStates(agents) {
  if (!Array.isArray(agents)) return;
  agents.forEach((agent) => {
    if (agent?.agent_id) notificationAgentStates.set(agent.agent_id, getNotificationSnapshot(agent));
  });
}

function processSoundNotifications(agents) {
  if (!Array.isArray(agents)) return;
  const currentIds = new Set();
  agents.forEach((agent) => {
    if (!agent?.agent_id) return;
    currentIds.add(agent.agent_id);
    const previous = notificationAgentStates.get(agent.agent_id);
    const current = getNotificationSnapshot(agent);
    if (previous) {
      if (isLeaderAgent(agent) && previous.displayStatus === "busy" && current.displayStatus === "idle") {
        playNotificationSound("taskDone", agent.agent_id);
      }
      if (!previous.needsIntervention && current.needsIntervention) {
        playNotificationSound("needsIntervention", agent.agent_id);
      }
    }
    notificationAgentStates.set(agent.agent_id, current);
  });
  Array.from(notificationAgentStates.keys()).forEach((agentId) => {
    if (!currentIds.has(agentId)) notificationAgentStates.delete(agentId);
  });
}

document.addEventListener("pointerdown", unlockNotificationAudio, { once: true, passive: true });
document.addEventListener("keydown", unlockNotificationAudio, { once: true });

function summarizeTerminalText(value) {
  const text = String(value || "");
  const ansiMatches = text.match(/\x1b(?:\[[0-9;?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|[@-Z\\-_])/g) || [];
  const suspiciousControls = Array.from(text).filter((char) => {
    const code = char.charCodeAt(0);
    return (code < 32 && !["\n", "\r", "\t", "\x1b"].includes(char)) || code === 127;
  });
  return {
    length: text.length,
    ansiCount: ansiMatches.length,
    suspiciousControlCount: suspiciousControls.length,
    hasReplacementChar: text.includes("\ufffd"),
    preview: JSON.stringify(text.slice(0, 160)),
    tailPreview: JSON.stringify(text.slice(-160)),
    suspiciousControls: suspiciousControls.slice(0, 12).map((char) => char.charCodeAt(0)),
  };
}

function logTerminalPayload(event, session, payload) {
  if (!hermesDebug || !session) return;
  const data = typeof payload?.data === "string" ? payload.data : "";
  const summary = summarizeTerminalText(data);
  debugLog(event, {
    agentId: session.agentId,
    type: payload?.type,
    ...summary,
  });
  if (summary.hasReplacementChar || summary.suspiciousControlCount > 0) {
    console.warn(`[hermes-terminal] suspicious ${event}`, {
      agentId: session.agentId,
      type: payload?.type,
      ...summary,
    });
  }
}

function restoreTerminalSnapshot(session, payload) {
  if (!session) return false;
  const snapshotAnsi = String(payload?.snapshot_ansi || "");
  if (!snapshotAnsi) return false;
  debugLog("terminal-snapshot-restore", {
    agentId: session.agentId,
    ansiSummary: summarizeTerminalText(snapshotAnsi),
    textLength: String(payload?.snapshot_text || "").length,
  });
  session.term.reset();
  session.term.clear();
  session.term.write(snapshotAnsi);
  session.hasRenderedOutput = true;
  return true;
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function setKanbanStatus(message, kind = "muted") {
  if (!kanbanTaskStatus) return;
  kanbanTaskStatus.textContent = message || "";
  kanbanTaskStatus.hidden = !message;
  kanbanTaskStatus.dataset.kind = kind;
}

function kanbanRoleLabel(role) {
  if (role === "parent") return "父任务";
  if (role === "worker") return "Worker";
  if (role === "summary") return "汇总";
  return role || "任务";
}

function kanbanStatusLabel(status) {
  const value = String(status || "").toLowerCase();
  if (value === "ready") return "待执行";
  if (value === "todo") return "待处理";
  if (value === "triage") return "待分诊";
  if (value === "running") return "执行中";
  if (value === "done") return "已完成";
  if (value === "archived") return "已归档";
  if (value === "blocked") return "已阻塞";
  if (value === "failed") return "失败";
  if (value === "crashed") return "异常";
  if (value === "timed_out") return "超时";
  if (value === "gave_up") return "已放弃";
  return "未知";
}

function kanbanColumnForStatus(status) {
  const value = String(status || "").toLowerCase();
  if (value === "running") return "running";
  if (value === "done" || value === "archived") return "done";
  if (["blocked", "failed", "crashed", "timed_out", "gave_up"].includes(value)) return "blocked";
  if (value === "ready" || value === "todo" || value === "triage") return "ready";
  return "unknown";
}

function agentForKanbanLink(link) {
  const profileName = String(link?.assignee_profile || "").trim();
  if (!profileName) return null;
  const agents = Array.isArray(window.__BOOTSTRAP__?.agents) ? window.__BOOTSTRAP__.agents : [];
  return agents.find((agent) => agent.profile_name === profileName) || null;
}

function openKanbanLinkTerminal(link) {
  const agent = agentForKanbanLink(link);
  if (!agent) {
    setKanbanStatus(`找不到 assignee_profile=${link?.assignee_profile || "unassigned"} 对应的 Agent。`, "error");
    return;
  }
  if ((agent.readiness_status || "ready") !== "ready") {
    setKanbanStatus(`${agent.name || agent.agent_id} 尚未就绪，无法打开终端。`, "error");
    return;
  }
  setSelectedAgent(agent.agent_id, agent.name, true);
  openTerminalPanel();
}

function renderKanbanTasks() {
  if (!kanbanTaskList) return;
  const links = [...(kanbanState.links || [])].sort((a, b) => String(b.updated_at || b.created_at || "").localeCompare(String(a.updated_at || a.created_at || "")));
  kanbanTaskList.innerHTML = "";
  if (kanbanTaskEmpty) kanbanTaskEmpty.hidden = links.length > 0;
  const columns = [
    { key: "ready", title: "待执行" },
    { key: "running", title: "执行中" },
    { key: "blocked", title: "阻塞" },
    { key: "unknown", title: "未知" },
    { key: "done", title: "已完成" },
  ];
  const grouped = new Map(columns.map((column) => [column.key, []]));
  links.forEach((link) => {
    const key = kanbanColumnForStatus(link.kanban_status);
    grouped.get(key).push(link);
  });
  columns.forEach((column) => {
    const items = grouped.get(column.key) || [];
    const section = document.createElement("section");
    section.className = "kanban-column";
    section.innerHTML = `
      <div class="kanban-column__head">
        <strong>${escapeHtml(column.title)}</strong>
        <span>${items.length}</span>
      </div>
      <div class="kanban-column__body"></div>
    `;
    const body = section.querySelector(".kanban-column__body");
    if (!items.length) {
      body.innerHTML = `<p class="kanban-column__empty">—</p>`;
    }
    items.slice(0, 20).forEach((link) => {
      const card = document.createElement("article");
      card.className = "kanban-task-card";
      card.setAttribute("role", "button");
      card.tabIndex = 0;
      card.title = "打开对应 Agent 终端";
      card.addEventListener("click", () => openKanbanLinkTerminal(link));
      card.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        openKanbanLinkTerminal(link);
      });
      const resultPreview = link.last_result ? String(link.last_result).slice(0, 96) : "";
      card.innerHTML = `
        <div class="kanban-task-card__top">
          <strong>${escapeHtml(kanbanRoleLabel(link.kanban_role))}</strong>
          <span class="kanban-task-badge">${escapeHtml(kanbanStatusLabel(link.kanban_status))}</span>
        </div>
        <p>${escapeHtml(link.local_id || "")}</p>
        <small>${escapeHtml(link.kanban_task_id || "")} · ${escapeHtml(link.assignee_profile || "unassigned")}</small>
        ${resultPreview ? `<div class="kanban-task-card__result">${escapeHtml(resultPreview)}</div>` : ""}
      `;
      body.appendChild(card);
    });
    kanbanTaskList.appendChild(section);
  });
}

async function refreshKanbanTasks({ silent = false } = {}) {
  if (!kanbanTaskList || kanbanState.loading) return;
  kanbanState.loading = true;
  if (!silent) setKanbanStatus("正在刷新 Kanban 任务…");
  try {
    const response = await fetch("/api/kanban/tasks");
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || "Kanban 任务加载失败");
    kanbanState.links = Array.isArray(data.links) ? data.links : [];
    renderKanbanTasks();
    if (!silent) setKanbanStatus(`已刷新 ${kanbanState.links.length} 个任务映射。`, "success");
  } catch (error) {
    if (!silent) setKanbanStatus(error.message || "Kanban 任务加载失败", "error");
  } finally {
    kanbanState.loading = false;
  }
}

async function submitKanbanTask(event) {
  event.preventDefault();
  if (!kanbanTaskInput || !kanbanTaskForm) return;
  const content = kanbanTaskInput.value.trim();
  if (!content) {
    setKanbanStatus("请输入任务内容。", "error");
    kanbanTaskInput.focus();
    return;
  }
  const submitBtn = kanbanTaskForm.querySelector('button[type="submit"]');
  if (submitBtn) submitBtn.disabled = true;
  setKanbanStatus("正在创建 Kanban 父任务…");
  try {
    const response = await fetch("/api/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || "任务创建失败");
    kanbanTaskInput.value = "";
    const message = data.message || {};
    setKanbanStatus(`已创建：${message.kanban_task_id || message.user_task_id || "Kanban 任务"}`, "success");
    await refreshKanbanTasks({ silent: true });
  } catch (error) {
    setKanbanStatus(error.message || "任务创建失败", "error");
  } finally {
    if (submitBtn) submitBtn.disabled = false;
  }
}

function handleKanbanTaskInputKeydown(event) {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  kanbanTaskForm?.requestSubmit();
}

async function dispatchKanbanOnce() {
  if (!kanbanDispatch) return;
  kanbanDispatch.disabled = true;
  setKanbanStatus("正在触发一次 Kanban dispatch…");
  try {
    const response = await fetch("/api/kanban/dispatch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || "Dispatch 失败");
    setKanbanStatus("Dispatch 已触发。", "success");
    await refreshKanbanTasks({ silent: true });
  } catch (error) {
    setKanbanStatus(error.message || "Dispatch 失败", "error");
  } finally {
    kanbanDispatch.disabled = false;
  }
}

function renderKanbanAutoDispatch() {
  if (!kanbanAutoDispatch) return;
  kanbanAutoDispatch.textContent = `自动 Dispatch：${kanbanState.autoDispatchEnabled ? "开" : "关"}`;
  kanbanAutoDispatch.classList.toggle("is-active", kanbanState.autoDispatchEnabled);
  kanbanAutoDispatch.setAttribute("aria-pressed", kanbanState.autoDispatchEnabled ? "true" : "false");
}

function stopKanbanAutoDispatchTimer() {
  if (!kanbanState.autoDispatchTimer) return;
  window.clearInterval(kanbanState.autoDispatchTimer);
  kanbanState.autoDispatchTimer = 0;
}

async function runKanbanAutoDispatchTick() {
  if (!kanbanState.autoDispatchEnabled || kanbanState.autoDispatchRunning) return;
  kanbanState.autoDispatchRunning = true;
  try {
    const response = await fetch("/api/kanban/dispatch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || "自动 Dispatch 失败");
    setKanbanStatus("自动 Dispatch 已触发。", "success");
    await refreshKanbanTasks({ silent: true });
  } catch (error) {
    setKanbanStatus(error.message || "自动 Dispatch 失败", "error");
  } finally {
    kanbanState.autoDispatchRunning = false;
  }
}

function syncKanbanAutoDispatchTimer() {
  stopKanbanAutoDispatchTimer();
  if (!kanbanState.autoDispatchEnabled) return;
  kanbanState.autoDispatchTimer = window.setInterval(
    runKanbanAutoDispatchTick,
    kanbanState.autoDispatchIntervalMs,
  );
  void runKanbanAutoDispatchTick();
}

function applyKanbanSettings(settings) {
  kanbanState.autoDispatchEnabled = Boolean(settings?.auto_dispatch_enabled);
  kanbanState.autoDispatchIntervalMs = Number(settings?.auto_dispatch_interval_ms) || 5000;
  renderKanbanAutoDispatch();
  syncKanbanAutoDispatchTimer();
}

async function loadKanbanSettings() {
  if (!kanbanAutoDispatch) return;
  try {
    const response = await fetch("/api/kanban/settings");
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || "Kanban 设置加载失败");
    applyKanbanSettings(data.settings || {});
  } catch (error) {
    setKanbanStatus(error.message || "Kanban 设置加载失败", "error");
    renderKanbanAutoDispatch();
  }
}

async function toggleKanbanAutoDispatch() {
  if (!kanbanAutoDispatch) return;
  const nextEnabled = !kanbanState.autoDispatchEnabled;
  kanbanAutoDispatch.disabled = true;
  try {
    const response = await fetch("/api/kanban/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ auto_dispatch_enabled: nextEnabled }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || "Kanban 设置保存失败");
    applyKanbanSettings(data.settings || {});
    setKanbanStatus(`自动 Dispatch 已${kanbanState.autoDispatchEnabled ? "开启" : "关闭"}。`, "success");
  } catch (error) {
    setKanbanStatus(error.message || "Kanban 设置保存失败", "error");
  } finally {
    kanbanAutoDispatch.disabled = false;
  }
}

function formatAgentTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

function formatRuntimeStatus(value) {
  if (value === "running") return "在岗";
  if (value === "crashed") return "异常";
  return "离岗";
}

function getAgentDisplayStatus(agent) {
  const readinessStatus = agent.readiness_status || "ready";
  const runtimeStatus = agent.runtime_status || "stopped";
  const interactionState = agent.interaction_state || "idle";
  const orchestrationState = agent.orchestration_state || "none";
  const status = agent.status || "idle";
  const currentTask = agent.current_task || "";

  if (readinessStatus === "preparing") {
    return { label: "准备中", className: "preparing" };
  }
  if (readinessStatus === "failed") {
    return { label: "未就绪", className: "unready" };
  }
  if (runtimeStatus === "stopped" || runtimeStatus === "crashed") {
    return { label: "不可用", className: "offline" };
  }
  if (["awaiting_approval", "awaiting_selection", "awaiting_input"].includes(interactionState)) {
    return { label: "需介入", className: "waiting" };
  }
  if (currentTask.includes("可能卡住")) {
    return { label: "卡住", className: "stuck" };
  }
  if (
    status === "busy" ||
    status === "waiting" ||
    interactionState === "queued" ||
    interactionState === "running" ||
    orchestrationState === "waiting_workers" ||
    orchestrationState === "summarizing" ||
    orchestrationState === "kanban_ready" ||
    orchestrationState === "kanban_running"
  ) {
    return { label: "处理中", className: "busy" };
  }
  return { label: "空闲", className: "idle" };
}

function buildAgentRow(agent, isActive) {
  const row = document.createElement("div");
  const readinessStatus = agent.readiness_status || "ready";
  const isReady = readinessStatus === "ready";
  const runtimeStatus = agent.runtime_status || "stopped";
  row.setAttribute("role", "button");
  row.setAttribute("aria-disabled", isReady ? "false" : "true");
  row.tabIndex = isReady ? 0 : -1;
  row.className = "agent-row" + (!isReady ? " is-disabled" : "") + (isReady && isActive ? " is-active" : "");
  row.dataset.agentId = agent.agent_id;
  row.dataset.agentName = agent.name;
  row.dataset.agentRole = agent.role;
  row.dataset.agentStatus = agent.status || "idle";
  row.dataset.agentOrchestrationState = agent.orchestration_state || "none";
  row.dataset.agentRuntimeStatus = runtimeStatus;
  row.dataset.readinessStatus = readinessStatus;
  const displayStatus = getAgentDisplayStatus(agent);
  debugLog("agent-row", {
    agent_id: agent.agent_id,
    status: agent.status,
    interaction_state: agent.interaction_state,
    orchestration_state: agent.orchestration_state,
    runtime_status: runtimeStatus,
    readiness_status: readinessStatus,
    queue_depth: agent.queue_depth || 0,
    display: displayStatus.label,
  });
  const btn = !isReady
    ? `<button class="acp-btn acp-btn--start acp-btn--runtime" type="button" data-session-action="start" data-agent-id="${agent.agent_id}" disabled>启动</button>`
    : runtimeStatus === "running"
    ? `<button class="acp-btn acp-btn--stop acp-btn--runtime" type="button" data-session-action="stop" data-agent-id="${agent.agent_id}">停止</button>`
    : `<button class="acp-btn acp-btn--start acp-btn--runtime" type="button" data-session-action="start" data-agent-id="${agent.agent_id}">启动</button>`;
  row.innerHTML = `
    <div class="agent-row__top">
      <div>
        <strong>${escapeHtml(agent.name)}</strong>
        <p>${escapeHtml(agent.role)} · ${escapeHtml(agent.profile_name)}</p>
      </div>
      <span class="status-badge status-${escapeHtml(displayStatus.className)}">${escapeHtml(displayStatus.label)}</span>
    </div>
    <div class="agent-row__body">
      <div class="load-track"><span style="width: ${agent.load || 0}%"></span></div>
      <dl>
        <div><dt>最后消息</dt><dd>${escapeHtml(formatAgentTime(agent.last_output_at))}</dd></div>
        <div><dt>任务数量</dt><dd>${agent.queue_depth || 0}</dd></div>
      </dl>
      <div class="agent-row__session">
        <span class="acp-dot acp-${runtimeStatus}"></span>
        <span class="acp-label">${escapeHtml(formatRuntimeStatus(runtimeStatus))}</span>
        <button class="acp-btn acp-btn--config" type="button" data-agent-config data-agent-id="${agent.agent_id}">配置 ▾</button>
        ${btn}
      </div>
    </div>
  `;
  return row;
}

function getChatEventMeta(event) {
  const type = event.event_type || "";
  if (type === "message.sent") return { label: "发送", className: "user" };
  if (type === "agent.output.final") return { label: "回复", className: "agent" };
  if (type === "agent.output.failed" || type === "agent.runtime.failed") {
    return { label: "异常", className: "error" };
  }
  if (type === "agent.interaction.required") {
    return { label: "需介入", className: "waiting" };
  }
  if (type === "agent.interaction.resolved") {
    return { label: "已处理", className: "system" };
  }
  if (type === "agent.created" || type === "agent.deleted") {
    return { label: "系统", className: "system" };
  }
  if (type === "user_task.created" || type === "user_task.completed") {
    return { label: "任务", className: "system" };
  }
  return null;
}

function isChatEvent(event) {
  return Boolean(event?.agent_id && getChatEventMeta(event));
}

function rememberChatEvent(event) {
  if (!isChatEvent(event)) return false;
  const agentId = event.agent_id;
  const events = chatEventsByAgent.get(agentId) || [];
  if (events.some((item) => item.id === event.id)) return false;
  events.push(event);
  events.sort((a, b) => (
    String(a.timestamp || "").localeCompare(String(b.timestamp || ""))
  ));
  chatEventsByAgent.set(agentId, events.slice(-80));
  return true;
}

function formatChatEventText(event) {
  return String(event.data?.text || "").trim() || "(空内容)";
}

function buildChatEventCard(event) {
  const meta = getChatEventMeta(event);
  const card = document.createElement("article");
  card.className = `interaction-card interaction-card--${meta.className}`;
  card.innerHTML = `
    <div class="interaction-card__head">
      <span>${escapeHtml(meta.label)}</span>
      <time>${escapeHtml(formatAgentTime(event.timestamp))}</time>
    </div>
    <p>${escapeHtml(formatChatEventText(event))}</p>
  `;
  return card;
}

function getSelectedAgentName() {
  const selectedAgentId = eventList?.dataset.selectedAgent || "";
  const row = selectedAgentId
    ? agentList?.querySelector(`.agent-row[data-agent-id="${CSS.escape(selectedAgentId)}"]`)
    : null;
  return row?.dataset.agentName || selectedAgentId || "尚未选择 Agent";
}

function renderInteractions() {
  if (!interactionList) return;
  const selectedAgentId = eventList?.dataset.selectedAgent || "";
  const events = selectedAgentId ? (chatEventsByAgent.get(selectedAgentId) || []) : [];
  if (historyDrawerAgent) historyDrawerAgent.textContent = getSelectedAgentName();
  if (historyEmpty) historyEmpty.hidden = events.length > 0;
  interactionList.innerHTML = "";
  interactionList.hidden = events.length === 0;
  events.forEach((event) => {
    interactionList.appendChild(buildChatEventCard(event));
  });
  interactionList.scrollTop = interactionList.scrollHeight;
}

function openHistoryPanel() {
  if (!historyDrawer) return;
  renderInteractions();
  openAnimatedLayer(historyDrawer);
}

function closeHistoryPanel() {
  if (!historyDrawer || historyDrawer.hidden) return;
  closeAnimatedLayer(historyDrawer);
}

function fitTerminalDrawer() {
  scheduleTerminalFit(0);
  scheduleTerminalFit(80);
  window.setTimeout(fitAllTerminalSessions, 180);
}

function openTerminalPanel() {
  if (!terminalDrawer) return;
  openAnimatedLayer(terminalDrawer);
  const agentId = eventList?.dataset.selectedAgent || "";
  if (agentId) {
    const session = ensureTerminalSession(agentId);
    if (session && (!session.ws || session.ws.readyState > WebSocket.OPEN)) connectTerminalSession(session);
  }
  fitTerminalDrawer();
}

function closeTerminalPanel() {
  if (!terminalDrawer || terminalDrawer.hidden) return;
  closeAnimatedLayer(terminalDrawer);
}

function setSoulStatus(message, kind = "muted") {
  if (!soulStatus) return;
  soulStatus.textContent = message || "";
  soulStatus.dataset.kind = kind;
  soulStatus.hidden = !message;
}

function setSkillsStatus(message, kind = "muted", options = {}) {
  if (!skillsStatus) return;
  skillsStatus.innerHTML = "";
  skillsStatus.dataset.kind = kind;
  skillsStatus.classList.toggle("has-action", Boolean(options.restartAction));
  skillsStatus.hidden = !message;
  if (!message) return;
  const text = document.createElement("span");
  text.textContent = message;
  skillsStatus.appendChild(text);
  if (options.restartAction) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "filter-chip skills-status__action";
    button.dataset.skillsRestartAgent = "true";
    button.textContent = "重启当前 Agent";
    skillsStatus.appendChild(button);
  }
}

function showSkillsRestartPrompt(message, kind = "success") {
  setSkillsStatus(`${message} 重启当前 Agent 后生效。`, kind, { restartAction: true });
}

function setMcpStatus(message, kind = "muted", options = {}) {
  if (!mcpStatus) return;
  mcpStatus.innerHTML = "";
  mcpStatus.dataset.kind = kind;
  mcpStatus.classList.toggle("has-action", Boolean(options.restartAction));
  mcpStatus.hidden = !message;
  if (!message) return;
  const text = document.createElement("span");
  text.textContent = message;
  mcpStatus.appendChild(text);
  if (options.restartAction) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "filter-chip skills-status__action";
    button.dataset.mcpRestartAgent = "true";
    button.textContent = "重启当前 Agent";
    mcpStatus.appendChild(button);
  }
}

function showMcpRestartPrompt(message, kind = "success") {
  setMcpStatus(`${message} 重启当前 Agent 后生效。`, kind, { restartAction: true });
}

async function restartCurrentMcpAgent(triggerButton = null) {
  const agentId = mcpState.agentId;
  if (!agentId) return;
  if (triggerButton) triggerButton.disabled = true;
  setMcpStatus("正在重启当前 Agent…", "muted");
  try {
    const response = await fetch(`/api/agents/${agentId}/restart`, { method: "POST" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || "重启 Agent 失败");
    setMcpStatus("当前 Agent 已重启，MCP 已生效。", "success");
  } catch (error) {
    showMcpRestartPrompt(`重启失败：${error.message || "未知错误"}`, "error");
  } finally {
    if (triggerButton) triggerButton.disabled = false;
  }
}

async function restartCurrentSkillsAgent(triggerButton = null) {
  const agentId = skillsState.agentId;
  if (!agentId) return;
  if (triggerButton) triggerButton.disabled = true;
  setSkillsStatus("正在重启当前 Agent…", "muted");
  try {
    const stopResponse = await fetch(`/api/agents/${agentId}/stop`, { method: "POST" });
    const stopData = await stopResponse.json().catch(() => ({}));
    if (!stopResponse.ok || stopData.ok === false) throw new Error(stopData.error || "停止 Agent 失败");

    const startResponse = await fetch(`/api/agents/${agentId}/start`, { method: "POST" });
    const startData = await startResponse.json().catch(() => ({}));
    if (!startResponse.ok || !startData.ok) throw new Error(startData.error || "启动 Agent 失败");

    setSkillsStatus("当前 Agent 已重启，skills 已生效。", "success");
  } catch (error) {
    showSkillsRestartPrompt(`重启失败：${error.message || "未知错误"}`, "error");
  }
}

function hasUnsavedSoulChanges() {
  return Boolean(soulEditor && soulEditor.value !== soulState.originalContent);
}

function updateSoulDirtyState() {
  const dirty = hasUnsavedSoulChanges();
  if (soulDirtyHint) soulDirtyHint.hidden = !dirty;
  if (saveSoul) saveSoul.disabled = soulState.saving || !dirty || !soulEditor?.value.trim();
}

function renderInlineMarkdown(value) {
  return escapeHtml(value).replace(/`([^`]+)`/g, "<code>$1</code>");
}

function renderMarkdownPreview(markdown) {
  if (!soulPreview) return;
  const lines = String(markdown || "").split(/\r?\n/);
  const html = [];
  let inCode = false;
  let codeLines = [];
  let listOpen = false;
  const closeList = () => {
    if (listOpen) {
      html.push("</ul>");
      listOpen = false;
    }
  };
  const flushCode = () => {
    html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
    codeLines = [];
  };

  lines.forEach((line) => {
    if (line.trim().startsWith("```")) {
      if (inCode) {
        flushCode();
        inCode = false;
      } else {
        closeList();
        inCode = true;
        codeLines = [];
      }
      return;
    }
    if (inCode) {
      codeLines.push(line);
      return;
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      closeList();
      const level = heading[1].length;
      html.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
      return;
    }

    const listItem = line.match(/^\s*[-*]\s+(.+)$/);
    if (listItem) {
      if (!listOpen) {
        html.push("<ul>");
        listOpen = true;
      }
      html.push(`<li>${renderInlineMarkdown(listItem[1])}</li>`);
      return;
    }

    closeList();
    if (!line.trim()) {
      html.push("");
      return;
    }
    html.push(`<p>${renderInlineMarkdown(line)}</p>`);
  });

  if (inCode) flushCode();
  closeList();
  soulPreview.innerHTML = html.join("");
}

function getScrollRatio(element) {
  const maxScroll = element.scrollHeight - element.clientHeight;
  if (maxScroll <= 0) return 0;
  return element.scrollTop / maxScroll;
}

function setScrollRatio(element, ratio) {
  const maxScroll = element.scrollHeight - element.clientHeight;
  element.scrollTop = maxScroll > 0 ? maxScroll * ratio : 0;
}

function syncSoulScroll(source, target, sourceName) {
  if (!source || !target) return;
  if (soulState.scrollSyncSource && soulState.scrollSyncSource !== sourceName) return;
  soulState.scrollSyncSource = sourceName;
  setScrollRatio(target, getScrollRatio(source));
  clearTimeout(soulState.scrollSyncTimer);
  soulState.scrollSyncTimer = window.setTimeout(() => {
    soulState.scrollSyncSource = "";
  }, 80);
}

function syncSoulPreviewToEditor() {
  if (!soulEditor || !soulPreview) return;
  setScrollRatio(soulPreview, getScrollRatio(soulEditor));
}

function skillLetterForSlug(slug) {
  const first = String(slug || "").trim().charAt(0).toUpperCase();
  return /^[A-Z]$/.test(first) ? first : "#";
}

function getFilteredSkills() {
  if (skillsState.activeLetter === "ALL") return skillsState.items;
  return skillsState.items.filter((skill) => skillLetterForSlug(skill.slug) === skillsState.activeLetter);
}

function renderSkillAlphaNav() {
  if (!skillsAlphaNav) return;
  const availableLetters = new Set(skillsState.items.map((skill) => skillLetterForSlug(skill.slug)));
  skillsAlphaNav.innerHTML = "";
  SKILL_ALPHA_OPTIONS.forEach((letter) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "skill-alpha-chip filter-chip" + (skillsState.activeLetter === letter ? " is-active" : "");
    button.dataset.letter = letter;
    button.textContent = letter === "ALL" ? "全部" : letter;
    if (letter !== "ALL" && !availableLetters.has(letter)) {
      button.disabled = true;
    }
    skillsAlphaNav.appendChild(button);
  });
}

function renderSkillItems() {
  if (!skillsList) return;
  const filteredItems = getFilteredSkills();
  skillsList.innerHTML = "";
  if (skillsEmpty) {
    skillsEmpty.hidden = filteredItems.length > 0;
    skillsEmpty.textContent = skillsState.activeLetter === "ALL" ? "还没有安装 skill。" : `没有 ${skillsState.activeLetter} 开头的 skill。`;
  }
  filteredItems.forEach((skill) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "skill-row" + (skill.slug === skillsState.selectedSlug ? " is-active" : "");
    button.dataset.slug = skill.slug;
    button.innerHTML = `
      <strong>${escapeHtml(skill.slug)}</strong>
      <span>${escapeHtml(skill.description || skill.name || skill.slug)}</span>
      <small>${escapeHtml(skill.source_type || "local")}</small>
    `;
    skillsList.appendChild(button);
  });
}

function setSelectedSkillDetail(skill) {
  skillsState.selectedSlug = skill?.slug || "";
  if (skillsDetailTitle) skillsDetailTitle.textContent = skill?.slug || "选择一个 skill";
  if (skillsDetailMeta) {
    const sourceType = skill?.source_type || "—";
    const sourceRef = skill?.source_ref ? ` · ${skill.source_ref}` : "";
    skillsDetailMeta.textContent = skill ? `${sourceType}${sourceRef}` : "—";
  }
  if (skillsDetailPath) skillsDetailPath.textContent = skill?.path || "—";
  if (skillsPreview) {
    const content = String(skill?.content || skill?.body || "").trim();
    skillsPreview.innerHTML = content ? `<pre><code>${escapeHtml(content)}</code></pre>` : "<p>暂无内容。</p>";
  }
  if (skillsReinstall) skillsReinstall.disabled = !skill || !skill.has_db_record;
  if (skillsUninstall) skillsUninstall.disabled = !skill;
  renderSkillItems();
}

async function loadSkillDetail(slug) {
  if (!skillsState.agentId || !slug) return;
  skillsState.selectedSlug = slug;
  renderSkillItems();
  const requestId = ++skillsState.detailRequestId;
  try {
    const response = await fetch(`/api/agents/${skillsState.agentId}/skills/${encodeURIComponent(slug)}`);
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || "skill 加载失败");
    if (requestId !== skillsState.detailRequestId) return;
    setSelectedSkillDetail(data.skill);
    setSkillsStatus("", "muted");
  } catch (error) {
    if (requestId !== skillsState.detailRequestId) return;
    setSkillsStatus(error.message || "skill 加载失败", "error");
  }
}

async function refreshSkills(selectSlug = "") {
  if (!skillsState.agentId) return;
  skillsState.loading = true;
  setSkillsStatus("正在刷新 skills…", "muted");
  try {
    const response = await fetch(`/api/agents/${skillsState.agentId}/skills`);
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || "skills 列表加载失败");
    skillsState.items = Array.isArray(data.skills) ? data.skills : [];
    renderSkillAlphaNav();
    renderSkillItems();
    const filteredItems = getFilteredSkills();
    let nextSlug = selectSlug || skillsState.selectedSlug || filteredItems[0]?.slug || "";
    if (nextSlug && !filteredItems.some((skill) => skill.slug === nextSlug)) {
      nextSlug = filteredItems[0]?.slug || "";
    }
    if (nextSlug) {
      await loadSkillDetail(nextSlug);
    } else {
      setSelectedSkillDetail(null);
      setSkillsStatus("", "muted");
    }
  } catch (error) {
    setSkillsStatus(error.message || "skills 列表加载失败", "error");
  } finally {
    skillsState.loading = false;
  }
}

async function openSkillsPanel(agentId) {
  if (!skillsDrawer || !agentId) return;
  closeAgentContextMenu();
  skillsState.agentId = agentId;
  skillsState.agentName = agentList?.querySelector(`.agent-row[data-agent-id="${CSS.escape(agentId)}"]`)?.dataset.agentName || agentId;
  skillsState.items = [];
  skillsState.selectedSlug = "";
  skillsState.activeLetter = "ALL";
  if (skillsDrawerAgent) skillsDrawerAgent.textContent = skillsState.agentName;
  setSelectedSkillDetail(null);
  renderSkillAlphaNav();
  renderSkillItems();
  setSkillsStatus("正在加载 skills…", "muted");
  openAnimatedLayer(skillsDrawer);
  await refreshSkills();
}

function closeSkillsPanel() {
  if (!skillsDrawer || skillsDrawer.hidden) return;
  closeAnimatedLayer(skillsDrawer, () => {
    skillsState.agentId = "";
    skillsState.agentName = "";
    skillsState.items = [];
    skillsState.selectedSlug = "";
    skillsState.activeLetter = "ALL";
    setSkillsStatus("", "muted");
  });
}

function mcpEndpoint(name = "") {
  const base = `/api/agents/${mcpState.agentId}/mcps`;
  return name ? `${base}/${encodeURIComponent(name)}` : base;
}

function parseKeyValueLines(value) {
  const result = {};
  String(value || "").split(/\r?\n/).forEach((line) => {
    const text = line.trim();
    if (!text) return;
    const colonIndex = text.indexOf(":");
    const equalsIndex = text.indexOf("=");
    const indexes = [colonIndex, equalsIndex].filter((index) => index >= 0);
    const index = indexes.length ? Math.min(...indexes) : -1;
    if (index <= 0) return;
    const key = text.slice(0, index).trim();
    const item = text.slice(index + 1).trim();
    if (key) result[key] = item;
  });
  return result;
}

function stringifyKeyValues(value) {
  return Object.entries(value || {}).map(([key, item]) => `${key}: ${item}`).join("\n");
}

function renderMcpItems() {
  if (!mcpList) return;
  mcpList.innerHTML = "";
  if (mcpEmpty) mcpEmpty.hidden = mcpState.items.length > 0;
  mcpState.items.forEach((mcp) => {
    const card = document.createElement("article");
    card.className = "mcp-card";
    const target = mcp.transport === "stdio"
      ? [mcp.command, ...(mcp.args || [])].filter(Boolean).join(" ")
      : mcp.url || "—";
    const testLabel = mcp.last_test_status === "ok" ? "测试:✓" : mcp.last_test_status === "fail" ? "测试:×" : "未测试";
    const managed = Boolean(mcp.managed);
    card.innerHTML = `
      <div class="mcp-card__head">
        <div>
          <strong>${escapeHtml(mcp.name)}</strong>
          <div class="mcp-card__badges">
            <span class="mcp-badge">${escapeHtml(mcp.transport)}</span>
            <span class="mcp-badge">${escapeHtml(mcp.source_type || "manual")}</span>
            <span class="mcp-badge">${escapeHtml(testLabel)}</span>
          </div>
        </div>
        <small>${managed ? "🔒 平台托管" : ""}</small>
      </div>
      <p>${escapeHtml(mcp.description || "暂无描述")}</p>
      <code>${escapeHtml(target)}</code>
      <div class="mcp-card__actions">
        <div></div>
        <div>
          <button class="filter-chip" type="button" data-mcp-reveal="${escapeHtml(mcp.name)}">显示</button>
          <button class="filter-chip" type="button" data-mcp-edit="${escapeHtml(mcp.name)}" ${managed ? "disabled title=\"平台托管\"" : ""}>编辑</button>
          <button class="filter-chip" type="button" data-mcp-test="${escapeHtml(mcp.name)}">测试</button>
          <button class="filter-chip" type="button" data-mcp-delete="${escapeHtml(mcp.name)}" ${managed ? "disabled title=\"平台托管\"" : ""}>删除</button>
        </div>
      </div>
    `;
    mcpList.appendChild(card);
  });
}

async function refreshMcps() {
  if (!mcpState.agentId) return;
  setMcpStatus("正在刷新 MCP…", "muted");
  try {
    const response = await fetch(mcpEndpoint());
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || "MCP 列表加载失败");
    mcpState.items = Array.isArray(data.mcps) ? data.mcps : [];
    renderMcpItems();
    setMcpStatus("", "muted");
  } catch (error) {
    setMcpStatus(error.message || "MCP 列表加载失败", "error");
  }
}

async function openMcpPanel(agentId) {
  if (!mcpDrawer || !agentId) return;
  closeAgentContextMenu();
  mcpState.agentId = agentId;
  mcpState.agentName = agentList?.querySelector(`.agent-row[data-agent-id="${CSS.escape(agentId)}"]`)?.dataset.agentName || agentId;
  mcpState.items = [];
  if (mcpDrawerAgent) mcpDrawerAgent.textContent = mcpState.agentName;
  renderMcpItems();
  setMcpStatus("正在加载 MCP…", "muted");
  openAnimatedLayer(mcpDrawer);
  await refreshMcps();
}

function closeMcpPanel() {
  if (!mcpDrawer || mcpDrawer.hidden) return;
  closeAnimatedLayer(mcpDrawer, () => {
    mcpState.agentId = "";
    mcpState.agentName = "";
    mcpState.items = [];
    setMcpStatus("", "muted");
  });
}

function toggleMcpTransportFields() {
  if (!mcpEditForm) return;
  const transport = mcpEditForm.elements.transport.value;
  const isHttpTransport = transport === "http" || transport === "streamable_http";
  mcpEditForm.querySelectorAll(".mcp-http-field").forEach((item) => { item.hidden = !isHttpTransport; });
  mcpEditForm.querySelectorAll(".mcp-stdio-field").forEach((item) => { item.hidden = transport !== "stdio"; });
}

function openMcpEditModal(mcp = null) {
  if (!mcpEditModal || !mcpEditForm) return;
  mcpState.editingName = mcp?.name || "";
  mcpEditForm.reset();
  mcpEditForm.elements.original_name.value = mcp?.name || "";
  mcpEditForm.elements.transport.value = mcp?.transport || "http";
  mcpEditForm.elements.name.value = mcp?.name || "";
  mcpEditForm.elements.name.disabled = Boolean(mcp);
  mcpEditForm.elements.url.value = mcp?.url || "";
  mcpEditForm.elements.headers.value = stringifyKeyValues(mcp?.headers || {});
  mcpEditForm.elements.command.value = mcp?.command || "";
  mcpEditForm.elements.args.value = (mcp?.args || []).join("\n");
  mcpEditForm.elements.env.value = stringifyKeyValues(mcp?.env || {});
  mcpEditForm.elements.description.value = mcp?.description || "";
  if (mcpEditTitle) mcpEditTitle.textContent = mcp ? `编辑 MCP：${mcp.name}` : "新增 MCP";
  toggleMcpTransportFields();
  openAnimatedLayer(mcpEditModal, mcpEditForm.elements.name);
}

function closeMcpEditModal() {
  if (!mcpEditModal) return;
  closeAnimatedLayer(mcpEditModal, () => {
    mcpState.editingName = "";
    mcpEditForm?.reset();
  });
}

function buildMcpPayload() {
  const formData = new FormData(mcpEditForm);
  const transport = formData.get("transport") || "http";
  const payload = {
    name: String(formData.get("name") || "").trim(),
    transport,
    description: String(formData.get("description") || "").trim(),
  };
  if (transport === "http" || transport === "streamable_http") {
    payload.url = String(formData.get("url") || "").trim();
    payload.headers = parseKeyValueLines(formData.get("headers"));
  } else {
    payload.command = String(formData.get("command") || "").trim();
    payload.args = String(formData.get("args") || "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    payload.env = parseKeyValueLines(formData.get("env"));
  }
  return payload;
}

async function saveMcpFromForm({ testAfter = false } = {}) {
  if (!mcpState.agentId || !mcpEditForm) return;
  const payload = buildMcpPayload();
  const editingName = mcpState.editingName;
  const method = editingName ? "PUT" : "POST";
  const url = editingName ? mcpEndpoint(editingName) : mcpEndpoint();
  setMcpStatus(editingName ? "正在保存 MCP…" : "正在新增 MCP…", "muted");
  try {
    let response = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    let data = await response.json().catch(() => ({}));
    if (response.status === 409 && !editingName) {
      const takeover = await confirmAction({
        title: "接管外部 MCP",
        message: "检测到 config.yaml 已有同名外部 MCP，是否接管并覆盖为平台可管理？",
        confirmText: "接管编辑",
        confirmVariant: "default",
      });
      if (!takeover) return;
      response = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...payload, takeover: true }),
      });
      data = await response.json().catch(() => ({}));
    }
    if (!response.ok || !data.ok) throw new Error(data.error || "MCP 保存失败");
    closeMcpEditModal();
      await refreshMcps();
    if (testAfter) {
      const testOk = await testMcp(editingName || payload.name);
      if (!testOk) return;
    }
    showMcpRestartPrompt("MCP 已保存。");
  } catch (error) {
    setMcpStatus(error.message || "MCP 保存失败", "error");
  }
}

async function revealMcp(name) {
  const confirmed = await confirmAction({ title: "显示 Secret", message: "确认在当前屏幕显示明文 secret 吗？", confirmText: "显示", confirmVariant: "default" });
  if (!confirmed) return;
  try {
    const response = await fetch(`${mcpEndpoint(name)}?reveal=1`);
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || "MCP 加载失败");
    openMcpEditModal(data.mcp);
  } catch (error) {
    setMcpStatus(error.message || "MCP 加载失败", "error");
  }
}

async function editMcp(name) {
  try {
    const response = await fetch(mcpEndpoint(name));
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || "MCP 加载失败");
    openMcpEditModal(data.mcp);
  } catch (error) {
    setMcpStatus(error.message || "MCP 加载失败", "error");
  }
}

async function testMcp(name) {
  const item = mcpState.items.find((mcp) => mcp.name === name);
  if (item?.transport === "stdio") {
    const confirmed = await confirmAction({ title: "执行本机命令", message: "stdio MCP 测试会在本机启动配置的 command，确认继续？", confirmText: "执行测试", confirmVariant: "danger" });
    if (!confirmed) return false;
  }
  setMcpStatus(`正在测试 ${name}…`, "muted");
  try {
    const response = await fetch(`${mcpEndpoint(name)}/test`, { method: "POST" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.ok === false) throw new Error(data.error || data.detail || "MCP 测试失败");
    await refreshMcps();
    setMcpStatus(`${name}: ${data.detail || data.status}`, data.status === "ok" ? "success" : "error");
    return data.status === "ok";
  } catch (error) {
    setMcpStatus(error.message || "MCP 测试失败", "error");
    return false;
  }
}

async function deleteMcp(name) {
  const confirmed = await confirmAction({ title: "确认删除", message: `将从 config.yaml 移除 ${name}，确认继续？`, confirmText: "删除", confirmVariant: "danger" });
  if (!confirmed) return;
  setMcpStatus(`正在删除 ${name}…`, "muted");
  try {
    const response = await fetch(`${mcpEndpoint(name)}?confirm=1`, { method: "DELETE" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || "MCP 删除失败");
    await refreshMcps();
    showMcpRestartPrompt(`${name} 已删除。`);
  } catch (error) {
    setMcpStatus(error.message || "MCP 删除失败", "error");
  }
}

async function setSkillsLetterFilter(letter) {
  const nextLetter = SKILL_ALPHA_OPTIONS.includes(letter) ? letter : "ALL";
  if (skillsState.activeLetter === nextLetter) return;
  skillsState.activeLetter = nextLetter;
  renderSkillAlphaNav();
  renderSkillItems();
  const filteredItems = getFilteredSkills();
  const nextSlug = filteredItems.some((skill) => skill.slug === skillsState.selectedSlug)
    ? skillsState.selectedSlug
    : filteredItems[0]?.slug || "";
  if (nextSlug) {
    await loadSkillDetail(nextSlug);
  } else {
    setSelectedSkillDetail(null);
  }
}

function openSkillsInstallModal() {
  if (!skillsInstallModal) return;
  openAnimatedLayer(skillsInstallModal, skillsInstallForm?.querySelector('input[name="repo_url"]'));
}

function closeSkillsInstallModal() {
  if (!skillsInstallModal) return;
  closeAnimatedLayer(skillsInstallModal, () => skillsInstallForm?.reset());
}

async function installSkillFromForm(event) {
  event.preventDefault();
  if (!skillsState.agentId || !skillsInstallForm) return;
  const formData = new FormData(skillsInstallForm);
  const repoUrl = String(formData.get("repo_url") || "").trim();
  if (!repoUrl) {
    setSkillsStatus("请输入 Git 仓库地址。", "error");
    return;
  }
  const payload = {
    repo_url: repoUrl,
    ref: formData.get("ref"),
    subdir: formData.get("subdir"),
    slug: formData.get("slug"),
  };
  const submitBtn = skillsInstallForm.querySelector('button[type="submit"]');
  if (submitBtn) submitBtn.disabled = true;
  setSkillsStatus("正在安装 skill…", "muted");
  try {
    const response = await fetch(`/api/agents/${skillsState.agentId}/skills/install`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || "skill 安装失败");
    skillsInstallForm.reset();
    closeSkillsInstallModal();
    await refreshSkills(data.skill?.slug || "");
    showSkillsRestartPrompt("安装成功。");
  } catch (error) {
    setSkillsStatus(error.message || "skill 安装失败", "error");
  } finally {
    if (submitBtn) submitBtn.disabled = false;
  }
}

async function reinstallSelectedSkill() {
  if (!skillsState.agentId || !skillsState.selectedSlug) return;
  setSkillsStatus("正在重装 skill…", "muted");
  try {
    const response = await fetch(
      `/api/agents/${skillsState.agentId}/skills/${encodeURIComponent(skillsState.selectedSlug)}/reinstall`,
      { method: "POST" },
    );
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || "skill 重装失败");
    await refreshSkills(data.skill?.slug || skillsState.selectedSlug);
    showSkillsRestartPrompt("重装成功。");
  } catch (error) {
    setSkillsStatus(error.message || "skill 重装失败", "error");
  }
}

async function uninstallSelectedSkill() {
  if (!skillsState.agentId || !skillsState.selectedSlug) return;
  const confirmed = await confirmAction({
    title: "确认卸载",
    message: `确认卸载 ${skillsState.selectedSlug} 吗？`,
    confirmText: "卸载",
    confirmVariant: "danger",
  });
  if (!confirmed) return;
  setSkillsStatus("正在卸载 skill…", "muted");
  try {
    const response = await fetch(
      `/api/agents/${skillsState.agentId}/skills/${encodeURIComponent(skillsState.selectedSlug)}`,
      { method: "DELETE" },
    );
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || "skill 卸载失败");
    const removedSlug = skillsState.selectedSlug;
    setSelectedSkillDetail(null);
    await refreshSkills();
    showSkillsRestartPrompt(`${removedSlug} 已卸载。`);
  } catch (error) {
    setSkillsStatus(error.message || "skill 卸载失败", "error");
  }
}

async function openSoulPanel(agentId) {
  if (!soulDrawer || !agentId) return;
  closeAgentContextMenu();
  const requestedAgentId = agentId;
  soulState.agentId = agentId;
  soulState.originalContent = "";
  soulState.runtimeStatus = "stopped";
  if (soulEditor) {
    soulEditor.value = "";
    soulEditor.disabled = true;
  }
  renderMarkdownPreview("");
  syncSoulPreviewToEditor();
  setSoulStatus("正在加载 SOUL.md…", "muted");
  updateSoulDirtyState();
  openAnimatedLayer(soulDrawer);

  try {
    const response = await fetch(`/api/agents/${agentId}/soul`);
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "SOUL.md 加载失败");
    }
    if (soulState.agentId !== requestedAgentId) return;
    soulState.originalContent = data.content || "";
    soulState.runtimeStatus = data.agent?.runtime_status || "stopped";
    const isPreparing = data.agent?.readiness_status === "preparing";
    if (soulDrawerAgent) {
      soulDrawerAgent.textContent = `${data.agent?.name || agentId} · ${data.agent?.profile_name || ""}`;
    }
    if (soulDrawerPath) soulDrawerPath.textContent = data.path || "—";
    if (soulEditor) {
      soulEditor.disabled = isPreparing;
      soulEditor.value = soulState.originalContent;
      if (!isPreparing) soulEditor.focus();
    }
    renderMarkdownPreview(soulState.originalContent);
    syncSoulPreviewToEditor();
    setSoulStatus(isPreparing ? "SOUL.md 正在生成中，完成后才能编辑。" : (data.updated_at ? `最后保存：${formatAgentTime(data.updated_at)}` : "SOUL.md 尚未创建，保存后会写入文件。"), "muted");
  } catch (error) {
    if (soulState.agentId !== requestedAgentId) return;
    setSoulStatus(error.message || "SOUL.md 加载失败", "error");
  } finally {
    if (soulState.agentId === requestedAgentId) updateSoulDirtyState();
  }
}

async function closeSoulPanel({ force = false } = {}) {
  if (!soulDrawer || soulDrawer.hidden) return;
  if (!force && hasUnsavedSoulChanges()) {
    const confirmed = await confirmAction({
      title: "确认关闭",
      message: "SOUL.md 有未保存修改，确认关闭吗？",
      confirmText: "关闭",
      confirmVariant: "warning",
    });
    if (!confirmed) return;
  }
  closeAnimatedLayer(soulDrawer, () => {
    soulState.agentId = "";
    soulState.originalContent = "";
    soulState.runtimeStatus = "stopped";
    setSoulStatus("", "muted");
  });
}

async function saveSoulContent() {
  if (!soulState.agentId || !soulEditor || !saveSoul) return;
  const content = soulEditor.value;
  if (!content.trim()) {
    setSoulStatus("SOUL.md 内容不能为空。", "error");
    updateSoulDirtyState();
    return;
  }
  soulState.saving = true;
  saveSoul.textContent = "保存中…";
  updateSoulDirtyState();
  try {
    const response = await fetch(`/api/agents/${soulState.agentId}/soul`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "SOUL.md 保存失败");
    }
    soulState.originalContent = data.content || "";
    soulState.runtimeStatus = data.agent?.runtime_status || soulState.runtimeStatus;
    if (soulEditor.value !== soulState.originalContent) {
      soulEditor.value = soulState.originalContent;
      renderMarkdownPreview(soulEditor.value);
      syncSoulPreviewToEditor();
    }
    const runningHint = soulState.runtimeStatus === "running" ? "，重启该 agent 后生效" : "";
    setSoulStatus(`已保存${runningHint}。`, "success");
  } catch (error) {
    setSoulStatus(error.message || "SOUL.md 保存失败", "error");
  } finally {
    soulState.saving = false;
    saveSoul.textContent = "保存";
    updateSoulDirtyState();
  }
}

function renderAgents(agents, stats) {
  if (!agentList) return;
  if (window.__BOOTSTRAP__) window.__BOOTSTRAP__.agents = agents;
  processSoundNotifications(agents);
  debugLog("render-agents", agents.map((agent) => ({
    agent_id: agent.agent_id,
    status: agent.status,
    interaction_state: agent.interaction_state,
    orchestration_state: agent.orchestration_state,
    runtime_status: agent.runtime_status,
    readiness_status: agent.readiness_status || "ready",
    queue_depth: agent.queue_depth || 0,
    current_task: agent.current_task,
  })));
  closeAgentContextMenu();
  const readyAgents = agents.filter((agent) => (agent.readiness_status || "ready") === "ready");
  const currentSelected = eventList?.dataset.selectedAgent || "";
  const selected = readyAgents.some((agent) => agent.agent_id === currentSelected)
    ? currentSelected
    : (readyAgents[0] && readyAgents[0].agent_id) || "";
  agentList.innerHTML = "";
  agents.forEach((agent) => {
    if ((agent.readiness_status || "ready") === "ready") {
      ensureTerminalSession(agent.agent_id);
    }
    agentList.appendChild(buildAgentRow(agent, agent.agent_id === selected));
  });
  requestAnimationFrame(() => requestAnimationFrame(fitAllTerminalSessions));
  renderInteractions();
  if (agentEmpty) agentEmpty.hidden = agents.length > 0;
  if (sidebarStats && stats) {
    sidebarStats.innerHTML = stats
      .slice(0, 2)
      .map((s) => `<article class="mini-stat"><span>${escapeHtml(s.label)}</span><strong>${escapeHtml(s.value)}</strong></article>`)
      .join("");
  }
  if (readyAgents.length > 0) {
    const active = readyAgents.find((a) => a.agent_id === selected) || readyAgents[0];
    setSelectedAgent(active.agent_id);
  } else {
    if (eventList) eventList.dataset.selectedAgent = "";
    if (terminalTitle) terminalTitle.textContent = "Agent Terminal";
    writeEmptyTerminalHint();
  }
}

function setTransferStatus(element, message, isError = false) {
  if (!element) return;
  element.textContent = message || "";
  element.hidden = !message;
  element.style.color = isError ? "#ff8a8a" : "#8ff0b3";
}

function openTransferModal() {
  if (!transferModal) return;
  renderTransferAgents();
  setTransferStatus(transferExportStatus, "");
  setTransferStatus(transferImportStatus, "");
  if (transferImportPreview) transferImportPreview.hidden = true;
  if (transferImportSubmit) transferImportSubmit.disabled = true;
  transferLastInspectedFile = null;
  openAnimatedLayer(transferModal, transferExportSubmit);
}

function closeTransferModal() {
  if (!transferModal) return;
  closeAnimatedLayer(transferModal);
}

function renderTransferAgents() {
  if (!transferAgentList) return;
  const agents = window.__BOOTSTRAP__?.agents || [];
  if (!agents.length) {
    transferAgentList.innerHTML = `<p class="form-hint">暂无可导出的 Agent。</p>`;
    return;
  }
  transferAgentList.innerHTML = agents.map((agent) => `
    <label class="transfer-agent-item">
      <span><strong>${escapeHtml(agent.name || agent.profile_name)}</strong><br><small>${escapeHtml(agent.role)} · ${escapeHtml(agent.profile_name)}</small></span>
      <input type="checkbox" value="${escapeHtml(agent.profile_name)}" checked>
    </label>
  `).join("");
}

function switchTransferTab(tabName) {
  transferModal?.querySelectorAll("[data-transfer-tab]").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.transferTab === tabName);
  });
  transferModal?.querySelectorAll("[data-transfer-pane]").forEach((pane) => {
    pane.hidden = pane.dataset.transferPane !== tabName;
  });
}

async function exportTeamArchive() {
  const profileNames = Array.from(transferAgentList?.querySelectorAll("input:checked") || []).map((input) => input.value);
  if (!profileNames.length) {
    setTransferStatus(transferExportStatus, "请至少选择一个 Agent。", true);
    return;
  }
  transferExportSubmit.disabled = true;
  setTransferStatus(transferExportStatus, "正在导出…");
  try {
    const response = await fetch("/api/transfer/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        profile_names: profileNames,
        options: {
          inline_skill_files: Boolean(transferInlineSkills?.checked),
          include_workspace: Boolean(transferIncludeWorkspace?.checked),
        },
      }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || "导出失败");
    }
    const blob = await response.blob();
    const disposition = response.headers.get("content-disposition") || "";
    const match = disposition.match(/filename\*?=(?:UTF-8''|\")?([^";]+)/i);
    const filename = match ? decodeURIComponent(match[1].replace(/"/g, "")) : "hermes-agent-team.zip";
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setTransferStatus(transferExportStatus, "导出完成。请保存下载的 zip。");
  } catch (error) {
    setTransferStatus(transferExportStatus, error.message || "导出失败", true);
  } finally {
    transferExportSubmit.disabled = false;
  }
}

async function inspectTeamArchive() {
  const file = transferImportFile?.files?.[0];
  if (!file) {
    setTransferStatus(transferImportStatus, "请选择 zip 文件。", true);
    return;
  }
  transferInspectSubmit.disabled = true;
  if (transferImportSubmit) transferImportSubmit.disabled = true;
  setTransferStatus(transferImportStatus, "正在预检…");
  try {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch("/api/transfer/inspect", { method: "POST", body: formData });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || "预检失败");
    transferLastInspectedFile = file;
    renderImportPreview(data);
    if (transferImportSubmit) transferImportSubmit.disabled = false;
    setTransferStatus(transferImportStatus, "预检通过。确认后可导入。");
  } catch (error) {
    setTransferStatus(transferImportStatus, error.message || "预检失败", true);
  } finally {
    transferInspectSubmit.disabled = false;
  }
}

function renderImportPreview(data) {
  if (!transferImportPreview) return;
  const clear = data.will_clear || {};
  const secrets = data.missing_secrets || [];
  const rows = (data.agents || []).map((agent) => `
    <div class="transfer-preview-row"><span>${escapeHtml(agent.profile_name)}</span><small>${escapeHtml(agent.role || "worker")}</small></div>
  `).join("");
  const secretRows = secrets.length
    ? `<div class="transfer-secret-list"><strong>导入后需要补齐</strong>${secrets.map((item) => `<small>${escapeHtml(item)}</small>`).join("")}</div>`
    : `<p class="form-hint">未检测到需要手动补齐的凭据。</p>`;
  transferImportPreview.innerHTML = `
    <p class="form-hint">将导入 ${data.agents?.length || 0} 个 Agent；导入前会删除本机 ${clear.agents || 0} 个 Agent、${clear.workspaces || 0} 个 workspace，并清空运行历史。</p>
    ${rows || `<p class="form-hint">包内没有 Agent。</p>`}
    ${secretRows}
  `;
  transferImportPreview.hidden = false;
}

async function importTeamArchive() {
  const file = transferImportFile?.files?.[0];
  if (!file || file !== transferLastInspectedFile) {
    setTransferStatus(transferImportStatus, "请先预检当前文件。", true);
    return;
  }
  const confirmed = await confirmAction({
    title: "确认导入团队",
    message: "导入前将解雇并删除本机所有 agents、workspace 与运行历史，确认继续？",
    confirmText: "确认导入",
    confirmVariant: "danger",
  });
  if (!confirmed) return;
  transferImportSubmit.disabled = true;
  setTransferStatus(transferImportStatus, "正在导入…");
  try {
    const formData = new FormData();
    formData.append("file", file);
    const response = await fetch("/api/transfer/import", { method: "POST", body: formData });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || "导入失败");
    const success = (data.results || []).filter((item) => item.success).length;
    setTransferStatus(transferImportStatus, `导入完成：${success}/${(data.results || []).length} 成功。`);
  } catch (error) {
    setTransferStatus(transferImportStatus, error.message || "导入失败", true);
  } finally {
    transferImportSubmit.disabled = false;
  }
}

function hydrateChatEvents() {
  const events = Array.isArray(window.__BOOTSTRAP__?.events) ? window.__BOOTSTRAP__.events : [];
  events.slice().reverse().forEach((event) => {
    rememberChatEvent(event);
  });
}

function applyEventFilter() {
  if (eventEmpty) eventEmpty.hidden = Boolean(eventList?.dataset.selectedAgent);
}

function createTerminalInstance(agentId) {
  const term = new Terminal({
    cursorBlink: true,
    convertEol: true,
    fontFamily: '"JetBrains Mono", monospace',
    fontSize: 14,
    lineHeight: 1.42,
    scrollback: 5000,
    cols: defaultTerminalCols,
    rows: defaultTerminalRows,
    theme: {
      background: "#020201",
      foreground: "#fff8ea",
      cursor: "#f6cf75",
      selectionBackground: "#4a3511",
      black: "#090704",
      red: "#ff7b73",
      green: "#61e294",
      yellow: "#f0ab25",
      blue: "#b88935",
      magenta: "#d6a85a",
      cyan: "#f6cf75",
      white: "#f4efe4",
      brightBlack: "#b1a38f",
      brightWhite: "#fff8e8",
    },
  });
  const fitAddon = new FitAddon.FitAddon();
  const pane = document.createElement("div");
  pane.className = "terminal-pane";
  pane.dataset.agentId = agentId;
  term.loadAddon(fitAddon);
  terminalViewport.appendChild(pane);
  term.open(pane);
  term.onData((data) => {
    const session = terminalSessions.get(agentId);
    if (session && agentId !== "__empty__") {
      sendTerminalSocketMessage(session, { type: "input", data });
    }
  });
  return {
    agentId,
    term,
    fitAddon,
    pane,
    ws: null,
    lastRows: 0,
    lastCols: 0,
    reconnectTimer: 0,
    connectToken: 0,
    reconnectEnabled: false,
    hasRenderedOutput: false,
  };
}

function ensureTerminalSession(agentId) {
  if (!agentId || !terminalViewport || !window.Terminal || !window.FitAddon) {
    return null;
  }
  let session = terminalSessions.get(agentId);
  if (session) return session;
  session = createTerminalInstance(agentId);
  terminalSessions.set(agentId, session);
  return session;
}

function writeTerminalNotice(session, message) {
  if (!session || !message) return;
  session.term.write(`\x1b[90m${message}\x1b[0m\r\n`);
}

function resetTerminalSessionView(session, message = "") {
  if (!session) return;
  session.term.reset();
  session.term.clear();
  session.hasRenderedOutput = false;
  if (message) writeTerminalNotice(session, message);
}

function buildTerminalSocketUrl(agentId) {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/agents/${encodeURIComponent(agentId)}/terminal/ws`;
}

function clearTerminalReconnect(session) {
  if (!session?.reconnectTimer) return;
  window.clearTimeout(session.reconnectTimer);
  session.reconnectTimer = 0;
}

function disconnectTerminalSession(session) {
  if (!session || session.agentId === "__empty__") return;
  clearTerminalReconnect(session);
  session.reconnectEnabled = false;
  session.connectToken += 1;
  const ws = session.ws;
  session.ws = null;
  if (ws && ws.readyState < WebSocket.CLOSING) {
    ws.close();
  }
}

function sendTerminalSocketMessage(session, payload) {
  if (!session?.ws || session.ws.readyState !== WebSocket.OPEN) return false;
  session.ws.send(JSON.stringify(payload));
  return true;
}

function scheduleTerminalReconnect(session, delay = terminalReconnectDelay) {
  if (!session || !session.reconnectEnabled || session.reconnectTimer) return;
  if ((eventList?.dataset.selectedAgent || "") !== session.agentId) return;
  session.reconnectTimer = window.setTimeout(() => {
    session.reconnectTimer = 0;
    connectTerminalSession(session);
  }, delay);
}

function handleTerminalSocketMessage(session, payload) {
  if (!session || !payload || typeof payload !== "object") return;
  if (payload.type === "ready") {
    debugLog("terminal-ready", {
      agentId: session.agentId,
      rows: payload.rows,
      cols: payload.cols,
      snapshotTextLength: String(payload.snapshot_text || "").length,
      snapshotAnsiLength: String(payload.snapshot_ansi || "").length,
    });
    session.reconnectEnabled = true;
    const snapRows = typeof payload.rows === "number" ? payload.rows : 0;
    const snapCols = typeof payload.cols === "number" ? payload.cols : 0;
    const ansi = String(payload.snapshot_ansi || "");
    debugLog("terminal-ready-detail", {
      agentId: session.agentId,
      payloadRows: snapRows,
      payloadCols: snapCols,
      termBefore: { rows: session.term.rows, cols: session.term.cols },
      paneSize: session.pane ? { w: session.pane.offsetWidth, h: session.pane.offsetHeight, active: session.pane.classList.contains("is-active") } : null,
      ansiLen: ansi.length,
      ansiHead: JSON.stringify(ansi.slice(0, 240)),
      ansiTail: JSON.stringify(ansi.slice(-240)),
    });
    if (snapRows > 0 && snapCols > 0) {
      try { session.term.resize(snapCols, snapRows); } catch (_) {}
      session.lastRows = snapRows;
      session.lastCols = snapCols;
    }
    if (!restoreTerminalSnapshot(session, payload) && !session.hasRenderedOutput) {
      session.term.reset();
      session.term.clear();
    }
    debugLog("terminal-ready-after", {
      agentId: session.agentId,
      termAfter: { rows: session.term.rows, cols: session.term.cols },
    });
    requestAnimationFrame(() => requestAnimationFrame(() => {
      fitTerminal();
      fitTerminal();
    }));
    return;
  }
  if (payload.type === "output") {
    logTerminalPayload("terminal-output", session, payload);
    if (!session.hasRenderedOutput) {
      session.term.reset();
      session.term.clear();
      session.hasRenderedOutput = true;
    }
    session.term.write(String(payload.data || ""));
    return;
  }
  if (payload.type === "status") {
    session.reconnectEnabled = false;
    resetTerminalSessionView(session, payload.message || "终端不可用");
  }
}

function connectTerminalSession(session) {
  if (!session || session.agentId === "__empty__") return;
  if ((eventList?.dataset.selectedAgent || "") !== session.agentId) return;
  if (session.ws && (session.ws.readyState === WebSocket.OPEN || session.ws.readyState === WebSocket.CONNECTING)) {
    return;
  }
  clearTerminalReconnect(session);
  session.reconnectEnabled = true;
  const token = session.connectToken + 1;
  session.connectToken = token;
  resetTerminalSessionView(session, "正在连接终端…");
  const ws = new WebSocket(buildTerminalSocketUrl(session.agentId));
  session.ws = ws;

  ws.addEventListener("open", () => {
    if (session.connectToken !== token) return;
    debugLog("terminal-ws-open", { agentId: session.agentId });
    requestAnimationFrame(() => requestAnimationFrame(fitTerminal));
  });

  ws.addEventListener("message", (event) => {
    if (session.connectToken !== token) return;
    try {
      const payload = JSON.parse(event.data);
      if (payload?.type !== "output") {
        debugLog("terminal-ws-message", {
          agentId: session.agentId,
          type: payload?.type,
          payload,
        });
      }
      handleTerminalSocketMessage(session, payload);
    } catch (e) {
      debugLog("terminal-ws-message-error", { agentId: session.agentId, error: String(e) });
    }
  });

  ws.addEventListener("close", () => {
    if (session.connectToken !== token) return;
    debugLog("terminal-ws-close", { agentId: session.agentId, reconnect: session.reconnectEnabled });
    session.ws = null;
    if (session.reconnectEnabled) {
      resetTerminalSessionView(session, "终端连接已断开，正在重连…");
      scheduleTerminalReconnect(session);
    }
  });

  ws.addEventListener("error", () => {
    debugLog("terminal-ws-error", { agentId: session.agentId });
  });
}

function writeEmptyTerminalHint() {
  if (!terminalViewport) return;
  terminalSessions.forEach((session) => {
    if (session.agentId !== "__empty__") disconnectTerminalSession(session);
    session.pane.classList.remove("is-active");
  });
  let session = terminalSessions.get("__empty__");
  if (!session && window.Terminal && window.FitAddon) {
    session = createTerminalInstance("__empty__");
    terminalSessions.set("__empty__", session);
  }
  if (session) {
    resetTerminalSessionView(session, "还没有 Agent。创建并启动 Agent 后，这里会显示交互终端。");
    session.pane.classList.add("is-active");
    scheduleTerminalFit(0);
  }
}

function fitTerminalSession(session, tag = "") {
  if (!session) return;
  const pane = session.pane;
  const beforeRows = session.term.rows;
  const beforeCols = session.term.cols;
  const paneInfo = pane ? {
    offsetW: pane.offsetWidth,
    offsetH: pane.offsetHeight,
    clientW: pane.clientWidth,
    clientH: pane.clientHeight,
    isActive: pane.classList.contains("is-active"),
  } : null;
  try {
    session.fitAddon.fit();
    debugLog("terminal-fit", {
      tag,
      agentId: session.agentId,
      pane: paneInfo,
      before: { rows: beforeRows, cols: beforeCols },
      after: { rows: session.term.rows, cols: session.term.cols },
      last: { rows: session.lastRows, cols: session.lastCols },
    });
    if (session.agentId === "__empty__") return;
    if (session.term.rows !== session.lastRows || session.term.cols !== session.lastCols) {
      session.lastRows = session.term.rows;
      session.lastCols = session.term.cols;
      const sent = sendTerminalSocketMessage(session, {
        type: "resize",
        rows: session.term.rows,
        cols: session.term.cols,
      });
      debugLog("terminal-resize-sent", {
        tag,
        agentId: session.agentId,
        rows: session.term.rows,
        cols: session.term.cols,
        sent,
      });
    }
  } catch (e) {
    debugLog("terminal-fit-error", { tag, agentId: session.agentId, error: String(e), pane: paneInfo });
  }
}

function fitAllTerminalSessions() {
  terminalSessions.forEach((session) => fitTerminalSession(session));
}

function initTerminal() {
  if (!terminalViewport || !window.Terminal || !window.FitAddon) return;
  const selectedAgentId = eventList?.dataset.selectedAgent || "";
  if (selectedAgentId) {
    const session = ensureTerminalSession(selectedAgentId);
    if (session) connectTerminalSession(session);
  } else {
    writeEmptyTerminalHint();
  }
  scheduleTerminalFit(0);
  scheduleTerminalFit(80);
  requestAnimationFrame(() => requestAnimationFrame(fitTerminal));
}

function fitTerminal() {
  const agentId = eventList?.dataset.selectedAgent || "";
  const session = terminalSessions.get(agentId);
  if (!session || !session.pane.classList.contains("is-active")) return;
  fitTerminalSession(session);
}

function scheduleTerminalFit(delay = 120) {
  window.setTimeout(fitTerminal, delay);
}

function debounceTerminalFit(delay = 120) {
  clearTimeout(resizeTimer);
  resizeTimer = window.setTimeout(fitTerminal, delay);
}

function setSelectedAgent(agentId, agentName, force = false) {
  if (!agentList || !eventList) return;
  const row = agentList.querySelector(`.agent-row[data-agent-id="${CSS.escape(agentId)}"]`);
  if (row?.dataset.readinessStatus && row.dataset.readinessStatus !== "ready") return;
  const name = agentName || row?.dataset.agentName || agentId || "尚未选择";
  const changed = eventList.dataset.selectedAgent !== agentId;
  agentList.querySelectorAll(".agent-row").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.agentId === agentId);
  });
  eventList.dataset.selectedAgent = agentId;
  renderInteractions();
  if (terminalTitle) terminalTitle.textContent = agentId ? `${name} · Hermes Terminal` : "Agent Terminal";
  const session = ensureTerminalSession(agentId);
  terminalSessions.forEach((item, key) => {
    item.pane.classList.toggle("is-active", key === agentId);
    if (key !== agentId) disconnectTerminalSession(item);
  });
  debugLog("terminal-switch", {
    agentId,
    changed,
    force,
    sessionExists: !!session,
    paneSize: session?.pane ? { w: session.pane.offsetWidth, h: session.pane.offsetHeight } : null,
    termSize: session ? { rows: session.term.rows, cols: session.term.cols } : null,
  });
  if (session && (changed || force || !session.ws || session.ws.readyState > WebSocket.OPEN)) {
    requestAnimationFrame(() => {
      fitTerminalSession(session, "switch-pre-connect");
      connectTerminalSession(session);
      requestAnimationFrame(() => requestAnimationFrame(fitTerminal));
    });
  }
  scheduleTerminalFit(0);
  applyEventFilter();
}

function handleRuntimeEvent(event) {
  if (!eventList) return;
  if (event.event_type === "agent.terminal.output" || event.event_type === "agent.terminal.snapshot") {
    return;
  }
  if (rememberChatEvent(event)) renderInteractions();
  if (String(event.event_type || "").startsWith("kanban.")) {
    refreshKanbanTasks({ silent: true });
  }
}

function isIdleAgentRow(row) {
  return row?.dataset.agentStatus === "idle"
    && (row.dataset.agentOrchestrationState || "none") === "none";
}

function ensureAgentContextMenu() {
  if (agentContextMenu) return agentContextMenu;
  agentContextMenu = document.createElement("div");
  agentContextMenu.className = "agent-context-menu";
  agentContextMenu.hidden = true;
  agentContextMenu.dataset.mode = "danger";
  agentContextMenu.innerHTML = `
    <button class="agent-context-menu__item" type="button" data-agent-soul>
      SOUL.md
    </button>
    <button class="agent-context-menu__item" type="button" data-agent-skills>
      Skills
    </button>
    <button class="agent-context-menu__item" type="button" data-agent-mcp>
      MCP Servers
    </button>
    <button class="agent-context-menu__item" type="button" data-agent-open-workspace>
      打开工作目录
    </button>
    <div class="agent-context-menu__separator" data-config-separator></div>
    <button class="agent-context-menu__item agent-context-menu__item--danger" type="button" data-agent-delete>
      解雇
    </button>
  `;
  agentContextMenu.addEventListener("click", async (event) => {
    event.stopPropagation();
    const soulBtn = event.target.closest("[data-agent-soul]");
    if (soulBtn) {
      const agentId = agentContextMenu.dataset.agentId || "";
      if (agentId) openSoulPanel(agentId);
      closeAgentContextMenu();
      return;
    }
    const skillsBtn = event.target.closest("[data-agent-skills]");
    if (skillsBtn) {
      const agentId = agentContextMenu.dataset.agentId || "";
      if (agentId) openSkillsPanel(agentId);
      closeAgentContextMenu();
      return;
    }
    const mcpBtn = event.target.closest("[data-agent-mcp]");
    if (mcpBtn) {
      const agentId = agentContextMenu.dataset.agentId || "";
      if (agentId) openMcpPanel(agentId);
      closeAgentContextMenu();
      return;
    }
    const workspaceBtn = event.target.closest("[data-agent-open-workspace]");
    if (workspaceBtn) {
      const agentId = agentContextMenu.dataset.agentId || "";
      if (!agentId || workspaceBtn.disabled) return;
      workspaceBtn.disabled = true;
      try {
        const response = await fetch(`/api/agents/${agentId}/open-workspace`, { method: "POST" });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.ok) {
          alert(data.error || "打开工作目录失败");
          return;
        }
        closeAgentContextMenu();
      } finally {
        workspaceBtn.disabled = false;
      }
      return;
    }
    const btn = event.target.closest("[data-agent-delete]");
    if (!btn || btn.disabled) return;
    const agentId = agentContextMenu.dataset.agentId || "";
    const agentName = agentContextMenu.dataset.agentName || agentId;
    if (!agentId || deletingAgentId) return;

    const confirmed = await confirmAgentDismissal(agentName);
    if (!confirmed) {
      closeAgentContextMenu();
      return;
    }

    deletingAgentId = agentId;
    btn.disabled = true;
    try {
      const response = await fetch(`/api/agents/${agentId}`, { method: "DELETE" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) {
        alert(data.error || "解雇失败");
        return;
      }
      closeAgentContextMenu();
    } finally {
      deletingAgentId = "";
      btn.disabled = false;
    }
  });
  document.body.appendChild(agentContextMenu);
  return agentContextMenu;
}

function positionAgentContextMenu(menu, clientX, clientY) {
  menu.hidden = false;
  const padding = 8;
  const rect = menu.getBoundingClientRect();
  const left = Math.min(clientX, window.innerWidth - rect.width - padding);
  const top = Math.min(clientY, window.innerHeight - rect.height - padding);
  menu.style.left = `${Math.max(padding, left)}px`;
  menu.style.top = `${Math.max(padding, top)}px`;
}

function showAgentConfigMenu(row, trigger) {
  const menu = ensureAgentContextMenu();
  const soulBtn = menu.querySelector("[data-agent-soul]");
  const skillsBtn = menu.querySelector("[data-agent-skills]");
  const mcpBtn = menu.querySelector("[data-agent-mcp]");
  const separator = menu.querySelector("[data-config-separator]");
  const deleteBtn = menu.querySelector("[data-agent-delete]");
  const canDelete = isIdleAgentRow(row);
  const rect = trigger.getBoundingClientRect();
  menu.dataset.agentId = row.dataset.agentId || trigger.dataset.agentId || "";
  menu.dataset.agentName = row.dataset.agentName || "";
  menu.dataset.mode = "config";
  if (soulBtn) {
    const soulDisabled = (row.dataset.readinessStatus || "ready") === "preparing";
    soulBtn.hidden = false;
    soulBtn.disabled = soulDisabled;
    soulBtn.title = soulDisabled ? "SOUL.md 正在生成中" : "";
    soulBtn.textContent = soulDisabled ? "SOUL.md 生成中" : "SOUL.md";
  }
  if (skillsBtn) skillsBtn.hidden = false;
  if (mcpBtn) mcpBtn.hidden = false;
  if (separator) separator.hidden = false;
  if (deleteBtn) {
    deleteBtn.hidden = false;
    deleteBtn.disabled = !canDelete;
    deleteBtn.textContent = canDelete ? "解雇" : "仅 idle 可解雇";
  }
  positionAgentContextMenu(menu, rect.left, rect.bottom + 8);
}

function closeAgentContextMenu() {
  if (!agentContextMenu) return;
  agentContextMenu.hidden = true;
  agentContextMenu.dataset.agentId = "";
  agentContextMenu.dataset.agentName = "";
}

function confirmAgentDismissal(agentName) {
  const name = agentName || "该 Agent";
  return confirmAction({
    title: "确认解雇",
    message: `你要解雇 ${name} 吗？`,
    confirmText: "解雇",
    confirmVariant: "danger",
  });
}

function ensureConfirmModal() {
  if (confirmModal) return confirmModal;
  const modalEl = document.createElement("div");
  modalEl.className = "modal confirm-modal";
  modalEl.hidden = true;
  modalEl.innerHTML = `
    <div class="modal__backdrop" data-confirm-cancel></div>
    <div class="modal__panel panel confirm-modal__panel" role="dialog" aria-modal="true" aria-labelledby="confirm-modal-title">
      <div class="modal__head">
        <h2 id="confirm-modal-title" data-confirm-title>确认操作</h2>
      </div>
      <p class="confirm-modal__message" data-confirm-message></p>
      <div class="modal__actions">
        <button type="button" class="filter-chip" data-confirm-cancel>取消</button>
        <button type="button" class="confirm-modal__confirm" data-confirm-submit>确定</button>
      </div>
    </div>
  `;
  modalEl.resolve = null;
  const closeWith = (value) => {
    closeAnimatedLayer(modalEl, () => {
      const resolve = modalEl.resolve;
      modalEl.resolve = null;
      if (resolve) resolve(value);
    });
  };
  modalEl.addEventListener("click", (event) => {
    if (event.target.closest("[data-confirm-submit]")) {
      closeWith(true);
      return;
    }
    if (event.target.closest("[data-confirm-cancel]")) {
      closeWith(false);
    }
  });
  document.body.appendChild(modalEl);
  confirmModal = modalEl;
  return confirmModal;
}

function confirmAction({ title = "确认操作", message = "", confirmText = "确定", confirmVariant = "danger", hideCancel = false } = {}) {
  const modal = ensureConfirmModal();
  modal.querySelector("[data-confirm-title]").textContent = title;
  modal.querySelector("[data-confirm-message]").textContent = message;
  const cancelBtn = modal.querySelector("button[data-confirm-cancel]");
  if (cancelBtn) cancelBtn.hidden = hideCancel;
  const confirmBtn = modal.querySelector("[data-confirm-submit]");
  confirmBtn.textContent = confirmText;
  confirmBtn.dataset.variant = confirmVariant;
  openAnimatedLayer(modal, confirmBtn);

  return new Promise((resolve) => {
    modal.resolve = resolve;
  });
}

if (agentList) {
  agentList.addEventListener("click", (event) => {
    closeAgentContextMenu();
    const configBtn = event.target.closest("[data-agent-config]");
    if (configBtn) {
      event.stopPropagation();
      const row = configBtn.closest(".agent-row");
      if (row) showAgentConfigMenu(row, configBtn);
      return;
    }
    const skillsBtn = event.target.closest("[data-skills-open]");
    if (skillsBtn) {
      event.stopPropagation();
      openSkillsPanel(skillsBtn.dataset.agentId || "");
      return;
    }
    const mcpBtn = event.target.closest("[data-mcp-open]");
    if (mcpBtn) {
      event.stopPropagation();
      openMcpPanel(mcpBtn.dataset.agentId || "");
      return;
    }
    const soulBtn = event.target.closest("[data-soul-open]");
    if (soulBtn) {
      event.stopPropagation();
      openSoulPanel(soulBtn.dataset.agentId || "");
      return;
    }
    const btn = event.target.closest("[data-session-action]");
    if (btn) {
      event.stopPropagation();
      if (btn.disabled) return;
      const action = btn.dataset.sessionAction;
      const agentId = btn.dataset.agentId;
      btn.disabled = true;
      fetch(`/api/agents/${agentId}/${action}`, { method: "POST" })
        .catch(() => {})
        .finally(() => { btn.disabled = false; });
      return;
    }
    const row = event.target.closest(".agent-row");
    if (!row) return;
    if (row.dataset.readinessStatus && row.dataset.readinessStatus !== "ready") return;
    setSelectedAgent(row.dataset.agentId, row.dataset.agentName);
  });

  agentList.addEventListener("scroll", closeAgentContextMenu, { passive: true });
}

if (openTeamSettings) {
  openTeamSettings.addEventListener("click", openTransferModal);
}

if (transferModal) {
  transferModal.addEventListener("click", (event) => {
    if (event.target instanceof HTMLElement && event.target.dataset.closeTransfer !== undefined) {
      closeTransferModal();
      return;
    }
    const tab = event.target.closest("[data-transfer-tab]");
    if (tab) switchTransferTab(tab.dataset.transferTab || "export");
  });
}

transferExportSubmit?.addEventListener("click", exportTeamArchive);
transferInspectSubmit?.addEventListener("click", inspectTeamArchive);
transferImportSubmit?.addEventListener("click", importTeamArchive);
transferImportFile?.addEventListener("change", () => {
  transferLastInspectedFile = null;
  if (transferFileName) {
    transferFileName.textContent = transferImportFile.files?.[0]?.name || "选择 hermes-agent-team-时间.zip 文件";
  }
  if (transferImportSubmit) transferImportSubmit.disabled = true;
  if (transferImportPreview) transferImportPreview.hidden = true;
  setTransferStatus(transferImportStatus, "");
});

document.addEventListener("click", (event) => {
  if (agentContextMenu?.contains(event.target)) return;
  closeAgentContextMenu();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && confirmModal && !confirmModal.hidden) {
    event.preventDefault();
    event.stopImmediatePropagation();
    closeAnimatedLayer(confirmModal, () => {
      const resolve = confirmModal.resolve;
      confirmModal.resolve = null;
      if (resolve) resolve(false);
    });
    return;
  }
  if (event.key === "Escape") closeAgentContextMenu();
  if (event.key === "Escape" && terminalDrawer && !terminalDrawer.hidden) closeTerminalPanel();
  if (event.key === "Escape" && transferModal && !transferModal.hidden) closeTransferModal();
});

window.addEventListener("resize", closeAgentContextMenu);
window.addEventListener("resize", () => {
  debounceTerminalFit(120);
  window.setTimeout(fitAllTerminalSessions, 180);
});

if (window.ResizeObserver && terminalViewport) {
  const terminalResizeObserver = new ResizeObserver(() => debounceTerminalFit(60));
  terminalResizeObserver.observe(terminalViewport);
}

if (document.fonts?.ready) {
  document.fonts.ready.then(() => {
    scheduleTerminalFit(0);
    scheduleTerminalFit(160);
    window.setTimeout(fitAllTerminalSessions, 200);
  });
}

async function ensureHermesReadyForAgentCreation(button) {
  if (button) button.disabled = true;
  try {
    const { response, data } = await checkHermesStatus();
    if (response.ok && data.ok) return true;
    await confirmAction({
      title: "需要配置 Hermes",
      message: data.message || "Hermes 当前不可用，请先安装并配置 Hermes Agent。",
      confirmText: "知道了",
      confirmVariant: "default",
      hideCancel: true,
    });
    return false;
  } catch (error) {
    await confirmAction({
      title: "检测失败",
      message: "无法检测 Hermes 状态，请确认服务正常运行后重试。",
      confirmText: "知道了",
      confirmVariant: "default",
      hideCancel: true,
    });
    return false;
  } finally {
    if (button) button.disabled = false;
  }
}

function openModal() {
  if (!modal) return;
  if (createAgentError) {
    createAgentError.hidden = true;
    createAgentError.textContent = "";
  }
  openAnimatedLayer(modal, createAgentForm?.querySelector('input[name="name"]'));
}

function closeModal() {
  if (!modal) return;
  closeAnimatedLayer(modal, () => createAgentForm?.reset());
}

if (openCreateAgent) {
  openCreateAgent.addEventListener("click", async () => {
    if (await ensureHermesReadyForAgentCreation(openCreateAgent)) openModal();
  });
  window.setTimeout(() => {
    void checkHermesStatus().catch(() => {});
  }, 300);
}
if (openHistoryDrawer) openHistoryDrawer.addEventListener("click", openHistoryPanel);
if (kanbanTaskForm) kanbanTaskForm.addEventListener("submit", submitKanbanTask);
if (kanbanTaskInput) kanbanTaskInput.addEventListener("keydown", handleKanbanTaskInputKeydown);
if (kanbanRefresh) kanbanRefresh.addEventListener("click", () => refreshKanbanTasks());
if (kanbanAutoDispatch) kanbanAutoDispatch.addEventListener("click", toggleKanbanAutoDispatch);
if (kanbanDispatch) kanbanDispatch.addEventListener("click", dispatchKanbanOnce);
if (terminalDrawer) {
  terminalDrawer.addEventListener("click", (event) => {
    if (event.target instanceof HTMLElement && event.target.dataset.closeTerminal !== undefined) {
      closeTerminalPanel();
    }
  });
}
if (historyDrawer) {
  historyDrawer.addEventListener("click", (event) => {
    if (event.target instanceof HTMLElement && event.target.dataset.closeHistory !== undefined) {
      closeHistoryPanel();
    }
  });
}
if (soulDrawer) {
  soulDrawer.addEventListener("click", (event) => {
    if (event.target instanceof HTMLElement && event.target.dataset.closeSoul !== undefined) {
      void closeSoulPanel();
    }
  });
}
if (skillsDrawer) {
  skillsDrawer.addEventListener("click", (event) => {
    const restartBtn = event.target.closest("[data-skills-restart-agent]");
    if (restartBtn) {
      event.preventDefault();
      restartCurrentSkillsAgent(restartBtn);
      return;
    }
    if (event.target instanceof HTMLElement && event.target.dataset.closeSkills !== undefined) {
      closeSkillsPanel();
    }
  });
}
if (mcpDrawer) {
  mcpDrawer.addEventListener("click", (event) => {
    const restartBtn = event.target.closest("[data-mcp-restart-agent]");
    if (restartBtn) {
      event.preventDefault();
      restartCurrentMcpAgent(restartBtn);
      return;
    }
    const revealBtn = event.target.closest("[data-mcp-reveal]");
    if (revealBtn) {
      revealMcp(revealBtn.dataset.mcpReveal || "");
      return;
    }
    const editBtn = event.target.closest("[data-mcp-edit]");
    if (editBtn && !editBtn.disabled) {
      editMcp(editBtn.dataset.mcpEdit || "");
      return;
    }
    const testBtn = event.target.closest("[data-mcp-test]");
    if (testBtn) {
      testMcp(testBtn.dataset.mcpTest || "");
      return;
    }
    const deleteBtn = event.target.closest("[data-mcp-delete]");
    if (deleteBtn && !deleteBtn.disabled) {
      deleteMcp(deleteBtn.dataset.mcpDelete || "");
      return;
    }
    if (event.target instanceof HTMLElement && event.target.dataset.closeMcp !== undefined) {
      closeMcpPanel();
    }
  });
}
if (openMcpEdit) openMcpEdit.addEventListener("click", () => openMcpEditModal());
if (mcpRefresh) mcpRefresh.addEventListener("click", () => refreshMcps());
if (mcpEditModal) {
  mcpEditModal.addEventListener("click", (event) => {
    if (event.target instanceof HTMLElement && event.target.dataset.closeMcpEdit !== undefined) {
      closeMcpEditModal();
    }
  });
}
if (mcpEditForm) {
  mcpEditForm.addEventListener("submit", (event) => {
    event.preventDefault();
    saveMcpFromForm();
  });
  mcpEditForm.elements.transport.addEventListener("change", toggleMcpTransportFields);
}
if (mcpSaveTest) {
  mcpSaveTest.addEventListener("click", () => saveMcpFromForm({ testAfter: true }));
}
if (openSkillsInstall) openSkillsInstall.addEventListener("click", openSkillsInstallModal);
if (skillsInstallModal) {
  skillsInstallModal.addEventListener("click", (event) => {
    if (event.target instanceof HTMLElement && event.target.dataset.closeSkillsInstall !== undefined) {
      closeSkillsInstallModal();
    }
  });
}
if (skillsList) {
  skillsList.addEventListener("click", (event) => {
    const row = event.target.closest(".skill-row");
    if (!row) return;
    loadSkillDetail(row.dataset.slug || "");
  });
}
if (skillsAlphaNav) {
  skillsAlphaNav.addEventListener("click", (event) => {
    const button = event.target.closest(".skill-alpha-chip");
    if (!button || button.disabled) return;
    setSkillsLetterFilter(button.dataset.letter || "ALL");
  });
}
if (skillsInstallForm) skillsInstallForm.addEventListener("submit", installSkillFromForm);
if (skillsRefresh) skillsRefresh.addEventListener("click", () => refreshSkills());
if (skillsReinstall) skillsReinstall.addEventListener("click", reinstallSelectedSkill);
if (skillsUninstall) skillsUninstall.addEventListener("click", uninstallSelectedSkill);
if (soulEditor) {
  soulEditor.addEventListener("input", () => {
    const scrollRatio = getScrollRatio(soulEditor);
    renderMarkdownPreview(soulEditor.value);
    if (soulPreview) setScrollRatio(soulPreview, scrollRatio);
    updateSoulDirtyState();
  });
  soulEditor.addEventListener("scroll", () => {
    syncSoulScroll(soulEditor, soulPreview, "editor");
  });
}
if (soulPreview) {
  soulPreview.addEventListener("scroll", () => {
    syncSoulScroll(soulPreview, soulEditor, "preview");
  });
}
if (saveSoul) saveSoul.addEventListener("click", saveSoulContent);
if (modal) {
  modal.addEventListener("click", (event) => {
    if (event.target instanceof HTMLElement && event.target.dataset.closeModal !== undefined) {
      closeModal();
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.hidden) closeModal();
    if (e.key === "Escape" && skillsInstallModal && !skillsInstallModal.hidden) {
      closeSkillsInstallModal();
      return;
    }
    if (e.key === "Escape" && mcpEditModal && !mcpEditModal.hidden) {
      closeMcpEditModal();
      return;
    }
    if (e.key === "Escape") closeHistoryPanel();
    if (e.key === "Escape") void closeSoulPanel();
    if (e.key === "Escape") closeSkillsPanel();
  });
}

if (createAgentForm) {
  createAgentForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(createAgentForm);
    const payload = {
      name: formData.get("name"),
      profile_name: formData.get("profile_name"),
      role: formData.get("role"),
      description: formData.get("description"),
    };
    const submitBtn = createAgentForm.querySelector('button[type="submit"]');
    if (submitBtn) submitBtn.disabled = true;
    try {
      const response = await fetch("/api/agents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) {
        if (createAgentError) {
          createAgentError.textContent = data.error || "创建失败";
          createAgentError.hidden = false;
        }
        return;
      }
      closeModal();
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  });
}

const stream = new EventSource("/api/events/stream");
stream.addEventListener("event", (event) => {
  const payload = JSON.parse(event.data);
  handleRuntimeEvent(payload);
});
stream.addEventListener("agents", (event) => {
  const payload = JSON.parse(event.data);
  debugLog("sse-agents", payload);
  renderAgents(payload.agents || [], payload.stats || []);
});
stream.onmessage = (event) => {
  try {
    const payload = JSON.parse(event.data);
    if (payload && payload.event_type) handleRuntimeEvent(payload);
  } catch (e) {
    /* ignore */
  }
};

hydrateChatEvents();
hydrateNotificationStates(window.__BOOTSTRAP__?.agents || []);
renderKanbanTasks();
renderKanbanAutoDispatch();
void loadKanbanSettings();
initTerminal();
if (eventList?.dataset.selectedAgent) {
  const row = agentList?.querySelector(`.agent-row[data-agent-id="${CSS.escape(eventList.dataset.selectedAgent)}"]`);
  if (!row?.dataset.readinessStatus || row.dataset.readinessStatus === "ready") {
    setSelectedAgent(eventList.dataset.selectedAgent, row?.dataset.agentName, true);
  }
}
applyEventFilter();
