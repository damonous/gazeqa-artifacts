const apiBase = window.localStorage.getItem('GAZEQA_API_BASE') || window.location.origin;
const runsList = document.getElementById('runs-list');
const runSummary = document.getElementById('run-summary');
const artifactList = document.getElementById('artifact-list');
const logsOutput = document.getElementById('logs-output');
const refreshRunsBtn = document.getElementById('refresh-runs');
const refreshArtifactsBtn = document.getElementById('refresh-artifacts');

let activeRunId = null;
let eventSource = null;

function apiUrl(path) {
  return `${apiBase}${path}`;
}

async function fetchJson(path) {
  const response = await fetch(apiUrl(path));
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function renderRuns(runs) {
  runsList.innerHTML = '';
  runs.forEach((runId) => {
    const item = document.createElement('li');
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = runId;
    button.id = `run-${runId}`;
    if (runId === activeRunId) {
      button.classList.add('active');
      runsList.setAttribute('aria-activedescendant', button.id);
    }
    button.addEventListener('click', () => selectRun(runId));
    item.appendChild(button);
    runsList.appendChild(item);
  });
}

function renderSummary(manifest) {
  runSummary.innerHTML = '';
  const fields = {
    'Run ID': manifest.id,
    Status: manifest.status,
    'Target URL': manifest.target_url,
    'Storage Profile': manifest.storage_profile,
    Tags: manifest.tags && manifest.tags.length ? manifest.tags.join(', ') : '—',
    'Created At': manifest.created_at,
  };
  Object.entries(fields).forEach(([label, value]) => {
    const dt = document.createElement('dt');
    dt.textContent = label;
    const dd = document.createElement('dd');
    dd.textContent = value ?? '—';
    runSummary.append(dt, dd);
  });
}

function renderArtifacts(manifest) {
  artifactList.innerHTML = '';
  const prefix = `artifacts/runs/${manifest.run_id || activeRunId}`;
  const entries = manifest.artifacts || {};
  const flatten = (obj, path = []) => {
    Object.entries(obj).forEach(([key, value]) => {
      if (typeof value === 'string') {
        items.push({ label: [...path, key].join(' › '), path: `${prefix}/${value}` });
      } else if (typeof value === 'object' && value) {
        flatten(value, [...path, key]);
      }
    });
  };
  const items = [];
  flatten(entries);
  items.sort((a, b) => a.label.localeCompare(b.label));
  items.forEach(({ label, path }) => {
    const li = document.createElement('li');
    const anchor = document.createElement('a');
    anchor.href = path;
    anchor.target = '_blank';
    anchor.rel = 'noopener';
    anchor.textContent = label;
    li.appendChild(anchor);
    artifactList.appendChild(li);
  });
}

function appendLog(event) {
  const div = document.createElement('div');
  div.className = 'log-entry';
  div.textContent = `${event.timestamp} • ${event.status}`;
  logsOutput.appendChild(div);
  logsOutput.scrollTop = logsOutput.scrollHeight;
}

function clearLogs() {
  logsOutput.innerHTML = '';
}

function subscribeToEvents(runId) {
  if (eventSource) {
    eventSource.close();
  }
  const streamUrl = apiUrl(`/runs/${encodeURIComponent(runId)}/events/stream`);
  eventSource = new EventSource(streamUrl);
  eventSource.onmessage = (message) => {
    try {
      const payload = JSON.parse(message.data);
      appendLog(payload);
    } catch (error) {
      console.warn('Failed to parse event payload', error);
    }
  };
  eventSource.onerror = () => {
    eventSource.close();
    // attempt reconnection after a brief pause
    setTimeout(() => subscribeToEvents(runId), 2000);
  };
}

async function selectRun(runId) {
  activeRunId = runId;
  refreshArtifactsBtn.disabled = false;
  Array.from(runsList.querySelectorAll('button')).forEach((button) => {
    button.classList.toggle('active', button.textContent === runId);
  });
  runsList.setAttribute('aria-activedescendant', `run-${runId}`);
  try {
    const manifest = await fetchJson(`/runs/${encodeURIComponent(runId)}`);
    renderSummary(manifest);
    const artifacts = await fetchJson(`/runs/${encodeURIComponent(runId)}/artifacts`);
    renderArtifacts({ run_id: runId, artifacts });
    clearLogs();
    const events = await fetchJson(`/runs/${encodeURIComponent(runId)}/events`);
    (events.events || []).forEach(appendLog);
    subscribeToEvents(runId);
  } catch (error) {
    console.error('Failed to load run', error);
  }
}

async function refreshRuns() {
  try {
    const payload = await fetchJson('/runs?offset=0&limit=50');
    renderRuns(payload.runs);
    if (!activeRunId && payload.runs.length) {
      await selectRun(payload.runs[payload.runs.length - 1]);
    }
  } catch (error) {
    console.error('Failed to refresh runs', error);
  }
}

refreshRunsBtn.addEventListener('click', refreshRuns);
refreshArtifactsBtn.addEventListener('click', () => {
  if (activeRunId) {
    selectRun(activeRunId);
  }
});

refreshRuns();
