const terminalShell = document.getElementById("terminal-shell");
const terminalViewport = document.getElementById("terminal-viewport");
const terminalTitle = document.getElementById("terminal-title");
const eventList = terminalShell;
const agentList = document.getElementById("agent-list");
const agentEmpty = document.getElementById("agent-empty");
const eventEmpty = document.getElementById("event-empty");
const sidebarStats = document.getElementById("sidebar-stats");
const openCreateAgent = document.getElementById("open-create-agent");
const modal = document.getElementById("create-agent-modal");
const createAgentForm = document.getElementById("create-agent-form");
const createAgentError = document.getElementById("create-agent-error");
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
const terminalSessions = new Map();
const chatEventsByAgent = new Map();
const defaultTerminalCols = 120;
const defaultTerminalRows = 36;
const terminalReconnectDelay = 900;
const hermesDebug = window.localStorage?.getItem("hermesDebug") !== "0";
let agentContextMenu = null;
let deletingAgentId = "";
let dismissAgentModal = null;
let resizeTimer = 0;
const soulState = {
  agentId: "",
  runtimeStatus: "stopped",
  originalContent: "",
  saving: false,
  scrollSyncSource: "",
  scrollSyncTimer: 0,
};

function debugLog(event, payload) {
  if (!hermesDebug) return;
  console.debug(`[hermes-debug] ${event}`, payload);
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
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
  if (
    status === "busy" ||
    status === "waiting" ||
    interactionState === "queued" ||
    interactionState === "running" ||
    orchestrationState === "waiting_workers" ||
    orchestrationState === "summarizing"
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
    ? `<button class="acp-btn acp-btn--start" type="button" data-session-action="start" data-agent-id="${agent.agent_id}" disabled>启动</button>`
    : runtimeStatus === "running"
    ? `<button class="acp-btn acp-btn--stop" type="button" data-session-action="stop" data-agent-id="${agent.agent_id}">停止</button>`
    : `<button class="acp-btn acp-btn--start" type="button" data-session-action="start" data-agent-id="${agent.agent_id}">启动</button>`;
  const soulDisabled = readinessStatus === "preparing" ? " disabled title=\"SOUL.md 正在生成中\"" : "";
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
        <button class="acp-btn acp-btn--soul" type="button" data-soul-open data-agent-id="${agent.agent_id}"${soulDisabled}>SOUL</button>
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
  historyDrawer.hidden = false;
  requestAnimationFrame(() => {
    historyDrawer.classList.add("is-open");
  });
}

function closeHistoryPanel() {
  if (!historyDrawer || historyDrawer.hidden) return;
  historyDrawer.classList.remove("is-open");
  window.setTimeout(() => {
    if (!historyDrawer.classList.contains("is-open")) {
      historyDrawer.hidden = true;
    }
  }, 180);
}

function setSoulStatus(message, kind = "muted") {
  if (!soulStatus) return;
  soulStatus.textContent = message || "";
  soulStatus.dataset.kind = kind;
  soulStatus.hidden = !message;
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
  soulDrawer.hidden = false;
  requestAnimationFrame(() => soulDrawer.classList.add("is-open"));

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

function closeSoulPanel({ force = false } = {}) {
  if (!soulDrawer || soulDrawer.hidden) return;
  if (!force && hasUnsavedSoulChanges() && !window.confirm("SOUL.md 有未保存修改，确认关闭吗？")) {
    return;
  }
  soulDrawer.classList.remove("is-open");
  window.setTimeout(() => {
    if (!soulDrawer.classList.contains("is-open")) {
      soulDrawer.hidden = true;
      soulState.agentId = "";
      soulState.originalContent = "";
      soulState.runtimeStatus = "stopped";
      setSoulStatus("", "muted");
    }
  }, 180);
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
    fontSize: 13,
    lineHeight: 1.35,
    scrollback: 5000,
    cols: defaultTerminalCols,
    rows: defaultTerminalRows,
    theme: {
      background: "#020201",
      foreground: "#f4efe4",
      cursor: "#f6cf75",
      selectionBackground: "#4a3511",
      black: "#090704",
      red: "#ff7b73",
      green: "#61e294",
      yellow: "#d99a21",
      blue: "#b88935",
      magenta: "#d6a85a",
      cyan: "#f6cf75",
      white: "#f4efe4",
      brightBlack: "#82786a",
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
    session.reconnectEnabled = true;
    if (typeof payload.rows === "number") session.lastRows = payload.rows;
    if (typeof payload.cols === "number") session.lastCols = payload.cols;
    if (!session.hasRenderedOutput) {
      session.term.reset();
      session.term.clear();
    }
    requestAnimationFrame(() => requestAnimationFrame(fitTerminal));
    return;
  }
  if (payload.type === "output") {
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
    requestAnimationFrame(() => requestAnimationFrame(fitTerminal));
  });

  ws.addEventListener("message", (event) => {
    if (session.connectToken !== token) return;
    try {
      handleTerminalSocketMessage(session, JSON.parse(event.data));
    } catch (e) {
      debugLog("terminal-ws-message-error", { agentId: session.agentId, error: String(e) });
    }
  });

  ws.addEventListener("close", () => {
    if (session.connectToken !== token) return;
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

function fitTerminalSession(session) {
  if (!session) return;
  try {
    session.fitAddon.fit();
    if (session.agentId === "__empty__") return;
    if (session.term.rows !== session.lastRows || session.term.cols !== session.lastCols) {
      session.lastRows = session.term.rows;
      session.lastCols = session.term.cols;
      sendTerminalSocketMessage(session, {
        type: "resize",
        rows: session.term.rows,
        cols: session.term.cols,
      });
    }
  } catch (e) {
    /* xterm can throw while hidden or before fonts/layout are ready */
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
  if (session && (changed || force || !session.ws || session.ws.readyState > WebSocket.OPEN)) {
    connectTerminalSession(session);
    requestAnimationFrame(() => requestAnimationFrame(fitTerminal));
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
  agentContextMenu.innerHTML = `
    <button class="agent-context-menu__item" type="button" data-agent-soul>
      SOUL.md
    </button>
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

function showAgentContextMenu(row, clientX, clientY) {
  const menu = ensureAgentContextMenu();
  const deleteBtn = menu.querySelector("[data-agent-delete]");
  const canDelete = isIdleAgentRow(row);
  menu.dataset.agentId = row.dataset.agentId || "";
  menu.dataset.agentName = row.dataset.agentName || "";
  if (deleteBtn) {
    deleteBtn.disabled = !canDelete;
    deleteBtn.textContent = canDelete ? "解雇" : "仅 idle 可解雇";
  }
  positionAgentContextMenu(menu, clientX, clientY);
}

function closeAgentContextMenu() {
  if (!agentContextMenu) return;
  agentContextMenu.hidden = true;
  agentContextMenu.dataset.agentId = "";
  agentContextMenu.dataset.agentName = "";
}

function confirmAgentDismissal(agentName) {
  const modal = ensureDismissAgentModal();
  const name = agentName || "该 Agent";
  modal.querySelector("[data-dismiss-agent-message]").textContent = `你要解雇 ${name} 吗？`;
  modal.hidden = false;
  const confirmBtn = modal.querySelector("[data-dismiss-agent-confirm]");
  confirmBtn.focus();

  return new Promise((resolve) => {
    dismissAgentModal.resolve = resolve;
  });
}

function ensureDismissAgentModal() {
  if (dismissAgentModal) return dismissAgentModal;
  const modalEl = document.createElement("div");
  modalEl.className = "modal dismiss-agent-modal";
  modalEl.hidden = true;
  modalEl.innerHTML = `
    <div class="modal__backdrop" data-dismiss-agent-cancel></div>
    <div class="modal__panel panel dismiss-agent-modal__panel" role="dialog" aria-modal="true" aria-labelledby="dismiss-agent-title">
      <div class="modal__head">
        <h2 id="dismiss-agent-title">确认解雇</h2>
      </div>
      <p class="dismiss-agent-modal__message" data-dismiss-agent-message></p>
      <div class="modal__actions">
        <button type="button" class="filter-chip" data-dismiss-agent-cancel>取消</button>
        <button type="button" class="dismiss-agent-modal__confirm" data-dismiss-agent-confirm>解雇</button>
      </div>
    </div>
  `;
  modalEl.resolve = null;
  const closeWith = (value) => {
    modalEl.hidden = true;
    const resolve = modalEl.resolve;
    modalEl.resolve = null;
    if (resolve) resolve(value);
  };
  modalEl.addEventListener("click", (event) => {
    if (event.target.closest("[data-dismiss-agent-confirm]")) {
      closeWith(true);
      return;
    }
    if (event.target.closest("[data-dismiss-agent-cancel]")) {
      closeWith(false);
    }
  });
  document.body.appendChild(modalEl);
  dismissAgentModal = modalEl;
  return dismissAgentModal;
}

if (agentList) {
  agentList.addEventListener("click", (event) => {
    closeAgentContextMenu();
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

  agentList.addEventListener("contextmenu", (event) => {
    const row = event.target.closest(".agent-row");
    if (!row) return;
    event.preventDefault();
    showAgentContextMenu(row, event.clientX, event.clientY);
  });

  agentList.addEventListener("scroll", closeAgentContextMenu, { passive: true });
}

document.addEventListener("click", (event) => {
  if (agentContextMenu?.contains(event.target)) return;
  closeAgentContextMenu();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && dismissAgentModal && !dismissAgentModal.hidden) {
    dismissAgentModal.hidden = true;
    const resolve = dismissAgentModal.resolve;
    dismissAgentModal.resolve = null;
    if (resolve) resolve(false);
  }
  if (event.key === "Escape") closeAgentContextMenu();
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

function openModal() {
  if (!modal) return;
  modal.hidden = false;
  if (createAgentError) {
    createAgentError.hidden = true;
    createAgentError.textContent = "";
  }
  createAgentForm?.querySelector('input[name="name"]').focus();
}

function closeModal() {
  if (!modal) return;
  modal.hidden = true;
  createAgentForm?.reset();
}

if (openCreateAgent) openCreateAgent.addEventListener("click", openModal);
if (openHistoryDrawer) openHistoryDrawer.addEventListener("click", openHistoryPanel);
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
      closeSoulPanel();
    }
  });
}
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
    if (e.key === "Escape") closeHistoryPanel();
    if (e.key === "Escape") closeSoulPanel();
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
initTerminal();
if (eventList?.dataset.selectedAgent) {
  const row = agentList?.querySelector(`.agent-row[data-agent-id="${CSS.escape(eventList.dataset.selectedAgent)}"]`);
  if (!row?.dataset.readinessStatus || row.dataset.readinessStatus === "ready") {
    setSelectedAgent(eventList.dataset.selectedAgent, row?.dataset.agentName, true);
  }
}
applyEventFilter();
