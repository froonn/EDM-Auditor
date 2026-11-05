"""Small browser UI for local API testing."""

from fastapi.responses import HTMLResponse


def page() -> HTMLResponse:
    return HTMLResponse("""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EDM-Auditor</title>
<style>
:root { color-scheme: light; font-family: system-ui, sans-serif; }
body { max-width: 1180px; margin: 0 auto; padding: 24px; color: #172033; background: #f5f7fb; }
h1 { margin-top: 0; } h2 { margin-bottom: 12px; }
section { background: white; border: 1px solid #dfe4ee; border-radius: 10px; padding: 18px; margin: 16px 0; }
form { display: grid; gap: 9px; max-width: 680px; }
input, textarea, button { font: inherit; padding: 8px; border: 1px solid #b9c3d4; border-radius: 6px; }
textarea { min-height: 100px; resize: vertical; } button { cursor: pointer; background: #1d5fd1; color: white; border: 0; }
button.danger { background: #b42318; } button.secondary { background: #53627a; }
table { width: 100%; border-collapse: collapse; } th, td { padding: 9px; border-bottom: 1px solid #e6e9f0; text-align: left; vertical-align: top; }
pre { white-space: pre-wrap; background: #f1f3f7; padding: 12px; border-radius: 6px; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; } .muted { color: #667085; }
.error { color: #b42318; } .ok { color: #067647; }
.status { display: inline-block; padding: 3px 8px; border-radius: 999px; font-size: .85em; font-weight: 600; }
.status-completed { color: #067647; background: #d1fadf; }
.status-partial { color: #b54708; background: #fef0c7; }
.status-pending { color: #b42318; background: #fee4e2; }
.status-processing { color: #175cd3; background: #d1e9ff; }
.diagnostics { margin-top: 8px; }
.status-classified, .status-ready { color: #067647; background: #d1fadf; }
.status-pending { color: #b42318; background: #fee4e2; }
.status-needs_review, .status-needs_configuration, .status-no_applicable_rules { color: #b54708; background: #fef0c7; }
.status-unknown { color: #53627a; background: #e6e9f0; }
.warning { color: #b54708; background: #fef0c7; border-radius: 6px; padding: 8px 12px; margin: 8px 0; }
.choices { display: flex; flex-wrap: wrap; gap: 6px 16px; margin: 8px 0; }
.choices label { display: inline-flex; gap: 6px; align-items: center; }
td.selected { color: #067647; font-weight: 600; } td.skipped { color: #667085; }
h3 { margin: 16px 0 6px; }
</style>
</head>
<body>
<h1>EDM-Auditor</h1>
<p class="muted">Локальный интерфейс для загрузки НПА, документов и просмотра аудитов.</p>
<p id="message"></p>

<section>
<h2>Загрузить НПА</h2>
<form id="act-form">
<input name="code" placeholder="Код НПА" required>
<input name="title" placeholder="Название НПА" required>
<input name="number" placeholder="Номер (необязательно)">
<input name="source_url" placeholder="URL источника (необязательно)">
<input name="document_types" placeholder="Коды типов документов через запятую (необязательно)">
<input name="file" type="file" accept=".txt,text/plain" required>
<button>Загрузить НПА</button>
</form>
<div id="acts"></div>
</section>

<section>
<h2>Правила и их применимость</h2>
<p class="muted">Правило с областью unknown не применяется автоматически: укажите для него типы документов или выберите его вручную.</p>
<div id="rules"></div>
</section>

<section>
<h2>Типы документов</h2>
<form id="type-form">
<input name="code" placeholder="Код, например travel_expense_report" pattern="[a-z][a-z0-9_]*" required>
<input name="name" placeholder="Название" required>
<input name="description" placeholder="Описание: по нему модель выбирает тип" required>
<button>Добавить тип</button>
</form>
<div id="types"></div>
<div id="type-suggestions"></div>
</section>

<section>
<h2>Загрузить документ для аудита</h2>
<form id="document-form">
<input name="title" placeholder="Название (необязательно)">
<input name="file" type="file" accept=".txt,.pdf,.docx" required>
<button>Загрузить документ</button>
</form>
<div id="documents"></div>
</section>

<section id="audit-config" hidden>
<h2 id="config-title">Настройка аудита</h2>
<div id="config-classification"></div>
<h3>Подтверждённые типы документа</h3>
<div class="choices" id="config-types"></div>
<div class="row">
<button class="secondary" onclick="confirmTypes()">Подтвердить типы</button>
<button class="secondary" onclick="resetTypes()">Вернуть автоматическую классификацию</button>
</div>
<h3>Режим выбора правил</h3>
<div class="choices" id="config-modes">
<label><input type="radio" name="selection_mode" value="automatic" checked onchange="modeChanged()"> Автоматический</label>
<label><input type="radio" name="selection_mode" value="manual" onchange="modeChanged()"> Ручной</label>
<label><input type="radio" name="selection_mode" value="combined" onchange="modeChanged()"> Комбинированный</label>
<label><input type="radio" name="selection_mode" value="all" onchange="modeChanged()"> Все правила</label>
</div>
<div class="warning" id="config-all-warning" hidden>
Режим «Все правила» — административный диагностический запуск: к документу применятся правила всех НПА, поэтому возможны ложные нарушения.
<label><input type="checkbox" id="config-confirm-all" onchange="clearPreview()"> Понимаю риск и подтверждаю запуск</label>
</div>
<h3>НПА</h3>
<p class="muted" id="config-acts-hint"></p>
<div class="choices" id="config-acts"></div>
<h3>Правила</h3>
<div id="config-rules"></div>
<div id="config-warnings"></div>
<div class="row">
<button class="secondary" onclick="previewAudit()">Показать набор правил</button>
<button onclick="runConfiguredAudit()">Запустить аудит</button>
<button class="secondary" onclick="closeConfig()">Закрыть</button>
</div>
</section>

<section>
<h2>Готовые аудиты</h2>
<div id="reports"></div>
<div id="report-selection" hidden></div>
<pre id="report-detail" hidden></pre>
</section>

<script>
const $ = (id) => document.getElementById(id);
const state = {documentId: null, preview: null, rules: [], types: []};
function message(text, error = false) {
  $("message").textContent = text;
  $("message").className = error ? "error" : "ok";
}
async function request(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw Object.assign(new Error(body.error?.message || `HTTP ${response.status}`), {status: response.status});
  return body;
}
function formData(form) { return new FormData(form); }
function statusBadge(status) {
  const safe = escapeHtml(status || "uploaded");
  return `<span class="status status-${safe}">${safe}</span>`;
}
async function loadActs() {
  const acts = await request("/api/legal-acts?limit=100");
  $("acts").innerHTML = acts.length ? `<table><tr><th>Код</th><th>Название</th><th>Номер</th><th>Обработка</th><th></th></tr>
    ${acts.map(a => `<tr><td>${escapeHtml(a.code)}</td><td>${escapeHtml(a.title)}</td>
    <td>${escapeHtml(a.number || "—")}</td><td>${statusBadge(a.processing_status)}
    <div class="muted">${a.chunks_processed}/${a.chunks_total} chunks · accepted: ${a.rules_accepted} · rejected: ${a.rules_rejected}</div>
    <div class="diagnostics row"><input id="act-types-${a.id}" value="${escapeHtml(a.document_types.join(", "))}" placeholder="типы документов через запятую">
    <button class="secondary" onclick="saveActTypes(${a.id})">Сохранить типы</button></div>
    <div class="diagnostics"><button class="secondary" onclick="showDiagnostics(${a.id})">Диагностика</button>
    <button class="secondary" onclick="reprocessAct(${a.id})">Повторить</button></div></td>
    <td><button class="danger" onclick="deleteAct(${a.id})">Удалить</button></td></tr>`).join("")}</table>`
    : '<p class="muted">НПА пока нет.</p>';
}
async function saveActTypes(id) {
  try {
    await request(`/api/legal-acts/${id}`, jsonOptions("PATCH", {document_types: splitCodes($(`act-types-${id}`).value)}));
    message("Типы документов НПА сохранены."); await Promise.all([loadActs(), loadRules()]);
  } catch (error) { message(error.message, true); }
}
async function showDiagnostics(id) {
  try {
    const result = await request(`/api/legal-acts/${id}/diagnostics`);
    const details = result.diagnostics.length
      ? result.diagnostics.map(d => `<li>${escapeHtml(d.chunk_id)}: ${statusBadge(d.status)}
        ${escapeHtml(d.error_code || "ok")} ${escapeHtml(d.diagnostic_message || "")}</li>`).join("")
      : "<li>Диагностика отсутствует.</li>";
    $("message").innerHTML = `<strong>Диагностика НПА #${id}</strong><ul>${details}</ul>`;
    $("message").className = "";
  } catch (error) { message(error.message, true); }
}
async function reprocessAct(id) {
  try { await request(`/api/legal-acts/${id}/reprocess`, {method: "POST"}); message("НПА обработан повторно."); await Promise.all([loadActs(), loadRules()]); }
  catch (error) { message(error.message, true); await loadActs(); }
}
async function deleteAct(id) {
  if (!confirm("Удалить этот НПА?")) return;
  try { await request(`/api/legal-acts/${id}`, {method: "DELETE"}); message("НПА удалён."); await Promise.all([loadActs(), loadRules()]); }
  catch (error) { message(error.message, true); }
}
const WARNING_TEXT = {
  document_type_unknown: "Тип документа определить не удалось.",
  classification_low_confidence: "Модель не уверена в типе документа: подтвердите его.",
  manual_selection_required: "Нужно подтвердить тип документа или выбрать НПА и правила.",
  no_applicable_rules: "Для этого документа нет подходящих правил.",
  rules_with_unknown_applicability: "Есть правила с неизвестной применимостью: автоматически они не применяются.",
  all_mode_false_positive_risk: "Режим всех правил может дать ложные нарушения.",
  rag_candidate_below_threshold: "Есть RAG-кандидаты ниже порога: они не влияют на выбор правил.",
  rag_unavailable: "RAG недоступен: выбор правил и проверки продолжают работать без него.",
};
const REASON_TEXT = {
  rule_included_by_user: "включено вручную",
  rule_selected_by_legal_act: "выбран НПА",
  rule_selected_by_all_mode: "режим всех правил",
  rule_universal: "универсальное правило",
  rule_matched_document_type: "совпал тип документа",
  rule_excluded_by_user: "исключено вручную",
  rule_excluded_by_document_type: "другой тип документа",
  rule_excluded_by_legal_act_scope: "НПА не выбран",
  rule_manual_only: "только ручное включение",
  rule_applicability_unknown: "применимость неизвестна",
  rule_inactive: "правило неактивно",
  manual_selection_required: "не выбрано вручную",
};
const warningList = (warnings) => warnings.map(code => `<div class="warning">${escapeHtml(WARNING_TEXT[code] || code)}</div>`).join("");
const reasonText = (code) => escapeHtml(REASON_TEXT[code] || code);
const splitCodes = (value) => String(value || "").split(",").map(item => item.trim()).filter(Boolean);
const jsonOptions = (method, body) => ({method, headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
function classificationBadge(d) {
  const confidence = d.classification_confidence == null ? "" : ` · ${Math.round(d.classification_confidence * 100)}%`;
  const types = d.confirmed_document_types.length ? d.confirmed_document_types.join(", ") : "тип не подтверждён";
  return `${statusBadge(d.classification_status)} <span class="muted">${escapeHtml(types)}${confidence}</span>`;
}
async function loadTypes() {
  const types = await request("/api/document-types");
  state.types = types;
  $("types").innerHTML = types.length ? `<table><tr><th>Код</th><th>Название</th><th></th></tr>
    ${types.map(t => `<tr><td>${escapeHtml(t.code)}</td><td>${escapeHtml(t.name)}</td>
    <td><button class="danger" data-code="${escapeHtml(t.code)}" onclick="deleteType(this.dataset.code)">Удалить</button></td></tr>`).join("")}</table>`
    : '<p class="muted">Каталог типов пуст.</p>';
}
async function loadSuggestions() {
  const items = await request("/api/document-type-suggestions");
  $("type-suggestions").innerHTML = items.length ? `<h3>Модель предлагает новые типы</h3><table><tr><th>Название</th><th>Обоснование</th><th>Встречалось</th><th></th></tr>
    ${items.map(s => `<tr><td>${escapeHtml(s.name)}</td><td>${escapeHtml(s.reason)}</td><td>${s.occurrences}</td>
    <td><button onclick="acceptSuggestion(${s.id})">Добавить</button> <button class="danger" onclick="dismissSuggestion(${s.id})">Отклонить</button></td></tr>`).join("")}</table>`
    : "";
}
async function acceptSuggestion(id) {
  const code = prompt("Код нового типа, например travel_expense_report");
  if (!code) return;
  try {
    await request(`/api/document-type-suggestions/${id}/accept`, jsonOptions("POST", {code: code.trim()}));
    message("Тип добавлен. Чтобы применить его, заново классифицируйте документы и обработайте НПА.");
    await Promise.all([loadTypes(), loadSuggestions()]);
  } catch (error) { message(error.message, true); }
}
async function dismissSuggestion(id) {
  try { await request(`/api/document-type-suggestions/${id}/dismiss`, {method: "POST"}); await loadSuggestions(); }
  catch (error) { message(error.message, true); }
}
async function deleteType(code) {
  if (!confirm(`Деактивировать тип ${code}?`)) return;
  try { await request(`/api/document-types/${encodeURIComponent(code)}`, {method: "DELETE"}); message("Тип документа деактивирован."); await loadTypes(); }
  catch (error) { message(error.message, true); }
}
async function loadRules() {
  const rules = await request("/api/rules?limit=100");
  state.rules = rules;
  $("rules").innerHTML = rules.length ? `<table><tr><th>Правило</th><th>НПА</th><th>Область</th><th>Типы документов</th><th></th></tr>
    ${rules.map(r => `<tr><td>${escapeHtml(r.name)}<div class="muted">${escapeHtml(r.rule_code)}</div></td><td>${r.legal_act_id ?? "—"}</td>
    <td><select id="rule-scope-${r.id}">${["universal", "typed", "manual_only", "unknown"].map(scope => `<option ${scope === r.applicability_scope ? "selected" : ""}>${scope}</option>`).join("")}</select>
    <div class="muted">${escapeHtml(r.applicability_source || "")}</div></td>
    <td><input id="rule-types-${r.id}" value="${escapeHtml(r.document_types.join(", "))}" placeholder="коды через запятую"></td>
    <td><button class="secondary" onclick="saveRule(${r.id})">Сохранить</button></td></tr>`).join("")}</table>`
    : '<p class="muted">Правил пока нет.</p>';
}
async function saveRule(id) {
  try {
    await request(`/api/rules/${id}/applicability`, jsonOptions("PATCH", {
      applicability_scope: $(`rule-scope-${id}`).value,
      document_types: splitCodes($(`rule-types-${id}`).value),
    }));
    message("Применимость правила сохранена."); await loadRules(); clearPreview();
  } catch (error) { message(error.message, true); }
}
async function loadDocuments() {
  const documents = await request("/api/documents?limit=100");
  $("documents").innerHTML = documents.length ? `<table><tr><th>Документ</th><th>Тип</th><th>Статус</th><th></th></tr>
    ${documents.map(d => `<tr><td>${escapeHtml(d.title)} <span class="muted">#${d.id}</span></td><td>${classificationBadge(d)}</td><td>${escapeHtml(d.status)}</td>
    <td class="row"><button onclick="audit(${d.id})">Запустить аудит</button><button class="secondary" onclick="openConfig(${d.id})">Настроить аудит</button></td></tr>`).join("")}</table>`
    : '<p class="muted">Документы пока не загружены.</p>';
}
async function audit(id) {
  try { const result = await request(`/api/documents/${id}/audit`, jsonOptions("POST", {}));
    message(`Аудит завершён: ${result.total_findings} нарушений.`);
    await Promise.all([loadDocuments(), loadReports()]);
  } catch (error) {
    message(error.message, true);
    if (error.status === 409) { await openConfig(id); await previewAudit(); }
  }
}
async function openConfig(id) {
  try {
    state.documentId = id;
    state.preview = null;
    const [auditedDocument, acts] = await Promise.all([
      request(`/api/documents/${id}`), request("/api/legal-acts?limit=100"), loadRules(), loadTypes(),
    ]);
    $("audit-config").hidden = false;
    $("config-title").textContent = `Настройка аудита: ${auditedDocument.title}`;
    renderClassification(auditedDocument);
    $("config-acts").innerHTML = acts.length
      ? acts.map(a => `<label><input type="checkbox" class="config-act" value="${a.id}" onchange="clearPreview()"> ${escapeHtml(a.code)} — ${escapeHtml(a.title)}</label>`).join("")
      : '<span class="muted">НПА пока нет.</span>';
    setSelectedMode("automatic");
    $("config-confirm-all").checked = false;
    modeChanged();
    $("audit-config").scrollIntoView();
  } catch (error) { message(error.message, true); }
}
function closeConfig() { $("audit-config").hidden = true; state.documentId = null; }
function setSelectedMode(value) { document.querySelector(`input[name=selection_mode][value=${value}]`).checked = true; }
function renderClassification(d) {
  const candidates = d.candidate_document_types.map(item => `${escapeHtml(item.code)} (${Math.round(item.confidence * 100)}%)`).join(", ");
  $("config-classification").innerHTML = `<p>${classificationBadge(d)} <span class="muted">источник: ${escapeHtml(d.classification_source || "—")}</span></p>
    ${candidates ? `<p class="muted">Кандидаты модели: ${candidates}</p>` : ""}
    ${d.needs_configuration ? '<div class="warning">Тип документа не подтверждён: подтвердите его или выберите правила вручную.</div>' : ""}`;
  $("config-types").innerHTML = state.types.map(t => `<label><input type="checkbox" class="config-type" value="${escapeHtml(t.code)}" ${d.confirmed_document_types.includes(t.code) ? "checked" : ""}> ${escapeHtml(t.name)}</label>`).join("");
}
async function saveTypes(codes) {
  try {
    const updated = await request(`/api/documents/${state.documentId}/classification`, jsonOptions("PATCH", {confirmed_document_types: codes}));
    renderClassification(updated); clearPreview(); await loadDocuments();
    message("Классификация документа обновлена.");
  } catch (error) { message(error.message, true); }
}
function confirmTypes() {
  const codes = [...document.querySelectorAll(".config-type:checked")].map(item => item.value);
  if (!codes.length) { message("Выберите хотя бы один тип документа.", true); return; }
  return saveTypes(codes);
}
function resetTypes() { return saveTypes([]); }
function selectedMode() { return document.querySelector("input[name=selection_mode]:checked").value; }
function modeChanged() {
  const mode = selectedMode();
  $("config-all-warning").hidden = mode !== "all";
  $("config-acts-hint").textContent = {
    automatic: "Если выбрать НПА, автоматический отбор ограничится ими. Без выбора учитываются все НПА.",
    manual: "Применятся правила выбранных НПА и правила, включённые вручную.",
    combined: "Правила выбранных НПА добавятся к автоматически подобранным.",
    all: "В режиме всех правил выбор НПА не используется.",
  }[mode];
  clearPreview();
}
function selectionBody() {
  const choice = (value) => state.rules.filter(rule => $(`config-rule-${rule.id}`)?.value === value).map(rule => rule.id);
  return {
    selection_mode: selectedMode(),
    legal_act_ids: [...document.querySelectorAll(".config-act:checked")].map(item => Number(item.value)),
    included_rule_ids: choice("include"),
    excluded_rule_ids: choice("exclude"),
    confirm_all: $("config-confirm-all").checked,
  };
}
function renderRuleChoices() {
  const decisions = new Map((state.preview?.decisions || []).map(item => [item.rule_id, item]));
  const previous = new Map(state.rules.map(rule => [rule.id, $(`config-rule-${rule.id}`)?.value || ""]));
  $("config-rules").innerHTML = state.rules.length ? `<table><tr><th>Правило</th><th>Область</th><th>Ручной выбор</th><th>Решение</th></tr>
    ${state.rules.map(rule => {
      const decision = decisions.get(rule.id);
      const value = previous.get(rule.id);
      return `<tr><td>${escapeHtml(rule.name)}<div class="muted">${escapeHtml(rule.rule_code)}</div></td>
      <td>${escapeHtml(rule.applicability_scope)}<div class="muted">${escapeHtml(rule.document_types.join(", "))}</div></td>
      <td><select id="config-rule-${rule.id}" onchange="clearPreview()"><option value="">Автоматически</option>
      <option value="include" ${value === "include" ? "selected" : ""}>Включить</option><option value="exclude" ${value === "exclude" ? "selected" : ""}>Исключить</option></select></td>
      <td class="${decision?.selected ? "selected" : "skipped"}">${decision ? `${decision.selected ? "применится" : "не применится"}: ${reasonText(decision.reason)}` : "—"}</td></tr>`;
    }).join("")}</table>` : '<p class="muted">Правил пока нет.</p>';
}
function clearPreview() {
  state.preview = null;
  $("config-warnings").innerHTML = "";
  renderRuleChoices();
}
async function previewAudit() {
  try {
    state.preview = await request(`/api/documents/${state.documentId}/audit/preview`, jsonOptions("POST", selectionBody()));
    renderRuleChoices();
    const recommendations = state.preview.rag_recommendations.map(item => `<li>НПА #${item.legal_act_id}${item.rule_id ? `, правило #${item.rule_id}` : ""}: ${item.score.toFixed(2)} при пороге ${item.threshold.toFixed(2)}</li>`).join("");
    $("config-warnings").innerHTML = `<p>${statusBadge(state.preview.status)} <span class="muted">выбрано правил: ${state.preview.selected_rule_ids.length}</span></p>${warningList(state.preview.warnings)}
      ${recommendations ? `<details><summary>Рекомендации RAG (не влияют на выбор)</summary><ul>${recommendations}</ul></details>` : ""}`;
  } catch (error) { message(error.message, true); }
}
async function runConfiguredAudit() {
  try {
    const result = await request(`/api/documents/${state.documentId}/audit`, jsonOptions("POST", selectionBody()));
    message(`Аудит завершён: ${result.total_findings} нарушений.`);
    await Promise.all([loadDocuments(), loadReports()]);
    await showReport(state.documentId, result.report_id);
  } catch (error) { message(error.message, true); await previewAudit(); }
}
async function loadReports() {
  const reports = await request("/api/reports?limit=100");
  $("reports").innerHTML = reports.length ? `<table><tr><th>Дата</th><th>Документ</th><th>Нарушения</th><th>Статус LLM</th><th></th></tr>
    ${reports.map(r => `<tr><td>${new Date(r.created_at).toLocaleString()}</td><td>${escapeHtml(r.document_title)} (#${r.document_id})</td>
    <td>${r.total_findings} (critical: ${r.critical_count}, high: ${r.high_count}, medium: ${r.medium_count}, low: ${r.low_count})</td>
    <td>${escapeHtml(r.neural_status)}</td><td><button class="secondary" onclick="showReport(${r.document_id}, ${r.id})">Открыть</button></td></tr>`).join("")}</table>`
    : '<p class="muted">Готовых аудитов пока нет.</p>';
}
async function showReport(documentId, reportId) {
  try { const report = await request(`/api/documents/${documentId}/report?report_id=${reportId}`);
    renderReportSelection(report.selection);
    $("report-detail").hidden = false; $("report-detail").textContent = JSON.stringify(report, null, 2);
  } catch (error) { message(error.message, true); }
}
function renderReportSelection(selection) {
  const target = $("report-selection");
  target.hidden = false;
  if (!selection) { target.innerHTML = '<p class="muted">Этот отчёт создан до появления настройки аудита: конфигурация выбора не сохранена.</p>'; return; }
  const acts = selection.applied_legal_acts.map(act => `${escapeHtml(act.code)} — ${escapeHtml(act.title)}`).join("; ") || "—";
  target.innerHTML = `<h3>Конфигурация аудита</h3>
    <p>Режим: <strong>${escapeHtml(selection.selection_mode)}</strong> · типы документа: ${escapeHtml(selection.confirmed_document_types.join(", ") || "не подтверждены")}</p>
    <p>Использованные НПА: ${acts}</p>${warningList(selection.warnings)}
    <table><tr><th>Правило</th><th>Решение</th></tr>${selection.selection_reasons.map(item => `<tr><td>${escapeHtml(item.name)}<div class="muted">${escapeHtml(item.rule_code)}</div></td>
    <td class="${item.selected ? "selected" : "skipped"}">${item.selected ? "применено" : "не применено"}: ${reasonText(item.reason)}</td></tr>`).join("")}</table>`;
}
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;" })[char]);
}
$("act-form").onsubmit = async (event) => {
  event.preventDefault();
  try { await request("/api/legal-acts/upload", {method: "POST", body: formData(event.target)});
    event.target.reset(); message("НПА загружен."); await Promise.all([loadActs(), loadRules(), loadSuggestions()]);
  } catch (error) { message(error.message, true); }
};
$("type-form").onsubmit = async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    await request("/api/document-types", jsonOptions("POST", {
      code: form.get("code"), name: form.get("name"), description: form.get("description"),
    }));
    event.target.reset(); message("Тип документа добавлен."); await loadTypes();
  } catch (error) { message(error.message, true); }
};
$("document-form").onsubmit = async (event) => {
  event.preventDefault();
  try { await request("/api/documents/upload", {method: "POST", body: formData(event.target)});
    event.target.reset(); message("Документ загружен."); await Promise.all([loadDocuments(), loadSuggestions()]);
  } catch (error) { message(error.message, true); }
};
Promise.all([loadActs(), loadRules(), loadTypes(), loadSuggestions(), loadDocuments(), loadReports()]).catch(error => message(error.message, true));
</script>
</body>
</html>""")
