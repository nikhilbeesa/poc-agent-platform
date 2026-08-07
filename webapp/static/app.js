// ============================================================
// State
// ============================================================
let projectId = null;
let questions = [];
let currentAgentIndex = 0;
let agentMeta = [];

const NODE_COUNT = 5;
const NODE_X_START = 70;
const NODE_X_GAP = 190;
const NODE_Y = 70;
const NODE_R = 26;

// ============================================================
// Helpers
// ============================================================
function $(sel) { return document.querySelector(sel); }
function el(tag, attrs = {}, children = []) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'text') e.textContent = v;
    else if (k === 'html') e.innerHTML = v;
    else e.setAttribute(k, v);
  }
  for (const c of children) e.appendChild(c);
  return e;
}
function unlock(panelId) { $(panelId).classList.remove('is-locked'); }

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'request failed');
  return data;
}

// ============================================================
// Title block
// ============================================================
function setTitleBlock({ projectId, domain }) {
  $('#tb-project').textContent = projectId ? projectId.slice(0, 8) : '—';
  $('#tb-domain').textContent = domain || '—';
  $('#tb-date').textContent = new Date().toISOString().slice(0, 10);
}

async function refreshDomainCount() {
  try {
    const data = await api('/api/knowledge/domains');
    $('#tb-domains').textContent = `${data.domains.length} domains`;
  } catch (e) { /* non-critical */ }
}

async function checkMode() {
  const el = $('#tb-mode');
  try {
    const data = await api('/api/mode');
    if (data.mode === 'live') {
      el.textContent = `LIVE · ${data.provider.toUpperCase()}`;
    } else {
      el.textContent = 'MOCK · offline';
    }
  } catch (e) {
    el.textContent = 'unknown';
  }
}
checkMode();

$('#btn-new-project').addEventListener('click', () => {
  location.reload();
});

// ============================================================
// History overlay
// ============================================================
let historyProjects = [];
let historyDetailArtefacts = [];
let historyDetailActiveIndex = 0;

$('#btn-history').addEventListener('click', openHistory);
$('#btn-history-close').addEventListener('click', closeHistory);
$('#btn-history-back').addEventListener('click', showHistoryList);

async function openHistory() {
  $('#history-overlay').hidden = false;
  showHistoryList();
  try {
    const data = await api('/api/history');
    historyProjects = data.projects;
    renderHistoryList();
  } catch (e) {
    $('#history-list').innerHTML = `<div class="lock-msg">Could not load history: ${escapeHtml(e.message)}</div>`;
  }
}

function closeHistory() {
  $('#history-overlay').hidden = true;
}

function showHistoryList() {
  $('#history-list-view').hidden = false;
  $('#history-detail-view').hidden = true;
}

function renderHistoryList() {
  const list = $('#history-list');
  const emptyMsg = $('#history-empty-msg');
  list.innerHTML = '';

  if (!historyProjects.length) {
    emptyMsg.hidden = false;
    return;
  }
  emptyMsg.hidden = true;

  historyProjects.forEach(p => {
    const date = p.created_at ? new Date(p.created_at).toLocaleString() : 'unknown date';
    const badge = el('span', {
      class: `history-badge ${p.qa_readiness || ''}`,
      text: p.qa_readiness || 'unknown',
    });
    const row = el('div', { class: 'history-row' }, [
      el('div', { class: 'history-row-main' }, [
        el('div', { class: 'history-row-idea', text: p.business_idea }),
        el('div', { class: 'history-row-meta', text: `${p.domain || 'unclassified'} · ${p.artefact_count} artefact(s) · ${date}` }),
      ]),
      badge,
    ]);
    row.addEventListener('click', () => openHistoryDetail(p.id));
    list.appendChild(row);
  });
}

async function openHistoryDetail(projectId) {
  $('#history-list-view').hidden = true;
  $('#history-detail-view').hidden = false;
  $('#history-detail-meta').textContent = 'Loading…';
  $('#history-tabs').innerHTML = '';
  $('#history-doc-viewer').innerHTML = '';

  try {
    const record = await api(`/api/history/${projectId}`);
    const date = record.created_at ? new Date(record.created_at).toLocaleString() : 'unknown date';
    $('#history-detail-meta').innerHTML =
      `<strong>${escapeHtml(record.business_idea)}</strong><br>` +
      `Domain: ${escapeHtml(record.domain || 'unclassified')} · Created: ${escapeHtml(date)} · QA: ${escapeHtml(record.qa_readiness || 'unknown')}`;

    historyDetailArtefacts = record.artefacts || [];
    historyDetailActiveIndex = 0;

    const tabs = $('#history-tabs');
    tabs.innerHTML = '';
    historyDetailArtefacts.forEach((a, i) => {
      const tab = el('button', { class: 'tab-btn' + (i === 0 ? ' active' : ''), text: a.title.split('—')[0].trim() || a.type });
      tab.addEventListener('click', () => {
        historyDetailActiveIndex = i;
        document.querySelectorAll('#history-tabs .tab-btn').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        renderHistoryDoc(a.content_markdown);
      });
      tabs.appendChild(tab);
    });

    if (historyDetailArtefacts.length) renderHistoryDoc(historyDetailArtefacts[0].content_markdown);
  } catch (e) {
    $('#history-detail-meta').textContent = 'Could not load this project: ' + e.message;
  }
}

function renderHistoryDoc(markdown) {
  const viewer = $('#history-doc-viewer');
  viewer.innerHTML = window.marked ? marked.parse(markdown) : markdown;
}

$('#btn-history-download-current').addEventListener('click', () => {
  const a = historyDetailArtefacts[historyDetailActiveIndex];
  if (!a) return;
  downloadMarkdown(`${a.type}.md`, a.content_markdown);
});

$('#btn-history-download-all').addEventListener('click', () => {
  historyDetailArtefacts.forEach((a, i) => {
    setTimeout(() => downloadMarkdown(`${a.type}.md`, a.content_markdown), i * 350);
  });
});

// ============================================================
// SHEET 01 — Intake
// ============================================================
document.querySelectorAll('.chip').forEach(chip => {
  chip.addEventListener('click', () => {
    $('#idea-input').value = chip.dataset.idea;
  });
});

$('#btn-submit-idea').addEventListener('click', async () => {
  const idea = $('#idea-input').value.trim();
  if (!idea) return;

  const btn = $('#btn-submit-idea');
  btn.disabled = true;
  btn.textContent = 'Running discovery…';

  try {
    const data = await api('/api/project', {
      method: 'POST',
      body: JSON.stringify({ idea }),
    });

    projectId = data.project_id;
    questions = data.questions;
    setTitleBlock({ projectId, domain: `${data.domain} (${Math.round(data.confidence * 100)}%)` });
    await refreshDomainCount();

    if (data.learned_new_domain) {
      $('#learned-banner').hidden = false;
    }

    renderQuestions();
    unlock('#panel-discovery');
    $('#discovery-status').textContent = `0 / ${questions.length} answered`;
  } catch (e) {
    alert('Something went wrong: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Run discovery →';
  }
});

// ============================================================
// SHEET 02 — Discovery
// ============================================================
function renderQuestions() {
  const list = $('#questions-list');
  list.innerHTML = '';
  questions.forEach(q => {
    const row = el('div', { class: 'question-row', id: `q-row-${q.id}` }, [
      el('div', { class: 'question-cat', text: q.category.toUpperCase() }),
      el('div', { class: 'question-text', text: q.text }),
      el('div', { class: 'question-answer-row' }, [
        el('input', { type: 'text', id: `q-input-${q.id}`, placeholder: 'Type an answer…' }),
        el('button', { class: 'btn', text: 'Answer' }),
      ]),
      el('div', { class: 'answered-tag', id: `q-tag-${q.id}` }, []),
    ]);
    const answerBtn = row.querySelector('.question-answer-row .btn');
    const input = row.querySelector('input');
    const submit = () => submitAnswer(q.id, input.value.trim());
    answerBtn.addEventListener('click', submit);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
    list.appendChild(row);
  });
}

async function submitAnswer(questionId, answerText) {
  if (!answerText) return;
  try {
    const data = await api(`/api/project/${projectId}/answer`, {
      method: 'POST',
      body: JSON.stringify({ question_id: questionId, answer: answerText }),
    });

    const row = $(`#q-row-${questionId}`);
    row.classList.add('answered');
    $(`#q-tag-${questionId}`).textContent = `✓ ${answerText}`;

    const answeredCount = questions.filter(q => $(`#q-row-${q.id}`).classList.contains('answered')).length;
    $('#discovery-status').textContent = `${answeredCount} / ${questions.length} answered`;

    if (data.discovery_complete) {
      $('#discovery-status').textContent = 'complete';
      $('#btn-run-agents').hidden = false;
    }
  } catch (e) {
    alert('Could not save answer: ' + e.message);
  }
}

$('#btn-run-agents').addEventListener('click', async () => {
  unlock('#panel-agents');
  await loadAgentMeta();
  drawSchematic();
  runAgentPipeline();
});

// ============================================================
// SHEET 03 — Agent assembly (schematic)
// ============================================================
async function loadAgentMeta() {
  const data = await api(`/api/project/${projectId}/agents`);
  agentMeta = data.agents;
}

function nodeX(i) { return NODE_X_START + i * NODE_X_GAP; }

function drawSchematic() {
  const svg = $('#schematic');
  svg.innerHTML = '';
  const ns = 'http://www.w3.org/2000/svg';

  // Trace lines first (so they sit behind nodes)
  for (let i = 0; i < agentMeta.length - 1; i++) {
    const line = document.createElementNS(ns, 'line');
    line.setAttribute('x1', nodeX(i) + NODE_R);
    line.setAttribute('y1', NODE_Y);
    line.setAttribute('x2', nodeX(i + 1) - NODE_R);
    line.setAttribute('y2', NODE_Y);
    line.setAttribute('class', 'trace-line');
    line.setAttribute('id', `trace-${i}`);
    svg.appendChild(line);
  }

  agentMeta.forEach((agent, i) => {
    const g = document.createElementNS(ns, 'g');

    const circle = document.createElementNS(ns, 'circle');
    circle.setAttribute('cx', nodeX(i));
    circle.setAttribute('cy', NODE_Y);
    circle.setAttribute('r', NODE_R);
    circle.setAttribute('class', 'node-circle');
    circle.setAttribute('id', `node-${i}`);
    g.appendChild(circle);

    const check = document.createElementNS(ns, 'text');
    check.setAttribute('x', nodeX(i));
    check.setAttribute('y', NODE_Y + 6);
    check.setAttribute('text-anchor', 'middle');
    check.setAttribute('class', 'node-check');
    check.setAttribute('id', `check-${i}`);
    check.textContent = '✓';
    g.appendChild(check);

    const idx = document.createElementNS(ns, 'text');
    idx.setAttribute('x', nodeX(i));
    idx.setAttribute('y', NODE_Y + 5);
    idx.setAttribute('text-anchor', 'middle');
    idx.setAttribute('class', 'node-idx');
    idx.setAttribute('id', `idx-${i}`);
    idx.setAttribute('fill', 'var(--text-faint)');
    idx.setAttribute('font-family', 'var(--mono)');
    idx.setAttribute('font-size', '13');
    idx.textContent = `0${i + 1}`;
    g.appendChild(idx);

    const label1 = document.createElementNS(ns, 'text');
    label1.setAttribute('x', nodeX(i));
    label1.setAttribute('y', NODE_Y + NODE_R + 22);
    label1.setAttribute('text-anchor', 'middle');
    label1.setAttribute('class', 'node-label');
    label1.setAttribute('id', `label-${i}`);
    label1.textContent = agent.label;
    g.appendChild(label1);

    const label2 = document.createElementNS(ns, 'text');
    label2.setAttribute('x', nodeX(i));
    label2.setAttribute('y', NODE_Y + NODE_R + 36);
    label2.setAttribute('text-anchor', 'middle');
    label2.setAttribute('class', 'node-label');
    label2.setAttribute('font-size', '9');
    label2.setAttribute('opacity', '0.7');
    label2.textContent = agent.note;
    g.appendChild(label2);

    svg.appendChild(g);
  });
}

function setNodeState(i, state) {
  const circle = $(`#node-${i}`);
  const label = $(`#label-${i}`);
  const check = $(`#check-${i}`);
  const idx = $(`#idx-${i}`);
  circle.classList.remove('active', 'done');
  label.classList.remove('active', 'done');
  if (state === 'active') {
    circle.classList.add('active');
    label.classList.add('active');
  } else if (state === 'done') {
    circle.classList.add('done');
    label.classList.add('done');
    check.classList.add('show');
    idx.style.display = 'none';
    const trace = $(`#trace-${i}`);
    if (trace) trace.classList.add('charged');
  }
}

function logLine(text, done = false) {
  const log = $('#agent-log');
  const line = el('div', { text, class: done ? 'log-done' : '' });
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
}

async function runAgentPipeline() {
  $('#agents-status').textContent = 'running…';

  for (let i = 0; i < agentMeta.length; i++) {
    currentAgentIndex = i;
    setNodeState(i, 'active');
    logLine(`⏳ ${agentMeta[i].label} reading project context…`);

    try {
      const data = await api(`/api/project/${projectId}/agent/${i}`, { method: 'POST' });
      setNodeState(i, 'done');
      logLine(`✓ ${agentMeta[i].label} — ${data.summary}`, true);

      if (agentMeta[i].role === 'qa_reviewer') {
        showQaVerdict(data);
      }
    } catch (e) {
      logLine(`✗ ${agentMeta[i].label} failed: ${e.message}`);
      $('#agents-status').textContent = 'error';
      return;
    }
  }

  $('#agents-status').textContent = 'complete — 5/5';
  $('#btn-export').hidden = false;
}

function showQaVerdict(data) {
  const readiness = (data.output && data.output.overall_readiness) || 'unknown';
  const box = $('#qa-verdict');
  box.hidden = false;
  box.className = `qa-verdict ${readiness}`;

  const notes = data.consistency_notes || [];
  const notesHtml = notes.length
    ? '<ul>' + notes.map(n => `<li>${escapeHtml(n)}</li>`).join('') + '</ul>'
    : '';
  box.innerHTML = `VERDICT: ${readiness.toUpperCase()}` + notesHtml;
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// ============================================================
// SHEET 04 — Artefacts
// ============================================================
let currentArtefacts = [];
let activeArtefactIndex = 0;

$('#btn-export').addEventListener('click', async () => {
  unlock('#panel-artefacts');
  const btn = $('#btn-export');
  btn.disabled = true;
  btn.textContent = 'Exporting…';

  try {
    const data = await api(`/api/project/${projectId}/export`, { method: 'POST' });
    renderArtefacts(data.artefacts);
  } catch (e) {
    alert('Export failed: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Export artefacts →';
  }
});

function renderArtefacts(artefacts) {
  currentArtefacts = artefacts;
  activeArtefactIndex = 0;

  const tabs = $('#artefact-tabs');
  tabs.innerHTML = '';
  tabs.hidden = false;
  $('#artefact-controls').hidden = false;

  artefacts.forEach((a, i) => {
    const tab = el('button', { class: 'tab-btn' + (i === 0 ? ' active' : ''), text: a.title.split('—')[0].trim() || a.type });
    tab.addEventListener('click', () => {
      activeArtefactIndex = i;
      document.querySelectorAll('.tab-btn').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      renderDoc(a.content_markdown);
    });
    tabs.appendChild(tab);
  });

  if (artefacts.length) renderDoc(artefacts[0].content_markdown);
}

function renderDoc(markdown) {
  const viewer = $('#doc-viewer');
  if (window.marked) {
    viewer.innerHTML = marked.parse(markdown);
  } else {
    viewer.textContent = markdown;
  }
}

function downloadMarkdown(filename, content) {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

$('#btn-download-current').addEventListener('click', () => {
  const a = currentArtefacts[activeArtefactIndex];
  if (!a) return;
  downloadMarkdown(`${a.type}.md`, a.content_markdown);
});

$('#btn-download-all').addEventListener('click', () => {
  // Small stagger between downloads — some browsers block several
  // simultaneous downloads triggered without individual user gestures.
  currentArtefacts.forEach((a, i) => {
    setTimeout(() => downloadMarkdown(`${a.type}.md`, a.content_markdown), i * 350);
  });
});
