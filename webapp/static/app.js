// ============================================================
// State
// ============================================================
let projectId = null;
let questions = [];
let agentMeta = [];

// Conversational discovery flow state
let dfAnswers = {};       // question_id -> answer text
let dfIndex = 0;          // index of the question currently on screen
let dfShowingReview = false;
let dfReturnToReview = false; // true when we jumped here via "Edit" from the review screen
const OTHER_LABEL = 'Something else';

const NODE_X_START = 70;
const NODE_X_GAP = 150;
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
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || 'request failed');
  return data;
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function downloadMarkdown(filename, content) {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// Status strings like "READY FOR DESIGN AGENT" have spaces, which can't
// be used directly as CSS classes — slugify for styling, keep the raw
// text for display.
function statusSlug(status) {
  if (!status) return 'unknown';
  const s = status.toUpperCase();
  if (s.includes('NOT READY')) return 'status-not-ready';
  if (s.includes('WARNING')) return 'status-warnings';
  if (s.includes('READY')) return 'status-ready';
  return 'status-unknown';
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
  const elm = $('#tb-mode');
  try {
    const data = await api('/api/mode');
    elm.textContent = data.mode === 'live' ? `LIVE · ${data.provider.toUpperCase()}` : 'MOCK · offline';
  } catch (e) {
    elm.textContent = 'unknown';
  }
}
checkMode();

// ============================================================
// View switching: dashboard <-> pipeline
// ============================================================
$('#btn-go-dashboard').addEventListener('click', goToDashboard);
$('#btn-pipeline-back').addEventListener('click', goToDashboard);
$('#btn-open-new-project').addEventListener('click', () => {
  sessionStorage.setItem('poc_view', 'pipeline');
  location.reload();
});
$('#btn-history-back').addEventListener('click', showDashboardList);

function goToDashboard() {
  if (projectId && $('#artefact-tabs').children.length === 0) {
    if (!confirm('Leave this in-progress project? Unexported projects are not saved.')) return;
  }
  sessionStorage.removeItem('poc_view');
  location.reload();
}

function showPipelineView() {
  $('#dashboard-view').hidden = true;
  $('#dashboard-detail-view').hidden = true;
  $('#pipeline-view').hidden = false;
}

function showDashboardList() {
  $('#pipeline-view').hidden = true;
  $('#dashboard-detail-view').hidden = true;
  $('#dashboard-view').hidden = false;
  loadDashboard();
}

if (sessionStorage.getItem('poc_view') === 'pipeline') {
  sessionStorage.removeItem('poc_view');
  showPipelineView();
} else {
  loadDashboard();
}

// ============================================================
// Dashboard: project list (table)
// ============================================================
async function loadDashboard() {
  $('#dash-loading-msg').hidden = false;
  $('#dash-empty-msg').hidden = true;
  $('#dash-table').hidden = true;
  try {
    const data = await api('/api/history');
    renderDashboardTable(data.projects);
  } catch (e) {
    $('#dash-loading-msg').textContent = 'Could not load projects: ' + e.message;
  }
}

function renderDashboardTable(projects) {
  const loadingMsg = $('#dash-loading-msg');
  const emptyMsg = $('#dash-empty-msg');
  const table = $('#dash-table');
  const body = $('#dash-table-body');
  body.innerHTML = '';
  loadingMsg.hidden = true;

  if (!projects.length) {
    emptyMsg.hidden = false; table.hidden = true; return;
  }
  emptyMsg.hidden = true; table.hidden = false;

  projects.forEach(p => {
    const date = p.created_at ? new Date(p.created_at).toLocaleString() : 'unknown';
    const badge = el('span', { class: `history-badge ${statusSlug(p.handoff_status)}`, text: p.handoff_status || 'unknown' });
    const row = el('tr', {}, [
      el('td', { class: 'dash-idea-cell', text: p.business_idea }),
      el('td', { class: 'dash-domain-cell', text: p.domain || 'unclassified' }),
      el('td', { text: String(p.artefact_count) }),
      el('td', {}, [badge]),
      el('td', { class: 'dash-date-cell', text: date }),
    ]);
    row.addEventListener('click', () => openDashboardDetail(p.id));
    body.appendChild(row);
  });
}

// ============================================================
// Dashboard: project detail (view past artefacts)
// ============================================================
let historyDetailArtefacts = [];
let historyDetailActiveIndex = 0;

async function openDashboardDetail(id) {
  $('#dashboard-view').hidden = true;
  $('#dashboard-detail-view').hidden = false;
  $('#history-detail-meta').textContent = 'Loading…';
  $('#history-tabs').innerHTML = '';
  $('#history-doc-viewer').innerHTML = '';

  try {
    const record = await api(`/api/history/${id}`);
    const date = record.created_at ? new Date(record.created_at).toLocaleString() : 'unknown date';
    $('#history-detail-meta').innerHTML =
      `<strong>${escapeHtml(record.business_idea)}</strong><br>` +
      `Domain: ${escapeHtml(record.domain || 'unclassified')} · Created: ${escapeHtml(date)} · Handoff: ${escapeHtml(record.handoff_status || 'unknown')}`;

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
  $('#history-doc-viewer').innerHTML = window.marked ? marked.parse(markdown) : markdown;
}

$('#btn-history-download-current').addEventListener('click', () => {
  const a = historyDetailArtefacts[historyDetailActiveIndex];
  if (a) downloadMarkdown(`${a.type}.md`, a.content_markdown);
});
$('#btn-history-download-all').addEventListener('click', () => {
  historyDetailArtefacts.forEach((a, i) => setTimeout(() => downloadMarkdown(`${a.type}.md`, a.content_markdown), i * 350));
});

// ============================================================
// SHEET 01 — Intake
// ============================================================
document.querySelectorAll('.chip').forEach(chip => {
  chip.addEventListener('click', () => { $('#idea-input').value = chip.dataset.idea; });
});

$('#btn-submit-idea').addEventListener('click', async () => {
  const idea = $('#idea-input').value.trim();
  if (!idea) return;
  const btn = $('#btn-submit-idea');
  btn.disabled = true; btn.textContent = 'Running discovery…';

  try {
    const data = await api('/api/project', { method: 'POST', body: JSON.stringify({ idea }) });
    projectId = data.project_id;
    questions = data.questions;
    setTitleBlock({ projectId, domain: `${data.domain} (${Math.round(data.confidence * 100)}%)` });
    await refreshDomainCount();
    if (data.learned_new_domain) $('#learned-banner').hidden = false;

    dfAnswers = {};
    dfIndex = 0;
    dfShowingReview = false;
    dfReturnToReview = false;
    unlock('#panel-discovery');
    showDiscoveryQuestion(0);
  } catch (e) {
    alert('Something went wrong: ' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = 'Run discovery →';
  }
});

// ============================================================
// SHEET 02 — Discovery: sequential, conversational question flow
// ============================================================
const DF_MICROCOPY = {
  first: "Let's shape your idea into a plan.",
  penultimate: 'A few more details.',
  last: 'Almost there — last question.',
};

function microcopyFor(i, total) {
  if (total <= 1) return DF_MICROCOPY.first;
  if (i === 0) return DF_MICROCOPY.first;
  if (i === total - 1) return DF_MICROCOPY.last;
  if (i === total - 2) return DF_MICROCOPY.penultimate;
  if (i > 0 && i % 3 === 0) return "Let's narrow this down.";
  return '';
}

function humanizeCategory(cat) {
  return (cat || '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function updateDiscoveryStatus() {
  const answeredCount = questions.filter(q => dfAnswers[q.id]).length;
  if (dfShowingReview) { $('#discovery-status').textContent = 'reviewing'; return; }
  $('#discovery-status').textContent = answeredCount >= questions.length
    ? 'complete'
    : `${answeredCount} / ${questions.length} answered`;
}

function showDiscoveryQuestion(index) {
  dfIndex = Math.max(0, Math.min(index, questions.length - 1));
  dfShowingReview = false;
  $('#discovery-review').hidden = true;
  $('#discovery-flow').hidden = false;
  renderCurrentQuestion();
  updateDiscoveryStatus();
}

// Jump to a specific question from the review screen. Continuing from here
// returns straight to the review instead of marching through every
// remaining question, and answering it doesn't touch any other answer.
function editFromReview(index) {
  dfReturnToReview = true;
  showDiscoveryQuestion(index);
}

function renderCurrentQuestion() {
  const q = questions[dfIndex];
  const total = questions.length;

  // Progress
  $('#df-progress-fill').style.width = `${((dfIndex) / total) * 100 + (100 / total) * 0.15}%`;
  $('#df-progress-label').textContent = `Question ${dfIndex + 1} of ${total}`;

  // Copy
  $('#df-microcopy').textContent = microcopyFor(dfIndex, total);
  $('#df-category').textContent = humanizeCategory(q.category);
  $('#df-question').textContent = q.text;

  // Nav
  $('#df-btn-back').hidden = dfIndex === 0;
  $('#df-btn-to-review').hidden = !dfReturnToReview;
  $('#df-btn-continue').textContent = dfReturnToReview ? 'Save & return to review →' : 'Continue →';

  const existingAnswer = dfAnswers[q.id] || '';
  const optionsWrap = $('#df-options');
  const freetextWrap = $('#df-freetext');
  const freetextInput = $('#df-freetext-input');
  const otherWrap = $('#df-other-wrap');
  const otherInput = $('#df-other-input');
  const continueBtn = $('#df-btn-continue');

  optionsWrap.innerHTML = '';
  otherWrap.hidden = true;
  otherInput.value = '';

  if (q.options && q.options.length) {
    freetextWrap.hidden = true;
    const allOptions = [...q.options, OTHER_LABEL];
    const matchedOption = allOptions.includes(existingAnswer) ? existingAnswer : (existingAnswer ? OTHER_LABEL : '');

    allOptions.forEach(opt => {
      const isOther = opt === OTHER_LABEL;
      const card = el('button', {
        type: 'button',
        class: 'df-option' + (opt === matchedOption ? ' selected' : ''),
        role: 'radio',
        'aria-checked': opt === matchedOption ? 'true' : 'false',
      }, [
        el('span', { class: 'df-option-label', text: opt }),
      ]);
      if (isOther) {
        card.appendChild(el('span', { class: 'df-option-hint', text: 'Write your own answer' }));
      }
      card.addEventListener('click', () => selectOption(q, opt, card));
      optionsWrap.appendChild(card);
    });

    if (matchedOption === OTHER_LABEL) {
      otherWrap.hidden = false;
      otherInput.value = existingAnswer;
    }

    continueBtn.hidden = !matchedOption;
    continueBtn.disabled = matchedOption === OTHER_LABEL && !existingAnswer.trim();
  } else {
    freetextWrap.hidden = false;
    freetextInput.value = existingAnswer;
    continueBtn.hidden = false;
    continueBtn.disabled = !existingAnswer.trim();
    setTimeout(() => freetextInput.focus(), 50);
  }

  otherInput.oninput = () => {
    continueBtn.disabled = !otherInput.value.trim();
  };
  freetextInput.oninput = () => {
    continueBtn.disabled = !freetextInput.value.trim();
  };
}

async function selectOption(q, optionLabel, cardEl) {
  document.querySelectorAll('#df-options .df-option').forEach(c => {
    c.classList.remove('selected'); c.setAttribute('aria-checked', 'false');
  });
  cardEl.classList.add('selected');
  cardEl.setAttribute('aria-checked', 'true');

  const continueBtn = $('#df-btn-continue');
  const otherWrap = $('#df-other-wrap');
  const otherInput = $('#df-other-input');

  if (optionLabel === OTHER_LABEL) {
    otherWrap.hidden = false;
    otherInput.value = dfAnswers[q.id] && !q.options.includes(dfAnswers[q.id]) ? dfAnswers[q.id] : '';
    continueBtn.hidden = false;
    continueBtn.disabled = !otherInput.value.trim();
    otherInput.focus();
    return;
  }

  otherWrap.hidden = true;
  continueBtn.hidden = false;
  continueBtn.disabled = false;
  await saveAnswer(q.id, optionLabel);
  // Conversational feel: auto-advance shortly after a tap.
  setTimeout(() => { if (dfAnswers[q.id] === optionLabel) goToNextQuestion(); }, 350);
}

async function saveAnswer(questionId, answerText) {
  answerText = (answerText || '').trim();
  if (!answerText) return;
  dfAnswers[questionId] = answerText;
  updateDiscoveryStatus();
  try {
    await api(`/api/project/${projectId}/answer`, { method: 'POST', body: JSON.stringify({ question_id: questionId, answer: answerText }) });
  } catch (e) {
    alert('Could not save answer: ' + e.message);
  }
}

async function confirmCurrentAnswerAndAdvance() {
  const q = questions[dfIndex];
  if (q.options && q.options.length) {
    const otherWrap = $('#df-other-wrap');
    if (!otherWrap.hidden) {
      const val = $('#df-other-input').value.trim();
      if (!val) return;
      await saveAnswer(q.id, val);
    } else if (!dfAnswers[q.id]) {
      return; // nothing selected yet
    }
  } else {
    const val = $('#df-freetext-input').value.trim();
    if (!val) return;
    await saveAnswer(q.id, val);
  }
  goToNextQuestion();
}

function goToNextQuestion() {
  if (dfReturnToReview) {
    dfReturnToReview = false;
    showDiscoveryReview();
    return;
  }
  if (dfIndex < questions.length - 1) {
    showDiscoveryQuestion(dfIndex + 1);
  } else {
    showDiscoveryReview();
  }
}

$('#df-btn-continue').addEventListener('click', confirmCurrentAnswerAndAdvance);
$('#df-freetext-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) confirmCurrentAnswerAndAdvance();
});
$('#df-other-input').addEventListener('keydown', e => { if (e.key === 'Enter') confirmCurrentAnswerAndAdvance(); });
$('#df-btn-back').addEventListener('click', () => {
  if (dfIndex > 0) showDiscoveryQuestion(dfIndex - 1);
});
$('#df-btn-to-review').addEventListener('click', () => {
  dfReturnToReview = false;
  showDiscoveryReview();
});

// ---- Review / confirmation screen ----
function showDiscoveryReview() {
  dfShowingReview = true;
  dfReturnToReview = false;
  $('#discovery-flow').hidden = true;
  $('#discovery-review').hidden = false;
  updateDiscoveryStatus();
  renderReview();
}

function renderReview() {
  const container = $('#df-review-groups');
  container.innerHTML = '';

  const seenCategories = [];
  const byCategory = {};
  questions.forEach(q => {
    if (!byCategory[q.category]) { byCategory[q.category] = []; seenCategories.push(q.category); }
    byCategory[q.category].push(q);
  });

  seenCategories.forEach(cat => {
    const section = el('div', { class: 'df-review-section' }, [
      el('div', { class: 'df-review-section-title', text: humanizeCategory(cat) }),
    ]);
    byCategory[cat].forEach(q => {
      const idx = questions.indexOf(q);
      const answer = dfAnswers[q.id] || '(not answered)';
      const editBtn = el('button', { type: 'button', class: 'df-review-edit', text: 'Edit' });
      editBtn.addEventListener('click', () => editFromReview(idx));
      section.appendChild(el('div', { class: 'df-review-item' }, [
        el('div', { class: 'df-review-item-body' }, [
          el('p', { class: 'df-review-q', text: q.text }),
          el('p', { class: 'df-review-a', text: answer }),
        ]),
        editBtn,
      ]));
    });
    container.appendChild(section);
  });
}

$('#df-btn-review-back').addEventListener('click', () => showDiscoveryQuestion(questions.length - 1));

$('#btn-run-agents').addEventListener('click', async () => {
  const allAnswered = questions.every(q => dfAnswers[q.id]);
  if (!allAnswered) { alert('A few questions still need an answer.'); return; }
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

  const totalWidth = NODE_X_START * 2 + Math.max(0, agentMeta.length - 1) * NODE_X_GAP;
  svg.setAttribute('viewBox', `0 0 ${totalWidth} 160`);

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
    circle.setAttribute('cx', nodeX(i)); circle.setAttribute('cy', NODE_Y); circle.setAttribute('r', NODE_R);
    circle.setAttribute('class', 'node-circle'); circle.setAttribute('id', `node-${i}`);
    g.appendChild(circle);

    const check = document.createElementNS(ns, 'text');
    check.setAttribute('x', nodeX(i)); check.setAttribute('y', NODE_Y + 6);
    check.setAttribute('text-anchor', 'middle'); check.setAttribute('class', 'node-check'); check.setAttribute('id', `check-${i}`);
    check.textContent = '✓';
    g.appendChild(check);

    const idx = document.createElementNS(ns, 'text');
    idx.setAttribute('x', nodeX(i)); idx.setAttribute('y', NODE_Y + 5);
    idx.setAttribute('text-anchor', 'middle'); idx.setAttribute('id', `idx-${i}`);
    idx.setAttribute('fill', 'var(--text-faint)'); idx.setAttribute('font-family', 'var(--mono)'); idx.setAttribute('font-size', '13');
    idx.textContent = `0${i + 1}`;
    g.appendChild(idx);

    const label1 = document.createElementNS(ns, 'text');
    label1.setAttribute('x', nodeX(i)); label1.setAttribute('y', NODE_Y + NODE_R + 22);
    label1.setAttribute('text-anchor', 'middle'); label1.setAttribute('class', 'node-label'); label1.setAttribute('id', `label-${i}`);
    label1.textContent = agent.label;
    g.appendChild(label1);

    const label2 = document.createElementNS(ns, 'text');
    label2.setAttribute('x', nodeX(i)); label2.setAttribute('y', NODE_Y + NODE_R + 36);
    label2.setAttribute('text-anchor', 'middle'); label2.setAttribute('class', 'node-label');
    label2.setAttribute('font-size', '9'); label2.setAttribute('opacity', '0.7');
    label2.textContent = agent.note;
    g.appendChild(label2);

    svg.appendChild(g);
  });
}

function setNodeState(i, state) {
  const circle = $(`#node-${i}`), label = $(`#label-${i}`), check = $(`#check-${i}`), idx = $(`#idx-${i}`);
  circle.classList.remove('active', 'done'); label.classList.remove('active', 'done');
  if (state === 'active') {
    circle.classList.add('active'); label.classList.add('active');
  } else if (state === 'done') {
    circle.classList.add('done'); label.classList.add('done'); check.classList.add('show');
    idx.style.display = 'none';
    const trace = $(`#trace-${i}`);
    if (trace) trace.classList.add('charged');
  }
}

function logLine(text, done = false) {
  const log = $('#agent-log');
  log.appendChild(el('div', { text, class: done ? 'log-done' : '' }));
  log.scrollTop = log.scrollHeight;
}

async function runAgentPipeline() {
  $('#agents-status').textContent = 'running…';

  for (let i = 0; i < agentMeta.length; i++) {
    setNodeState(i, 'active');
    logLine(`⏳ ${agentMeta[i].label} reading project context…`);
    try {
      const data = await api(`/api/project/${projectId}/agent/${i}`, { method: 'POST' });
      setNodeState(i, 'done');
      logLine(`✓ ${agentMeta[i].label} — ${data.summary}`, true);
      if (agentMeta[i].role === 'ai_handoff_validation') showQaVerdict(data);
    } catch (e) {
      logLine(`✗ ${agentMeta[i].label} failed: ${e.message}`);
      $('#agents-status').textContent = 'error';
      return;
    }
  }

  $('#agents-status').textContent = `complete — ${agentMeta.length}/${agentMeta.length}`;
  $('#btn-export').hidden = false;
}

function showQaVerdict(data) {
  const status = (data.output && data.output.final_handoff_status) || 'unknown';
  const box = $('#qa-verdict');
  box.hidden = false;
  box.className = `qa-verdict ${statusSlug(status)}`;

  const notes = data.consistency_notes || [];
  const notesHtml = notes.length ? '<ul>' + notes.map(n => `<li>${escapeHtml(n)}</li>`).join('') + '</ul>' : '';
  box.innerHTML = `HANDOFF STATUS: ${escapeHtml(status)}` + notesHtml;
}

// ============================================================
// SHEET 04 — Artefacts (5-document package)
// ============================================================
let currentArtefacts = [];
let activeArtefactIndex = 0;

$('#btn-export').addEventListener('click', async () => {
  unlock('#panel-artefacts');
  const btn = $('#btn-export');
  btn.disabled = true; btn.textContent = 'Exporting…';
  try {
    const data = await api(`/api/project/${projectId}/export`, { method: 'POST' });
    renderArtefacts(data.artefacts);
  } catch (e) {
    alert('Export failed: ' + e.message);
  } finally {
    btn.disabled = false; btn.textContent = 'Export 5-document package →';
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
  $('#doc-viewer').innerHTML = window.marked ? marked.parse(markdown) : markdown;
}

$('#btn-download-current').addEventListener('click', () => {
  const a = currentArtefacts[activeArtefactIndex];
  if (a) downloadMarkdown(`${a.type}.md`, a.content_markdown);
});
$('#btn-download-all').addEventListener('click', () => {
  currentArtefacts.forEach((a, i) => setTimeout(() => downloadMarkdown(`${a.type}.md`, a.content_markdown), i * 350));
});
