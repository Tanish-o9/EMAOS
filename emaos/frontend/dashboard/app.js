/* ══════════════════════════════════════════════════════════════════
   EMAOS Mission Control — Dashboard JavaScript
   ══════════════════════════════════════════════════════════════════ */

'use strict';

// ─── State ────────────────────────────────────────────────────────
let API_BASE = 'http://localhost:8000';
let TOKEN = null;
let activeSection = 'dashboard';
let throughputChart = null;
let agentChart = null;
let pollInterval = null;
let logLines = 0;
const MAX_LOG_LINES = 200;

const AGENT_META = {
  ceo:        { emoji: '🧠', color: '#8b5cf6', role: 'Task decomposition & routing' },
  developer:  { emoji: '💻', color: '#3b82f6', role: 'Code generation & GitHub' },
  tester:     { emoji: '🧪', color: '#06b6d4', role: 'Test execution & QA' },
  finance:    { emoji: '💰', color: '#10b981', role: 'Financial analysis' },
  marketing:  { emoji: '📣', color: '#f97316', role: 'SEO & content strategy' },
  hr:         { emoji: '👥', color: '#f0abfc', role: 'Talent & HR content' },
  monitoring: { emoji: '📊', color: '#f59e0b', role: 'System health & metrics' },
  research:   { emoji: '🔬', color: '#67e8f9', role: 'Literature & synthesis' },
};

// ─── Auth ─────────────────────────────────────────────────────────
async function handleLogin() {
  const btn = document.getElementById('loginBtn');
  const username = document.getElementById('loginUsername').value.trim();
  const password = document.getElementById('loginPassword').value.trim();
  API_BASE = document.getElementById('apiUrl').value.trim();

  if (!username || !password) {
    alert('Please enter username and password');
    return;
  }

  btn.innerText = 'Signing In...';
  btn.disabled = true;

  try {
    const response = await fetch(`${API_BASE}/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });

    if (response.ok) {
      const data = await response.json();
      TOKEN = data.access_token;
      sessionStorage.setItem('emaos_token', TOKEN);
      sessionStorage.setItem('emaos_api', API_BASE);
      
      document.getElementById('authOverlay').style.display = 'none';
      document.getElementById('appContainer').style.display = 'grid';
      
      initApp();
    } else {
      const err = await response.json();
      alert(`Login failed: ${err.detail || 'Invalid credentials'}`);
    }
  } catch (err) {
    alert(`Failed to connect to backend: ${err.message}`);
  } finally {
    btn.innerText = 'Sign In to Mission Control';
    btn.disabled = false;
  }
}

function handleLogout() {
  TOKEN = null;
  sessionStorage.removeItem('emaos_token');
  clearInterval(pollInterval);
  document.getElementById('appContainer').style.display = 'none';
  document.getElementById('authOverlay').style.display = 'flex';
}

function getHeaders() {
  return {
    'Authorization': `Bearer ${TOKEN}`,
    'Content-Type': 'application/json'
  };
}

// ─── Navigation ───────────────────────────────────────────────────
function switchSection(sectionId) {
  // Toggle nav classes
  document.querySelectorAll('.menu-item').forEach(el => el.classList.remove('active'));
  document.getElementById(`menu-${sectionId}`).classList.add('active');

  // Toggle sections
  document.querySelectorAll('.content-section').forEach(el => el.style.display = 'none');
  document.getElementById(`section-${sectionId}`).style.display = 'block';

  activeSection = sectionId;
  
  if (sectionId === 'agents') {
    loadAgentsRegistry();
  } else if (sectionId === 'reports') {
    loadReportsList();
  } else if (sectionId === 'metrics') {
    loadMetricsCharts();
  } else if (sectionId === 'tasks') {
    loadTasksQueue();
  }
}

// ─── Initialization ───────────────────────────────────────────────
function initApp() {
  // Load token from storage
  TOKEN = sessionStorage.getItem('emaos_token');
  API_BASE = sessionStorage.getItem('emaos_api') || 'http://localhost:8000';

  if (!TOKEN) {
    handleLogout();
    return;
  }

  document.getElementById('authOverlay').style.display = 'none';
  document.getElementById('appContainer').style.display = 'grid';
  
  // Healthcheck status checking
  checkSystemHealth();
  setInterval(checkSystemHealth, 30000);

  // Load dashboard widgets
  switchSection('dashboard');
  
  // Start polling tasks status
  startPollingTasks();
}

async function checkSystemHealth() {
  try {
    const res = await fetch(`${API_BASE}/health`);
    const data = await res.json();
    const ind = document.getElementById('healthIndicator');
    const txt = document.getElementById('healthStatusText');
    
    if (res.ok && data.status === 'healthy') {
      ind.className = 'status-indicator status-green';
      txt.innerText = 'SYSTEM ACTIVE (CONNECTED)';
    } else {
      ind.className = 'status-indicator status-red';
      txt.innerText = 'SYSTEM DEGRADED';
    }
  } catch (err) {
    const ind = document.getElementById('healthIndicator');
    const txt = document.getElementById('healthStatusText');
    ind.className = 'status-indicator status-red';
    txt.innerText = 'BACKEND DISCONNECTED';
  }
}

// ─── Log Stream Console ───────────────────────────────────────────
function logStream(msg, type = 'system') {
  const container = document.getElementById('streamLog');
  const line = document.createElement('div');
  line.className = `log-line`;
  
  if (type === 'error') line.style.color = '#ef4444';
  else if (type === 'success') line.style.color = '#10b981';
  else if (type === 'agent') line.style.color = '#3b82f6';
  else line.style.color = '#94a3b8';

  const timeStr = new Date().toLocaleTimeString();
  line.innerText = `[${timeStr}] ${msg}`;
  
  container.appendChild(line);
  container.scrollTop = container.scrollHeight;

  logLines++;
  if (logLines > MAX_LOG_LINES) {
    container.removeChild(container.firstChild);
    logLines--;
  }
}

// ─── Task Submission ──────────────────────────────────────────────
async function submitQuickTask() {
  const input = document.getElementById('quickTaskInput');
  const req = input.value.trim();
  if (!req) return;

  logStream(`Dispatched user request: "${req.substring(0, 50)}..."`);
  input.value = '';

  await executeTaskSubmission(req);
}

async function submitTask() {
  const desc = document.getElementById('taskDesc').value.trim();
  const project = document.getElementById('projectContext').value.trim();
  if (!desc) {
    alert('Please enter a task description');
    return;
  }

  logStream(`Dispatched pipeline task: "${desc.substring(0, 50)}..."`);
  document.getElementById('taskDesc').value = '';

  await executeTaskSubmission(desc, project);
  switchSection('dashboard');
}

async function executeTaskSubmission(user_request, project_id = 'default') {
  try {
    const res = await fetch(`${API_BASE}/tasks/submit`, {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({ user_request, project_id })
    });

    if (res.ok) {
      const data = await res.json();
      logStream(`CEO Agent assigned Task ID: ${data.task_id} (PENDING)`, 'success');
      // Begin watching the submitted task ID
      watchTaskProgress(data.task_id);
    } else {
      const err = await res.json();
      logStream(`Submission failed: ${err.error.message}`, 'error');
    }
  } catch (err) {
    logStream(`Error submitting task: ${err.message}`, 'error');
  }
}

// ─── Real-time Streaming ──────────────────────────────────────────
let activeTaskId = null;
let watchInterval = null;

function watchTaskProgress(task_id) {
  if (watchInterval) clearInterval(watchInterval);
  activeTaskId = task_id;
  
  logStream(`Pipeline monitoring started for Task ID: ${task_id}...`);
  
  watchInterval = setInterval(async () => {
    try {
      const res = await fetch(`${API_BASE}/tasks/${task_id}`, { headers: getHeaders() });
      if (!res.ok) return;

      const data = await res.json();
      
      // Update stats counters
      document.getElementById('statActiveTasks').innerText = data.status === 'running' ? '1' : '0';

      // Log agent outputs
      data.agent_outputs.forEach((out, idx) => {
        // Simple check to prevent logging duplicate statements
        const logId = `logged_${task_id}_${out.agent_name}_${out.output_type}`;
        if (!sessionStorage.getItem(logId)) {
          logStream(
            `Agent [${out.agent_name.toUpperCase()}] produced '${out.output_type}' (${out.duration_ms}ms)`,
            out.success ? 'agent' : 'error'
          );
          sessionStorage.setItem(logId, 'true');
        }
      });

      if (data.status === 'completed') {
        logStream(`Task execution completed successfully!`, 'success');
        clearInterval(watchInterval);
        
        if (data.final_reports && data.final_reports.length > 0) {
          const summary = data.final_reports[0].summary;
          logStream(`Final executive summary report compiled. View under Reports tab.`, 'success');
        }
        loadTasksQueue();
      } else if (data.status === 'failed') {
        logStream(`Task pipeline failed. Review metrics or error logs.`, 'error');
        clearInterval(watchInterval);
        loadTasksQueue();
      }
    } catch (err) {
      console.error('Error fetching stream status:', err);
    }
  }, 2000);
}

// ─── Queue list ───────────────────────────────────────────────────
async function loadTasksQueue() {
  try {
    const res = await fetch(`${API_BASE}/tasks/`, { headers: getHeaders() });
    if (!res.ok) return;

    const data = await res.json();
    document.getElementById('statTotalTasks').innerText = data.length;

    const tbody = document.getElementById('taskQueueBody');
    tbody.innerHTML = '';
    
    if (data.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No historical pipelines.</td></tr>';
      return;
    }

    data.forEach(t => {
      let badgeClass = 'badge-yellow';
      if (t.status === 'completed') badgeClass = 'badge-green';
      else if (t.status === 'failed') badgeClass = 'badge-red';
      else if (t.status === 'running') badgeClass = 'badge-blue';

      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${t.id.substring(0, 8)}...</td>
        <td>${t.project_id}</td>
        <td>${t.title}</td>
        <td><span class="badge ${badgeClass}">${t.status}</span></td>
        <td><button class="action-btn" style="padding:4px 8px;font-size:12px;" onclick="watchTaskProgress('${t.id}')">Monitor</button></td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error('Failed to list tasks:', err);
  }
}

function startPollingTasks() {
  loadTasksQueue();
  pollInterval = setInterval(loadTasksQueue, 15000);
}

// ─── Agent Registry UI ────────────────────────────────────────────
async function loadAgentsRegistry() {
  const container = document.getElementById('agentsRegistryGrid');
  container.innerHTML = '<div class="text-muted">Loading registry...</div>';

  try {
    const res = await fetch(`${API_BASE}/agents/`, { headers: getHeaders() });
    if (!res.ok) return;

    const data = await res.json();
    container.innerHTML = '';

    Object.keys(data).forEach(key => {
      const info = data[key];
      const meta = AGENT_META[key] || { emoji: '🤖', color: '#3b82f6', role: info.role };
      
      const card = document.createElement('div');
      card.className = 'agent-card';
      card.onclick = () => {
        // Pre-select agent in Memory tab
        document.getElementById('memoryAgentSelect').value = key;
        switchSection('memory');
        loadAgentMemoryLogs();
      };
      
      card.innerHTML = `
        <div class="agent-header">
          <div class="agent-emoji" style="border-bottom: 2px solid ${meta.color}">${meta.emoji}</div>
          <div>
            <div class="agent-title">${info.name}</div>
            <div class="agent-role">${meta.role}</div>
          </div>
        </div>
        <div class="agent-caps">
          ${info.capabilities.map(c => `<span class="agent-cap-tag">${c}</span>`).join('')}
        </div>
      `;
      container.appendChild(card);
    });
  } catch (err) {
    container.innerHTML = '<div class="text-red">Failed to load agent registry.</div>';
  }
}

// ─── Memory Searches ──────────────────────────────────────────────
async function searchSemanticMemory() {
  const query = document.getElementById('semanticSearchQuery').value.trim();
  const agent = document.getElementById('memoryAgentSelect').value;
  const list = document.getElementById('semanticResults');

  if (!query) return;
  list.innerHTML = '<div class="text-muted">Searching FAISS index...</div>';

  try {
    const res = await fetch(`${API_BASE}/agents/${agent}/memory/semantic?query=${encodeURIComponent(query)}`, {
      headers: getHeaders()
    });
    if (!res.ok) return;

    const data = await res.json();
    list.innerHTML = '';
    
    if (data.length === 0) {
      list.innerHTML = '<div class="text-muted">No semantically similar memories found.</div>';
      return;
    }

    data.forEach(r => {
      const item = document.createElement('div');
      item.className = 'search-result-item';
      item.innerHTML = `
        <div style="font-size:11px;color:#3b82f6;">Score: ${(r.score * 100).toFixed(1)}% | Agent: ${r.agent_name.toUpperCase()}</div>
        <div style="margin-top:5px;">${r.content}</div>
      `;
      list.appendChild(item);
    });
  } catch (err) {
    list.innerHTML = '<div class="text-red">Failed to search memory.</div>';
  }
}

async function loadAgentMemoryLogs() {
  const agent = document.getElementById('memoryAgentSelect').value;
  const container = document.getElementById('episodicLogsContainer');
  container.innerHTML = '<div class="text-muted">Loading logs...</div>';

  try {
    const res = await fetch(`${API_BASE}/agents/${agent}/memory/episodic`, { headers: getHeaders() });
    if (!res.ok) return;

    const data = await res.json();
    container.innerHTML = '';
    
    if (data.length === 0) {
      container.innerHTML = '<div class="text-muted">No episodic memory records found.</div>';
      return;
    }

    data.forEach(m => {
      const card = document.createElement('div');
      card.className = 'memory-log-card';
      card.innerHTML = `
        <div style="font-size:11px;color:#94a3b8;">${new Date(m.created_at).toLocaleString()} [${m.event_type.toUpperCase()}]</div>
        <div style="margin-top:3px;font-family:'JetBrains Mono',monospace;font-size:12px;">${m.content}</div>
      `;
      container.appendChild(card);
    });
  } catch (err) {
    container.innerHTML = '<div class="text-red">Failed to load episodic logs.</div>';
  }
}

// ─── Reports ──────────────────────────────────────────────────────
async function loadReportsList() {
  const tbody = document.getElementById('reportsTableBody');
  tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">Loading reports...</td></tr>';

  try {
    const res = await fetch(`${API_BASE}/reports/`, { headers: getHeaders() });
    if (!res.ok) return;

    const data = await res.json();
    tbody.innerHTML = '';
    
    if (data.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No reports generated yet.</td></tr>';
      return;
    }

    data.forEach(r => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${r.id.substring(0, 8)}...</td>
        <td>${r.task_id.substring(0, 8)}...</td>
        <td>${r.title}</td>
        <td>${r.format}</td>
        <td>
          <button class="action-btn" style="padding:4px 8px;font-size:12px;" onclick="viewReport('${r.id}')">View</button>
          <a class="action-btn" style="padding:4px 8px;font-size:12px;text-decoration:none;" href="${API_BASE}/reports/${r.id}/raw?token=${TOKEN}" target="_blank">Raw</a>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    tbody.innerHTML = '<tr><td colspan="5" class="text-center text-red">Failed to load reports.</td></tr>';
  }
}

async function viewReport(report_id) {
  const panel = document.getElementById('reportViewerPanel');
  const titleEl = document.getElementById('reportViewerTitle');
  const contentEl = document.getElementById('reportViewerContent');

  panel.style.display = 'block';
  titleEl.innerText = 'Loading Report...';
  contentEl.innerText = '';

  try {
    const res = await fetch(`${API_BASE}/reports/${report_id}`, { headers: getHeaders() });
    if (!res.ok) return;

    const data = await res.json();
    titleEl.innerText = data.title;
    
    // Simple markdown renderer
    let html = data.content
      .replace(/^# (.*$)/gim, '<h1>$1</h1>')
      .replace(/^## (.*$)/gim, '<h2>$2</h2>')
      .replace(/^### (.*$)/gim, '<h3>$1</h3>')
      .replace(/^\- (.*$)/gim, '<li>$1</li>')
      .replace(/\n$/gim, '<br />');

    contentEl.innerHTML = html;
    
    // Scroll into view
    panel.scrollIntoView({ behavior: 'smooth' });
  } catch (err) {
    titleEl.innerText = 'Error Loading Report';
    contentEl.innerText = err.message;
  }
}

// ─── Metrics Charts ───────────────────────────────────────────────
function loadMetricsCharts() {
  const ctxT = document.getElementById('throughputChart').getContext('2d');
  const ctxA = document.getElementById('agentChart').getContext('2d');

  if (throughputChart) throughputChart.destroy();
  if (agentChart) agentChart.destroy();

  // Create mock charts representing historical distributions
  throughputChart = new Chart(ctxT, {
    type: 'line',
    data: {
      labels: ['10:00', '11:00', '12:00', '13:00', '14:00', '15:00'],
      datasets: [{
        label: 'Tasks Per Hour',
        data: [12, 19, 3, 5, 2, 3],
        borderColor: '#3b82f6',
        backgroundColor: 'rgba(59, 130, 246, 0.1)',
        fill: true,
        tension: 0.4
      }]
    },
    options: { responsive: true, scales: { y: { beginAtZero: true } } }
  });

  agentChart = new Chart(ctxA, {
    type: 'bar',
    data: {
      labels: ['Developer', 'Tester', 'Finance', 'Marketing', 'HR', 'Monitoring', 'Research'],
      datasets: [{
        label: 'Agent Activations',
        data: [15, 12, 5, 8, 3, 10, 22],
        backgroundColor: ['#3b82f6', '#06b6d4', '#10b981', '#f97316', '#f0abfc', '#f59e0b', '#67e8f9']
      }]
    },
    options: { responsive: true, scales: { y: { beginAtZero: true } } }
  });
}

// Load session credentials if exists
window.onload = () => {
  const token = sessionStorage.getItem('emaos_token');
  if (token) {
    initApp();
  }
};
