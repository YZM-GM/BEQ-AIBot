const chatBox = document.getElementById("chat-box");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send-btn");
const usageBar = document.getElementById("usage-bar");

const state = {
  currentPanel: "chat-panel",
  agents: [],
  selectedAgent: null,
  selectedSkill: null,
  selectedSoul: null,
  mcpData: null,
  selectedMcpId: null,
  skills: [],
  souls: [],
  conversations: [],
  selectedConversation: null,
  groupTaskBoard: [],
  scheduler: [],
};

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function api(path, options = {}) {
  const config = { ...options };
  if (config.body && typeof config.body !== "string") {
    config.headers = { ...(config.headers || {}), "Content-Type": "application/json" };
    config.body = JSON.stringify(config.body);
  }
  const res = await fetch(path, config);
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error) {
    throw new Error(data.error || `请求失败: ${res.status}`);
  }
  return data;
}

function setActivePanel(panelId) {
  state.currentPanel = panelId;
  document.querySelectorAll(".nav-btn").forEach((button) => {
    button.classList.toggle("active", button.dataset.panel === panelId);
  });
  document.querySelectorAll(".panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === panelId);
  });
}

function autoResize() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 160) + "px";
}

function renderConversationMeta() {
  const meta = document.getElementById("conversation-meta");
  const conversation = state.selectedConversation;
  if (!conversation) {
    meta.innerHTML = '<div class="empty-state">请选择会话</div>';
    return;
  }
  const memberText = conversation.type === "group"
    ? `群主：${escapeHtml(conversation.owner_agent || "-")} | 成员：${escapeHtml((conversation.member_agents || []).join(", "))}`
    : `当前 Agent：${escapeHtml(conversation.owner_agent || "-")}`;
  meta.innerHTML = `
    <div>
      <h3>${escapeHtml(conversation.title)}</h3>
      <p>${conversation.type === "group" ? "群聊" : "单聊"} · ${memberText}</p>
    </div>
  `;
}

function renderTaskBoard() {
  const board = document.getElementById("group-task-board");
  const conversation = state.selectedConversation;
  if (!conversation || conversation.type !== "group") {
    board.innerHTML = '<div class="empty-state">当前会话无需展示群聊任务板</div>';
    return;
  }
  if (!state.groupTaskBoard.length) {
    board.innerHTML = '<div class="empty-state">等待群主生成任务安排</div>';
    return;
  }
  board.innerHTML = `
    <h3>任务安排与进度</h3>
    <div class="task-board-grid">
      ${state.groupTaskBoard.map((task) => `
        <div class="list-item">
          <h4>${escapeHtml(task.title)}</h4>
          <p>执行者：${escapeHtml(task.assignee || "-")}</p>
          <div class="meta-row">
            <span class="badge">${escapeHtml(task.status || "pending")}</span>
          </div>
          <p>${escapeHtml(task.progress_note || "")}</p>
        </div>
      `).join("")}
    </div>
  `;
}

function appendChatEvent(roleClass, title, body = "", meta = "") {
  const el = document.createElement("div");
  el.className = `msg ${roleClass}`;
  el.innerHTML = `
    <div class="trace-title">${escapeHtml(title)}</div>
    ${meta ? `<div class="trace-body">${escapeHtml(meta)}</div>` : ""}
    ${body ? `<div class="final-answer">${escapeHtml(body)}</div>` : ""}
  `;
  chatBox.appendChild(el);
  chatBox.scrollTop = chatBox.scrollHeight;
}

function clearChatView() {
  chatBox.innerHTML = "";
  usageBar.textContent = "";
}

function renderConversationList() {
  const el = document.getElementById("conversation-list");
  if (!state.conversations.length) {
    el.innerHTML = '<div class="empty-state">暂无会话</div>';
    return;
  }
  el.innerHTML = state.conversations.map((item) => `
    <div class="list-item ${state.selectedConversation?.id === item.id ? "active" : ""}" data-key="${escapeHtml(item.id)}">
      <h4>${escapeHtml(item.title)}</h4>
      <p>${item.type === "group" ? "群聊" : "单聊"} · ${escapeHtml(item.last_message_preview || "暂无消息")}</p>
      <div class="meta-row">
        <span class="badge">${item.type === "group" ? "Group" : "Single"}</span>
      </div>
    </div>
  `).join("");
  el.querySelectorAll(".list-item").forEach((node) => {
    node.addEventListener("click", () => {
      state.selectedConversation = state.conversations.find((item) => item.id === node.dataset.key) || null;
      state.groupTaskBoard = [];
      clearChatView();
      renderConversationList();
      renderConversationMeta();
      renderTaskBoard();
    });
  });
}

async function createSingleConversation() {
  const ownerAgent = state.selectedAgent?.name || state.agents[0]?.name;
  if (!ownerAgent) {
    alert("没有可用 agent");
    return;
  }
  await api("/api/conversations", {
    method: "POST",
    body: {
      type: "single",
      title: `${ownerAgent} 单聊`,
      owner_agent: ownerAgent,
      member_agents: [ownerAgent],
    },
  });
  await loadConversations();
}

async function createGroupConversation() {
  if (!state.agents.length) {
    alert("没有可用 agent");
    return;
  }
  const title = prompt("输入群聊名称", `群聊-${new Date().toISOString().slice(11, 19)}`);
  if (title === null) return;
  const ownerAgent = prompt("输入群主 agent 名称", state.agents[0]?.name || "");
  if (!ownerAgent) return;
  const members = prompt("输入成员 agent，使用逗号分隔", state.agents.map((item) => item.name).join(","));
  if (members === null) return;
  await api("/api/conversations", {
    method: "POST",
    body: {
      type: "group",
      title,
      owner_agent: ownerAgent.trim(),
      member_agents: members.split(",").map((item) => item.trim()).filter(Boolean),
    },
  });
  await loadConversations();
}

async function sendMessage() {
  const conversation = state.selectedConversation;
  const text = input.value.trim();
  if (!conversation || !text) return;

  input.value = "";
  autoResize();
  sendBtn.disabled = true;
  usageBar.textContent = "";

  appendChatEvent("user", "用户", text);

  try {
    const createData = await api(`/api/conversations/${encodeURIComponent(conversation.id)}/turns`, {
      method: "POST",
      body: { message: text },
    });

    const es = new EventSource(`/api/conversations/${encodeURIComponent(conversation.id)}/stream/${encodeURIComponent(createData.turn_id)}`);
    es.onmessage = (evt) => {
      const payload = JSON.parse(evt.data);
      const type = payload.type;
      const data = payload.data || {};

      if (type === "conversation_meta") {
        state.scheduler = data.scheduler || [];
      } else if (type === "task_board") {
        state.groupTaskBoard = data.tasks || [];
        renderTaskBoard();
      } else if (type === "agent_message") {
        appendChatEvent("bot", data.agent_name || "Agent", data.content || "", data.role === "owner" ? "群主" : "成员");
      } else if (type === "tool_call") {
        appendChatEvent("bot", `${data.agent_name || "Agent"} 调用工具`, JSON.stringify(data.arguments || {}, null, 2), data.tool_name || "");
      } else if (type === "tool_result") {
        appendChatEvent("bot", `${data.agent_name || "Agent"} 工具返回`, data.result || "", data.tool_name || "");
      } else if (type === "group_status") {
        appendChatEvent("bot", `${data.agent_name || "Agent"} 状态`, data.status || "", data.role || "");
      } else if (type === "final_answer") {
        if (data.task_board) {
          state.groupTaskBoard = data.task_board;
          renderTaskBoard();
        }
        appendChatEvent("bot", "最终总结", data.content || "");
        es.close();
        sendBtn.disabled = false;
        input.focus();
        loadConversations().catch(console.error);
      } else if (type === "cycle_message") {
        appendChatEvent("bot", conversation.owner_agent || "Agent", data.content || payload.message || "");
      } else if (type === "tool_call") {
        appendChatEvent("bot", "工具调用", JSON.stringify(data.arguments || {}, null, 2), data.tool_name || "");
      } else if (type === "tool_result") {
        appendChatEvent("bot", "工具返回", data.result || "", data.tool_name || "");
      } else if (type === "final_answer") {
        appendChatEvent("bot", "回答", data.content || "");
        es.close();
        sendBtn.disabled = false;
        input.focus();
        loadConversations().catch(console.error);
      } else if (type === "error") {
        appendChatEvent("error", "错误", payload.message || data.message || "");
        es.close();
        sendBtn.disabled = false;
        input.focus();
      } else if (type === "turn_end") {
        es.close();
        sendBtn.disabled = false;
        input.focus();
        loadConversations().catch(console.error);
      }
    };

    es.onerror = () => {
      appendChatEvent("error", "错误", "流连接中断");
      es.close();
      sendBtn.disabled = false;
      input.focus();
    };
  } catch (err) {
    appendChatEvent("error", "网络错误", String(err.message || err));
    sendBtn.disabled = false;
    input.focus();
  }
}

function renderAgentOptions() {
  if (!state.selectedAgent && state.agents.length) {
    state.selectedAgent = state.agents[0];
  }
}

function renderList(containerId, items, activeKey, clickHandler, renderItem) {
  const el = document.getElementById(containerId);
  if (!items.length) {
    el.innerHTML = '<div class="empty-state">暂无数据</div>';
    return;
  }
  el.innerHTML = items.map((item) => renderItem(item, item.name === activeKey || item.url === activeKey || item.id === activeKey)).join("");
  el.querySelectorAll(".list-item").forEach((node) => {
    node.addEventListener("click", () => clickHandler(node.dataset.key));
  });
}

function renderAgentList() {
  renderList(
    "agent-list",
    state.agents,
    state.selectedAgent?.name,
    (name) => {
      state.selectedAgent = state.agents.find((item) => item.name === name) || null;
      renderAgentList();
      renderAgentDetail();
      renderAgentOptions();
    },
    (item, active) => `
      <div class="list-item ${active ? "active" : ""}" data-key="${escapeHtml(item.name)}">
        <h4>${escapeHtml(item.name)}</h4>
        <p>soul: ${escapeHtml(item.soul || "default")}</p>
        <div class="meta-row">
          <span class="badge ${item.enabled ? "success" : "danger"}">${item.enabled ? "启用" : "禁用"}</span>
          <span class="badge">MCP ${item.allowed_mcps?.length || 0}</span>
          <span class="badge">Skill ${item.allowed_skills?.length || 0}</span>
        </div>
      </div>
    `
  );
}

function currentMcpOptions() {
  const items = state.mcpData?.items || [];
  return items.map((item) => ({
    value: item.id,
    label: item.kind === "local" ? "本地 MCP" : (item.name || item.url || item.id),
  }));
}

function currentSkillNames() {
  return state.skills.map((item) => item.name).sort();
}

function currentSoulNames() {
  return state.souls.map((item) => item.name).sort();
}

function renderCheckboxes(items, selected) {
  const selectedSet = new Set(selected || []);
  return `
    <div class="checkbox-grid">
      ${items.map((item) => `
        <label class="checkbox-item">
          <input type="checkbox" value="${escapeHtml(item.value)}" ${selectedSet.has(item.value) ? "checked" : ""} />
          <span>${escapeHtml(item.label)}</span>
        </label>
      `).join("")}
    </div>
  `;
}

function renderAgentDetail(isNew = false) {
  const target = isNew ? {
    name: "",
    soul: state.souls[0]?.name || "default",
    allowed_mcps: [],
    allowed_skills: [],
    enabled: true,
  } : state.selectedAgent;
  const el = document.getElementById("agent-detail");
  if (!target) {
    el.innerHTML = '<div class="empty-state">请选择一个 agent</div>';
    return;
  }

  el.innerHTML = `
    <form id="agent-form" class="detail-pane-form">
      <div class="form-grid">
        <label class="form-field">
          <span>名称</span>
          <input name="name" value="${escapeHtml(target.name || "")}" ${isNew ? "" : "disabled"} />
        </label>
        <label class="form-field">
          <span>Soul</span>
          <select name="soul">
            ${currentSoulNames().map((name) => `<option value="${escapeHtml(name)}" ${name === target.soul ? "selected" : ""}>${escapeHtml(name)}</option>`).join("")}
          </select>
        </label>
        <label class="form-field full">
          <span>允许的 MCP</span>
          ${renderCheckboxes(currentMcpOptions(), target.allowed_mcps || [])}
        </label>
        <label class="form-field full">
          <span>允许的 Skills</span>
          ${renderCheckboxes(currentSkillNames().map((name) => ({ value: name, label: name })), target.allowed_skills || [])}
        </label>
        <label class="form-field">
          <span>状态</span>
          <select name="enabled">
            <option value="true" ${target.enabled ? "selected" : ""}>启用</option>
            <option value="false" ${!target.enabled ? "selected" : ""}>禁用</option>
          </select>
        </label>
      </div>
      <div class="toolbar">
        <button type="submit">${isNew ? "创建" : "保存"}</button>
        ${isNew ? "" : '<button type="button" class="danger" id="delete-agent-btn">删除</button>'}
      </div>
    </form>
  `;

  const form = document.getElementById("agent-form");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const mcpOptions = currentMcpOptions();
    const skillOptions = currentSkillNames().map((name) => ({ value: name, label: name }));
    const checkedValues = Array.from(form.querySelectorAll('input[type="checkbox"]:checked')).map((node) => node.value);
    const mcpValues = new Set(mcpOptions.map((item) => item.value));
    const skillValues = new Set(skillOptions.map((item) => item.value));
    const body = {
      soul: form.elements.soul.value,
      enabled: form.elements.enabled.value === "true",
      allowed_mcps: checkedValues.filter((value) => mcpValues.has(value)),
      allowed_skills: checkedValues.filter((value) => skillValues.has(value)),
    };

    try {
      if (isNew) {
        body.name = form.elements.name.value.trim();
        await api("/api/manage/agents", { method: "POST", body });
      } else {
        await api(`/api/manage/agents/${encodeURIComponent(target.name)}`, { method: "PUT", body });
      }
      await loadAgents();
    } catch (error) {
      alert(error.message || error);
    }
  });

  if (!isNew) {
    document.getElementById("delete-agent-btn").addEventListener("click", async () => {
      if (!confirm(`确认删除 agent ${target.name} 吗？`)) return;
      try {
        await api(`/api/manage/agents/${encodeURIComponent(target.name)}`, { method: "DELETE" });
        await loadAgents();
      } catch (error) {
        alert(error.message || error);
      }
    });
  }
}

function renderMcpPanel() {
  const items = state.mcpData?.items || [];
  const selectedId = state.selectedMcpId || items[0]?.id || null;
  state.selectedMcpId = selectedId;
  renderList(
    "mcp-server-list",
    items,
    selectedId,
    (id) => {
      state.selectedMcpId = id;
      renderMcpPanel();
    },
    (item, active) => `
      <div class="list-item ${active ? "active" : ""}" data-key="${escapeHtml(item.id)}">
        <h4>${escapeHtml(item.name || item.url || item.id)}</h4>
        <p>${escapeHtml(item.kind === "local" ? "本地接口" : (item.url || "在线接口"))}</p>
        <div class="meta-row">
          <span class="badge ${item.enabled ? "success" : "danger"}">${item.enabled ? "启用" : "禁用"}</span>
          <span class="badge">工具 ${item.tool_count || 0}</span>
          <span class="badge">${item.kind === "local" ? "Local" : "Online"}</span>
        </div>
      </div>
    `
  );
  renderMcpDetail(selectedId);
}

function renderMcpDetail(id) {
  const el = document.getElementById("mcp-detail");
  const item = (state.mcpData?.items || []).find((entry) => entry.id === id);
  if (!item) {
    el.innerHTML = '<div class="empty-state">请选择一个 MCP 接口</div>';
    return;
  }

  el.innerHTML = `
    <div class="card">
      <h3>${escapeHtml(item.name || item.url || item.id)}</h3>
      <p>${escapeHtml(item.description || (item.kind === "local" ? "本地 MCP 接口" : item.url || ""))}</p>
      <div class="meta-row">
        <span class="badge ${item.enabled ? "success" : "danger"}">${item.enabled ? "启用" : "禁用"}</span>
        <span class="badge">工具 ${item.tool_count || 0}</span>
        ${item.version ? `<span class="badge">${escapeHtml(item.version)}</span>` : ""}
      </div>
      ${item.url ? `<pre class="code-block">${escapeHtml(item.url)}</pre>` : ""}
      ${item.last_refresh_at ? `<p>最近刷新：${escapeHtml(item.last_refresh_at)}</p>` : ""}
      ${item.last_error ? `<pre class="code-block">${escapeHtml(item.last_error)}</pre>` : ""}
      ${item.kind === "online" ? `
        <div class="toolbar">
          <button id="toggle-mcp-server-btn">${item.enabled ? "禁用" : "启用"}</button>
        </div>
      ` : ""}
    </div>
    <div class="card">
      <h3>接口下工具</h3>
      ${item.tools?.length ? item.tools.map((tool) => `
        <div class="list-item">
          <h4>${escapeHtml(tool.name)}</h4>
          <p>${escapeHtml(tool.description || "")}</p>
        </div>
      `).join("") : '<div class="empty-state">该接口暂无工具</div>'}
    </div>
  `;

  if (item.kind === "online") {
    document.getElementById("toggle-mcp-server-btn").addEventListener("click", async () => {
      try {
        await api("/api/manage/mcps/online/toggle", {
          method: "PUT",
          body: { url: item.url, enabled: !item.enabled },
        });
        await loadMcps();
      } catch (error) {
        alert(error.message || error);
      }
    });
  }
}

function renderSkills() {
  renderList(
    "skills-list",
    state.skills,
    state.selectedSkill?.name,
    async (name) => {
      state.selectedSkill = await api(`/api/manage/skills/${encodeURIComponent(name)}`);
      renderSkills();
      renderSkillDetail();
    },
    (item, active) => `
      <div class="list-item ${active ? "active" : ""}" data-key="${escapeHtml(item.name)}">
        <h4>${escapeHtml(item.name)}</h4>
        <p>${escapeHtml(item.summary || "")}</p>
        <div class="meta-row">
          <span class="badge ${item.enabled ? "success" : "danger"}">${item.enabled ? "启用" : "禁用"}</span>
        </div>
      </div>
    `
  );
  renderSkillDetail();
}

function renderSkillDetail() {
  const el = document.getElementById("skills-detail");
  if (!state.selectedSkill) {
    el.innerHTML = '<div class="empty-state">请选择一个 skill</div>';
    return;
  }
  el.innerHTML = `
    <div class="card">
      <h3>${escapeHtml(state.selectedSkill.name)}</h3>
      <p>${escapeHtml(state.selectedSkill.summary || "")}</p>
      <div class="toolbar">
        <button id="toggle-skill-btn">${state.selectedSkill.enabled ? "禁用" : "启用"}</button>
      </div>
    </div>
    <div class="card">
      <h3>路径</h3>
      <pre class="code-block">${escapeHtml(state.selectedSkill.path || "")}</pre>
    </div>
    <div class="card">
      <h3>SKILL.md</h3>
      <pre class="code-block">${escapeHtml(state.selectedSkill.content || "")}</pre>
    </div>
  `;

  document.getElementById("toggle-skill-btn").addEventListener("click", async () => {
    try {
      await api(`/api/manage/skills/${encodeURIComponent(state.selectedSkill.name)}`, {
        method: "PUT",
        body: { enabled: !state.selectedSkill.enabled },
      });
      await loadSkills(state.selectedSkill.name);
    } catch (error) {
      alert(error.message || error);
    }
  });
}

function renderSouls() {
  renderList(
    "soul-list",
    state.souls,
    state.selectedSoul?.name,
    (name) => {
      state.selectedSoul = state.souls.find((item) => item.name === name) || null;
      renderSouls();
      renderSoulDetail();
    },
    (item, active) => `
      <div class="list-item ${active ? "active" : ""}" data-key="${escapeHtml(item.name)}">
        <h4>${escapeHtml(item.name)}</h4>
        <p>${escapeHtml(item.preview || "")}</p>
      </div>
    `
  );
  renderSoulDetail();
}

function renderSoulDetail(isNew = false) {
  const target = isNew ? { name: "", content: "" } : state.selectedSoul;
  const el = document.getElementById("soul-detail");
  if (!target) {
    el.innerHTML = '<div class="empty-state">请选择一个 soul</div>';
    return;
  }

  const contentValue = typeof target.content === "string" ? target.content : JSON.stringify(target.content, null, 2);
  el.innerHTML = `
    <form id="soul-form">
      <div class="form-grid">
        <label class="form-field full">
          <span>名称</span>
          <input name="name" value="${escapeHtml(target.name || "")}" ${isNew ? "" : "disabled"} />
        </label>
        <label class="form-field full">
          <span>内容</span>
          <textarea name="content" rows="18">${escapeHtml(contentValue || "")}</textarea>
        </label>
      </div>
      <div class="toolbar">
        <button type="submit">${isNew ? "创建" : "保存"}</button>
        ${isNew ? "" : '<button type="button" class="danger" id="delete-soul-btn">删除</button>'}
      </div>
    </form>
  `;

  document.getElementById("soul-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const payloadName = form.elements.name.value.trim();
    const raw = form.elements.content.value;
    let content = raw;
    try {
      content = JSON.parse(raw);
    } catch (_) {}

    try {
      if (isNew) {
        await api("/api/manage/souls", { method: "POST", body: { name: payloadName, content } });
      } else {
        await api(`/api/manage/souls/${encodeURIComponent(target.name)}`, { method: "PUT", body: { content } });
      }
      await loadSouls(isNew ? payloadName : target.name);
    } catch (error) {
      alert(error.message || error);
    }
  });

  if (!isNew) {
    document.getElementById("delete-soul-btn").addEventListener("click", async () => {
      if (!confirm(`确认删除 soul ${target.name} 吗？`)) return;
      try {
        await api(`/api/manage/souls/${encodeURIComponent(target.name)}`, { method: "DELETE" });
        await loadSouls();
      } catch (error) {
        alert(error.message || error);
      }
    });
  }
}

async function loadConversations() {
  const data = await api("/api/conversations");
  state.conversations = data.items || [];
  state.scheduler = data.scheduler || [];
  if (!state.selectedConversation || !state.conversations.some((item) => item.id === state.selectedConversation.id)) {
    state.selectedConversation = state.conversations[0] || null;
  } else {
    state.selectedConversation = state.conversations.find((item) => item.id === state.selectedConversation.id) || null;
  }
  renderConversationList();
  renderConversationMeta();
  renderTaskBoard();
}

async function loadAgents() {
  const data = await api("/api/manage/agents");
  state.agents = data.items || [];
  if (!state.selectedAgent || !state.agents.some((item) => item.name === state.selectedAgent.name)) {
    state.selectedAgent = state.agents[0] || null;
  } else {
    state.selectedAgent = state.agents.find((item) => item.name === state.selectedAgent.name) || null;
  }
  renderAgentOptions();
  renderAgentList();
  renderAgentDetail();
}

async function loadMcps() {
  state.mcpData = await api("/api/manage/mcps");
  const items = state.mcpData?.items || [];
  if (!items.some((item) => item.id === state.selectedMcpId)) {
    state.selectedMcpId = items[0]?.id || null;
  }
  renderMcpPanel();
  if (document.getElementById("agent-detail")?.querySelector("#agent-form")) {
    renderAgentDetail();
  }
}

async function loadSkills(selectedName = null) {
  const data = await api("/api/manage/skills");
  state.skills = data.items || [];
  if (selectedName) {
    state.selectedSkill = await api(`/api/manage/skills/${encodeURIComponent(selectedName)}`);
  } else if (state.skills.length) {
    state.selectedSkill = await api(`/api/manage/skills/${encodeURIComponent(state.skills[0].name)}`);
  } else {
    state.selectedSkill = null;
  }
  renderSkills();
}

async function loadSouls(selectedName = null) {
  const data = await api("/api/manage/souls");
  state.souls = data.items || [];
  if (selectedName) {
    state.selectedSoul = state.souls.find((item) => item.name === selectedName) || null;
  }
  if (!state.selectedSoul || !state.souls.some((item) => item.name === state.selectedSoul.name)) {
    state.selectedSoul = state.souls[0] || null;
  }
  renderSouls();
}

async function boot() {
  document.querySelectorAll(".nav-btn").forEach((button) => {
    button.addEventListener("click", () => setActivePanel(button.dataset.panel));
  });

  sendBtn.addEventListener("click", sendMessage);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  input.addEventListener("input", autoResize);

  document.getElementById("new-single-chat-btn").addEventListener("click", () => createSingleConversation().catch((error) => alert(error.message || error)));
  document.getElementById("new-group-chat-btn").addEventListener("click", () => createGroupConversation().catch((error) => alert(error.message || error)));
  document.getElementById("new-agent-btn").addEventListener("click", () => renderAgentDetail(true));
  document.getElementById("refresh-agent-btn").addEventListener("click", loadAgents);
  document.getElementById("refresh-mcp-btn").addEventListener("click", async () => {
    await api("/api/manage/mcps/online/refresh", { method: "POST" });
    await loadMcps();
  });
  document.getElementById("add-mcp-btn").addEventListener("click", async () => {
    const url = document.getElementById("new-mcp-url").value.trim();
    if (!url) return;
    try {
      await api("/api/manage/mcps/online", { method: "POST", body: { url } });
      document.getElementById("new-mcp-url").value = "";
      await loadMcps();
    } catch (error) {
      alert(error.message || error);
    }
  });
  document.getElementById("rescan-skills-btn").addEventListener("click", async () => {
    await api("/api/manage/skills/rescan", { method: "POST" });
    await loadSkills();
  });
  document.getElementById("new-soul-btn").addEventListener("click", () => renderSoulDetail(true));
  document.getElementById("refresh-soul-btn").addEventListener("click", loadSouls);

  await Promise.all([loadMcps(), loadSkills(), loadSouls(), loadAgents(), loadConversations()]);
}

boot().catch((error) => {
  console.error(error);
  alert(error.message || error);
});
