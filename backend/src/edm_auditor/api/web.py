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
<input name="file" type="file" accept=".txt,text/plain" required>
<button>Загрузить НПА</button>
</form>
<div id="acts"></div>
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

<section>
<h2>Готовые аудиты</h2>
<div id="reports"></div>
<pre id="report-detail" hidden></pre>
</section>

<script>
const $ = (id) => document.getElementById(id);
function message(text, error = false) {
  $("message").textContent = text;
  $("message").className = error ? "error" : "ok";
}
async function request(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error?.message || `HTTP ${response.status}`);
  return body;
}
function formData(form) { return new FormData(form); }
async function loadActs() {
  const acts = await request("/api/legal-acts?limit=100");
  $("acts").innerHTML = acts.length ? `<table><tr><th>Код</th><th>Название</th><th>Номер</th><th></th></tr>
    ${acts.map(a => `<tr><td>${escapeHtml(a.code)}</td><td>${escapeHtml(a.title)}</td>
    <td>${escapeHtml(a.number || "—")}</td><td><button class="danger" onclick="deleteAct(${a.id})">Удалить</button></td></tr>`).join("")}</table>`
    : '<p class="muted">НПА пока нет.</p>';
}
async function deleteAct(id) {
  if (!confirm("Удалить этот НПА?")) return;
  try { await request(`/api/legal-acts/${id}`, {method: "DELETE"}); message("НПА удалён."); await loadActs(); }
  catch (error) { message(error.message, true); }
}
async function loadDocuments() {
  const documents = await request("/api/documents?limit=100");
  $("documents").innerHTML = documents.length ? `<table><tr><th>Документ</th><th>Статус</th><th></th></tr>
    ${documents.map(d => `<tr><td>${escapeHtml(d.title)} <span class="muted">#${d.id}</span></td><td>${escapeHtml(d.status)}</td>
    <td><button onclick="audit(${d.id})">Запустить аудит</button></td></tr>`).join("")}</table>`
    : '<p class="muted">Документы пока не загружены.</p>';
}
async function audit(id) {
  try { const result = await request(`/api/documents/${id}/audit`, {method: "POST"});
    message(`Аудит завершён: ${result.total_findings} нарушений.`);
    await Promise.all([loadDocuments(), loadReports()]);
  } catch (error) { message(error.message, true); }
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
    $("report-detail").hidden = false; $("report-detail").textContent = JSON.stringify(report, null, 2);
  } catch (error) { message(error.message, true); }
}
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;" })[char]);
}
$("act-form").onsubmit = async (event) => {
  event.preventDefault();
  try { await request("/api/legal-acts/upload", {method: "POST", body: formData(event.target)});
    event.target.reset(); message("НПА загружен."); await loadActs();
  } catch (error) { message(error.message, true); }
};
$("document-form").onsubmit = async (event) => {
  event.preventDefault();
  try { await request("/api/documents/upload", {method: "POST", body: formData(event.target)});
    event.target.reset(); message("Документ загружен."); await loadDocuments();
  } catch (error) { message(error.message, true); }
};
Promise.all([loadActs(), loadDocuments(), loadReports()]).catch(error => message(error.message, true));
</script>
</body>
</html>""")
