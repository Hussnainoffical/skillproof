/* SkillProof browser client. Dynamic values are HTML-escaped before template insertion. */
const state = { cases: [], caseId: null, detail: null, checks: [], checksPartial: false, checksPagesScanned: 0, selectedDoc: null, selectedPage: 1, page: null, captureRegionId: "", aiStatus: null, aiResult: null, aiBusy: false, editRequirementId: null, pollTimer: null };
const $ = (selector, root = document) => root.querySelector(selector);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;", "'":"&#39;"}[c]));
const shortDate = (value) => value ? new Date(value).toLocaleDateString(undefined,{year:"numeric",month:"short",day:"numeric"}) : "";
const bytes = (n) => n < 1024 ? `${n} B` : n < 1048576 ? `${(n/1024).toFixed(0)} KB` : `${(n/1048576).toFixed(1)} MB`;
const stateLabels = { queued:"Queued", processing:"Extracting", ready:"Ready to review", partial:"Partial extract", needs_ocr:"Needs OCR", failed:"Needs attention", open:"Open", review:"In review", ready_case:"Ready", archived:"Archived", unreviewed:"Needs review", supports:"Supports", conflicts:"Conflict to review", needs_expert:"Needs expert", not_relevant:"Not relevant" };

async function api(url, options={}) {
  const response = await fetch(url, options);
  if (response.status === 204) return null;
  const type = response.headers.get("content-type") || "";
  const data = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof data === "object" ? (data.detail || data.message || response.statusText) : data;
    throw new Error(detail || response.statusText);
  }
  return data;
}
function toast(message, type="") {
  const node=document.createElement("div"); node.className=`toast ${type}`; node.textContent=message; $("#toastRegion").append(node); setTimeout(()=>node.remove(),4300);
}
function openDialog(id){$(id).showModal()}
function closeDialogs(){document.querySelectorAll("dialog[open]").forEach(d=>d.close())}
function fmtStatus(value){return stateLabels[value] || value || "—"}
function editRequirement(id=null){
  const form=$("#requirementForm"); const req=id?state.detail.requirements.find(item=>item.id===id):null;
  state.editRequirementId=req?.id||null; form.reset();
  $("#requirementDialog .eyebrow").textContent=req?`REVISE CHECKLIST · V${req.version} → V${req.version+1}`:"CASE CHECKLIST";
  $("#requirementDialog h2").textContent=req?"Create a new version":"Add a requirement";
  form.querySelector("button[type=submit]").textContent=req?"Save new version →":"Add to checklist →";
  if(req){for(const key of ["code","title","guidance","source_name","source_url","source_checked_at"])form.elements.namedItem(key).value=req[key]||"";form.elements.namedItem("required").checked=Boolean(req.required);}
  else form.elements.namedItem("required").checked=true;
  openDialog("#requirementDialog");
}
async function showRequirementHistory(id){
  try{const history=await api(`/api/requirements/${encodeURIComponent(id)}/history`);$("#historyContent").innerHTML=history.map(item=>`<article class="version-card ${item.is_current?'current':''}"><div class="version-card-head"><b>Version ${item.version} · ${item.is_current?'Current':'Historical'}</b><span class="badge">${item.required?'Required':'Optional'}</span></div><p>${esc(item.title)}${item.guidance?`<br>${esc(item.guidance)}`:""}</p><small>${esc(item.source_name||"Source not recorded")} · checked ${esc(item.source_checked_at||"date not recorded")} · created ${esc(shortDate(item.created_at))}</small>${item.source_url?`<p><a class="source-link" href="${esc(item.source_url)}" target="_blank" rel="noreferrer">Open recorded source ↗</a></p>`:""}</article>`).join("");openDialog("#historyDialog");}
  catch(error){toast(error.message,"error");}
}

async function refreshCases(preferred=state.caseId){
  state.cases=await api("/api/cases");
  if(preferred && state.cases.some(c=>c.id===preferred)) state.caseId=preferred;
  else state.caseId=state.cases[0]?.id || null;
  renderCaseList();
  if(state.caseId) await openCase(state.caseId); else renderWelcome();
}
function renderCaseList(){
  const nav=$("#caseList");
  if(!state.cases.length){nav.innerHTML='<div class="loading-line">No cases yet</div>';return;}
  nav.innerHTML=state.cases.map(c=>`<button class="case-nav ${c.id===state.caseId?'active':''}" data-case="${esc(c.id)}" title="${esc(c.title)}"><span class="case-dot"></span><span class="case-name">${esc(c.title)}</span><span class="case-caption">${c.document_count||0}</span></button>`).join("");
  nav.querySelectorAll("[data-case]").forEach(button=>button.addEventListener("click",()=>openCase(button.dataset.case)));
}
function renderWelcome(){
  clearInterval(state.pollTimer); state.detail=null; state.selectedDoc=null;
  $("#crumbTitle").textContent="Overview";
  $("#workspace").innerHTML=`<div class="welcome"><span class="welcome-kicker"><span>✳</span> A page-linked evidence workspace</span><h1>Make complex documents <em>reviewable.</em></h1><p>Prepare qualification evidence with source pages, requirement versions, and human review in one private workspace. Your files stay on this device in the local setup.</p><div class="welcome-actions"><button class="button button-primary" id="welcomeNew">＋ Create a case <span>→</span></button><button class="button" id="welcomeDemo">Explore with synthetic data</button></div><div class="welcome-grid"><article class="welcome-card"><span>⌕</span><b>Every claim has a source</b><p>Open the original page and preserve the exact excerpt used during review.</p></article><article class="welcome-card"><span>✓</span><b>People make the call</b><p>Extraction and text differences are prompts. Reviewers decide what the evidence supports.</p></article><article class="welcome-card"><span>▣</span><b>Use a current checklist</b><p>Record the official source and date you checked each case requirement.</p></article></div></div>`;
  $("#welcomeNew").addEventListener("click",()=>openDialog("#caseDialog"));
  $("#welcomeDemo").addEventListener("click",createDemo);
}
async function openCase(caseId){
  if(state.caseId!==caseId)state.aiResult=null; state.caseId=caseId; state.selectedDoc=null; state.page=null; renderCaseList();
  try{state.detail=await api(`/api/cases/${encodeURIComponent(caseId)}`); state.aiStatus=await api("/api/ai/status"); const result=await api(`/api/cases/${encodeURIComponent(caseId)}/checks`);state.checks=result.potential_discrepancies;state.checksPartial=result.partial_scan;state.checksPagesScanned=result.pages_scanned;renderCase();}
  catch(error){toast(error.message,"error");}
}
function statCard(label,value,note,icon,good=false){return `<article class="stat-card"><div class="stat-top"><span>${esc(label)}</span><span class="stat-icon">${icon}</span></div><div class="stat-value">${esc(value)}</div><div class="stat-note ${good?'good':''}">${esc(note)}</div></article>`}
function renderCase(){
  if(!state.detail)return;
  const {case:c,requirements,documents,evidence,jobs}=state.detail;
  $("#crumbTitle").textContent=c.title;
  const processed=documents.filter(d=>["ready","partial","needs_ocr"].includes(d.status)).length;
  const reviewed=evidence.filter(e=>e.disposition!=="unreviewed").length;
  const pending=evidence.filter(e=>e.disposition==="unreviewed").length;
  const required= requirements.filter(r=>r.required).length;
  const latestJob=jobs.find(j=>["queued","running"].includes(j.state));
  $("#workspace").innerHTML=`
    <div class="boundary-banner"><span class="shield">⬡</span><div><b>Evidence preparation only.</b><p>This workspace does not authenticate documents, decide equivalence or eligibility, or recommend a hiring decision. Inspect every source page.</p></div></div>
    <div class="page-head"><div><span class="eyebrow">CASE REVIEW</span><h1>${esc(c.title)}</h1><p>Keep each requirement tied to a current source, then record what a human reviewer observed.</p><div class="case-meta">${c.occupation?`<span class="meta-chip">Role <b>${esc(c.occupation)}</b></span>`:""}${c.jurisdiction?`<span class="meta-chip">Jurisdiction <b>${esc(c.jurisdiction)}</b></span>`:""}${c.source_country?`<span class="meta-chip">Training country <b>${esc(c.source_country)}</b></span>`:""}<select id="caseStatus" class="status-select" aria-label="Case status"><option value="open" ${c.status==='open'?'selected':''}>Open</option><option value="review" ${c.status==='review'?'selected':''}>In review</option><option value="ready" ${c.status==='ready'?'selected':''}>Reviewer ready</option><option value="archived" ${c.status==='archived'?'selected':''}>Archived</option></select></div></div><div class="head-actions"><a class="button" href="/api/cases/${esc(c.id)}/packet.md">↓ Export packet</a><button class="button button-danger" id="deleteCase">Delete case</button></div></div>
    ${latestJob?`<div class="alert-banner"><b>Document processing is active.</b> Progress is saved locally and continues in the background. You can keep reviewing requirements.</div>`:""}
    <div class="stats-grid">${statCard("CASE REQUIREMENTS",required,`${requirements.length} checklist item${requirements.length===1?'':'s'} added`,"☷")}${statCard("DOCUMENTS",documents.length,`${processed} processed · ${documents.reduce((n,d)=>n+(d.page_count||0),0)} pages indexed`,"▤")}${statCard("EVIDENCE CAPTURED",state.detail.evidence_total??evidence.length,`${(state.detail.evidence_total??evidence.length)-(state.detail.evidence_pending??pending)} reviewed · ${state.detail.evidence_pending??pending} awaiting review`,"⌕")}${statCard("POTENTIAL DIFFERENCES",state.checks.length,"Text patterns to inspect · not findings","⚑",state.checks.length===0)}</div>
    ${renderAIAnalyst(requirements)}
    <div class="content-grid"><section class="panel"><div class="panel-head"><div class="panel-title"><span class="stat-icon">☷</span><div><h2>Requirements</h2><span class="panel-subtitle">Version the source for this case</span></div><span class="count-pill">${requirements.length}</span></div></div><div class="panel-body"><div class="requirement-list">${requirements.length?requirements.map(r=>requirementCard(r,evidence)).join(""):`<div class="empty-note"><b>No checklist items yet</b>Add requirements using the responsible authority's current information.</div>`}</div><button id="addRequirement" class="add-row">＋ Add a requirement and source</button></div></section>
    <section class="panel document-panel"><div class="panel-head"><div class="panel-title"><span class="stat-icon">▤</span><div><h2>Source documents</h2><span class="panel-subtitle">PDFs and images · page-linked extraction</span></div><span class="count-pill">${documents.length}</span></div></div><div class="upload-zone" id="dropZone"><span class="upload-icon">↑</span><b>Upload a consented document</b><p>PDF or PNG, JPEG, TIFF, WebP · up to 200 MB per file<br>Files remain on this device in the local setup.</p><label class="button button-sm" for="fileInput">Choose file</label><input id="fileInput" type="file" accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.webp,application/pdf,image/png,image/jpeg,image/tiff,image/webp" multiple></div>
    <div class="notice"><strong>Review boundary:</strong> OCR/text extraction may be wrong. A missing field or absent public registry result is not evidence of fraud. Enable optional OCR for scanned images; source files remain available for visual inspection.</div><div id="documentList" class="document-list">${documents.length?documents.map(documentRow).join(""):`<div class="empty-note">No source files uploaded yet.</div>`}</div>${state.selectedDoc?renderInspector(state.selectedDoc,state.page):""}</section></div>
    ${renderDiscrepancies()}
    <section class="panel evidence-panel"><div class="panel-head"><div class="panel-title"><span class="stat-icon">⌕</span><div><h2>Evidence and reviewer decisions</h2><span class="panel-subtitle">Open the cited page to inspect each excerpt</span></div><span class="count-pill">${state.detail.evidence_total??evidence.length}</span></div></div><div class="evidence-list">${evidence.length?evidence.map(evidenceRow).join(""):`<div class="empty-note"><b>No evidence linked yet</b>Open a processed document and capture an exact source excerpt against a requirement.</div>`}</div>${state.detail.evidence_cursor?`<button id="loadMoreEvidence" class="add-row">Load older evidence · ${evidence.length} of ${state.detail.evidence_total}</button>`:""}</section>`;
  bindCaseActions();
  if(jobs.some(j=>["queued","running"].includes(j.state))) scheduleRefresh(); else clearInterval(state.pollTimer);
}
function renderAIAnalyst(requirements){
  const result=state.aiResult;
  const observations=result?.observations?.map(item=>`<article class="ai-observation"><div class="ai-observation-head"><span class="badge">${esc(item.relation)}</span><button data-source="${esc(item.document_id)}" data-page="${item.page_number}">${esc(item.document_name)} · page ${item.page_number} ↗</button></div><blockquote>“${esc(item.quote)}”</blockquote><p>${esc(item.observation)}</p></article>`).join("")||"";
  const status=state.aiStatus;
  return `<section class="panel ai-panel"><div class="panel-head"><div class="panel-title"><span class="stat-icon">✳</span><div><h2>AI evidence analyst</h2><span class="panel-subtitle">Searches page-level sources, then checks every citation against the original extracted text</span></div></div><span class="ai-local-state">${status?.available?`LOCAL MODEL · ${esc(status.model)}`:"LOCAL MODEL NOT READY"}</span></div><form id="aiForm" class="ai-form"><label>Ask a question about these documents<textarea name="question" rows="3" maxlength="1200" required placeholder="e.g. Which pages state the awarding institution, and do they use the same name?"></textarea></label><div class="ai-form-foot"><label>Focus on a current requirement<select name="requirement_id"><option value="">No specific requirement</option>${requirements.map(r=>`<option value="${esc(r.id)}">${esc(r.title)}</option>`).join("")}</select></label><button class="button button-primary" ${state.aiBusy||!status?.available?"disabled":""}>${state.aiBusy?"Analyzing source pages…":"Analyze cited pages →"}</button></div></form><p class="ai-privacy">${esc(status?.reason||"Checking local model…")} Source text is sent only to Ollama on this device. AI output is provisional; it does not make legal, equivalence, authenticity, or hiring decisions.</p>${result?`<div class="ai-results"><h3>Provisional analysis</h3><p>${esc(result.summary)}</p>${result.rejected_citations?`<div class="notice">${result.rejected_citations} unsupported citation${result.rejected_citations===1?" was":"s were"} removed. Treat the model answer as incomplete.</div>`:""}${observations||`<div class="empty-note">No source-verified citations were returned. Try another question or inspect the source pages.</div>`}${result.uncertainties?.length?`<h4>Uncertainties</h4><ul>${result.uncertainties.map(x=>`<li>${esc(x)}</li>`).join("")}</ul>`:""}</div>`:""}</section>`;
}
async function runAIAnalysis(event){
  event.preventDefault();const form=new FormData(event.currentTarget);state.aiBusy=true;renderCase();
  try{state.aiResult=await api(`/api/cases/${encodeURIComponent(state.caseId)}/ai/analyze`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question:form.get("question"),requirement_id:form.get("requirement_id")||null})});}
  catch(error){toast(error.message,"error");}
  finally{state.aiBusy=false;renderCase();}
}

function requirementCard(r,evidence){
  const items=evidence.filter(e=>e.requirement_id===r.id); const itemCount=Number(r.evidence_count??items.length); const unreviewed=Number(r.unreviewed_count??items.filter(e=>e.disposition==="unreviewed").length); const done=Number(r.supported_count??items.filter(e=>e.disposition==="supports").length);
  const href=/^https?:\/\//i.test(r.source_url||"")?r.source_url:"";
  const source=href?`<a class="source-link" target="_blank" rel="noreferrer" href="${esc(href)}">${esc(r.source_name||"Official source")} ↗</a>`:esc(r.source_name||"Source not recorded");
  return `<article class="requirement-card"><div class="requirement-row"><span class="req-symbol">${done?"✓":"○"}</span><div><h3>${esc(r.title)} <span class="source-tag">· v${r.version}${r.required?" · required":""}</span></h3><div class="req-state">${itemCount?`${itemCount} evidence item${itemCount===1?'':'s'} · ${unreviewed} unreviewed`:"No evidence linked"}</div></div><div class="req-tools"><button class="icon-button edit-requirement" data-id="${esc(r.id)}" aria-label="Create a requirement revision" title="Create a requirement revision">✎</button><button class="icon-button history-requirement" data-id="${esc(r.id)}" aria-label="View requirement history" title="View requirement history">↻</button><button class="icon-button delete-requirement" data-id="${esc(r.id)}" aria-label="Remove requirement" title="Remove from current checklist">×</button></div></div>${r.guidance?`<p>${esc(r.guidance)}</p>`:""}<div class="req-foot"><span>${source}</span><span>v${r.version} · ${esc(r.source_checked_at||"Never checked")}</span></div></article>`;
}
function documentRow(d){
  const icon=d.media_type?.startsWith("image/")?"image":""; const ext=d.media_type==="application/pdf"?"PDF":d.media_type?.startsWith("image/")?"IMG":"DEMO";
  const active=["queued","processing"].includes(d.status);
  const errors=d.error_message?`<small>${esc(d.error_message)}</small>`:"";
  return `<article class="document-row ${active?'processing':''}"><span class="doc-icon ${icon}">${ext}</span><div class="doc-main"><b title="${esc(d.original_name)}">${esc(d.original_name)}</b><small>${d.size_bytes?bytes(d.size_bytes):"synthetic example"} · ${d.page_count||0} page${d.page_count===1?'':'s'}${d.extracted_chars?` · ${d.extracted_chars.toLocaleString()} chars`:""}</small>${active?'<div class="progress-track"><div class="progress-bar"></div></div>':errors}</div><div class="doc-tools"><span class="doc-state ${d.status==='ready'?'ready':d.status==='failed'?'failed':''}">${esc(fmtStatus(d.status))}</span><button class="doc-review" data-open-doc="${esc(d.id)}" ${d.page_count?'':'disabled'}>Inspect</button><button class="doc-delete" data-delete-doc="${esc(d.id)}" aria-label="Delete document">×</button></div></article>`;
}
function renderInspector(docId,page){
  const doc=state.detail.documents.find(d=>d.id===docId);if(!doc)return "";
  const pg=page?.page_number||state.selectedPage;
  const pageSelector=doc.page_count>1?`<div class="page-controls"><button id="prevPage" aria-label="Previous page">‹</button><span>Page ${pg} of ${doc.page_count}</span><button id="nextPage" aria-label="Next page">›</button></div>`:`<div class="page-controls"><span>Page ${doc.page_count?1:"—"}${doc.page_count?` of ${doc.page_count}`:""}</span></div>`;
  const suggestions=page?.suggestions?.length?`<div class="suggestion-list"><h4>TEXT SUGGESTIONS · VERIFY AGAINST PAGE</h4>${page.suggestions.slice(0,12).map((s,i)=>`<div class="suggestion-item"><p>${esc(s.claim_text)}</p><button data-capture="${i}">+ Capture exact excerpt${s.region_id?" · link region":""}</button></div>`).join("")}</div>`:"";
  const source=doc.storage_name===undefined&&doc.media_type!=="text/plain"?`<iframe title="Original source file" src="/api/documents/${esc(doc.id)}/source#page=${pg}"></iframe>`:`<div class="source-placeholder">Synthetic example<br>There is no uploaded source file for this page.</div>`;
  return `<div id="inspector" class="inspector scroll-anchor"><div class="inspector-head"><b>Source inspection · ${esc(doc.original_name)}</b><div class="inspector-actions"><button class="button button-sm" id="closeInspector">Close</button>${pageSelector}</div></div><div class="inspector-body"><div class="source-view">${source}</div><div class="page-text"><h4>PAGE TEXT · PAGE ${pg}</h4>${page?`<pre>${esc(page.text||"No text was extracted from this page.")}</pre>${page.text_truncated_for_display?'<p class="doc-state">Display clipped to 40,000 characters. The original remains unchanged.</p>':""}${page.tables?.length?`<div class="suggestion-list"><h4>TABLE CANDIDATES (${page.tables.length}) · VERIFY ORIGINAL</h4>${page.tables.map(t=>`<div class="suggestion-item"><p>${t.rows.slice(0,5).map(row=>row.map(c=>esc(c||"")).join(" | ")).join("<br>")}</p></div>`).join("")}</div>`:""}${suggestions}`:`<div class="empty-note">Loading page evidence…</div>`}</div></div>${state.captureQuote?renderCaptureForm(doc,page):""}</div>`;
}
function renderCaptureForm(doc,page){
  const quote=state.captureQuote;
  return `<form id="captureForm" class="capture-form"><label>Exact excerpt from page ${page?.page_number||state.selectedPage}<textarea name="claim_text" rows="2" required>${esc(quote)}</textarea></label><div class="form-grid"><label>Link to requirement<select name="requirement_id"><option value="">Unassigned evidence</option>${state.detail.requirements.map(r=>`<option value="${esc(r.id)}">${esc(r.title)}</option>`).join("")}</select></label><label>Evidence type<select name="claim_type"><option value="qualification">Qualification or award</option><option value="institution">Institution</option><option value="identity_or_name">Name or identity field</option><option value="date">Date</option><option value="translation">Translation evidence</option><option value="supporting_evidence">Supporting excerpt</option></select></label></div><div class="modal-actions"><button type="button" class="button button-quiet button-sm" id="cancelCapture">Cancel</button><button class="button button-primary button-sm">Save source-linked evidence</button></div></form>`;
}
function evidenceRow(e){
  const badge=e.disposition||"unreviewed";const doc=state.detail.documents.find(d=>d.id===e.document_id);
  const requirementLabel=e.requirement_title?`${e.requirement_title} · v${e.requirement_version}`:"Unassigned requirement";
  return `<article class="evidence-row"><div><p class="evidence-quote">“${esc(e.claim_text)}”</p><div class="evidence-source"><span>${esc(requirementLabel)}</span><span>·</span><span>${esc(e.original_name)}</span><span>·</span><button data-source="${esc(e.document_id)}" data-page="${e.page_number}">Page ${e.page_number} ↗</button></div></div><div class="evidence-badges"><span class="badge ${esc(badge)}">${esc(fmtStatus(badge))}</span><span class="badge">${e.provenance==='human_verified'?'Human reviewed':e.provenance==='human_observed'?'Human observed':'System suggestion'}</span></div>${e.disposition==="unreviewed"?`<div class="review-actions"><input class="note-input" data-note="${esc(e.id)}" aria-label="Reviewer note" placeholder="Optional reviewer note"><button class="button" data-review="${esc(e.id)}" data-disposition="supports">Supports</button><button class="button" data-review="${esc(e.id)}" data-disposition="conflicts">Conflicts</button><button class="button" data-review="${esc(e.id)}" data-disposition="needs_expert">Needs expert</button><button class="button button-quiet" data-review="${esc(e.id)}" data-disposition="not_relevant">Not relevant</button></div>`:`<div class="review-actions"><span class="doc-state">Reviewer disposition recorded ${e.updated_at?`· ${shortDate(e.updated_at)}`:""}</span><button class="button button-sm" data-review="${esc(e.id)}" data-disposition="unreviewed">Reopen review</button></div>`}</article>`;
}
function renderDiscrepancies(){
  const empty=state.checksPartial?`No differences surfaced in the first ${state.checksPagesScanned.toLocaleString()} pages inspected. Later pages were not checked.`:"No cross-file differences found by the simple label checks. This is not evidence that documents are consistent or authentic.";
  const partial=state.checksPartial?`Scan capped at ${state.checksPagesScanned.toLocaleString()} pages; later pages are unchecked. `:"";
  return `<section class="panel diff-panel"><div class="panel-head"><div class="panel-title"><span class="stat-icon">⚑</span><div><h2>Potential cross-document differences</h2><span class="panel-subtitle">Simple label matching only · each item requires human confirmation</span></div><span class="count-pill">${state.checks.length}</span></div></div>${state.checks.length?state.checks.map(check=>`<div class="diff-item"><span class="diff-icon">!</span><div class="diff-copy"><b>Different text appears under “${esc(check.field)}”</b><p>${check.values.map(v=>`“${esc(v.value)}” — ${esc(v.document_name)}, page ${v.page_number}`).join("<br>")}</p>${check.values.map(v=>`<button data-source="${esc(v.document_id)}" data-page="${v.page_number}">Open ${esc(v.document_name)} · page ${v.page_number} ↗</button>`).join(" &nbsp; · &nbsp; ")}</div></div>`).join(""):`<div class="empty-note">${esc(empty)}</div>`}<div class="notice">${esc(partial+"Text-pattern differences are prompts only. Different dates or names can be valid; the system does not classify them as errors or fraud.")}</div></section>`;
}
function bindCaseActions(){
  $("#aiForm")?.addEventListener("submit",runAIAnalysis);
  $("#loadMoreEvidence")?.addEventListener("click",async e=>{const button=e.currentTarget;button.disabled=true;try{const cursor=state.detail.evidence_cursor;const query=new URLSearchParams({limit:"50",before_created_at:cursor.created_at,before_id:cursor.id});const result=await api(`/api/cases/${encodeURIComponent(state.caseId)}/evidence?${query}`);state.detail.evidence.push(...result.items);state.detail.evidence_total=result.total;state.detail.evidence_cursor=result.next_cursor;renderCase();}catch(error){toast(error.message,"error");button.disabled=false;}});
  $("#addRequirement")?.addEventListener("click",()=>editRequirement());
  $("#caseStatus")?.addEventListener("change",async e=>{try{await api(`/api/cases/${state.caseId}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({status:e.target.value})});toast("Case status updated","success");}catch(err){toast(err.message,"error");}});
  $("#deleteCase")?.addEventListener("click",async()=>{if(!confirm("Delete this case, its uploaded files, evidence, and review history from this local workspace?"))return;try{await api(`/api/cases/${state.caseId}`,{method:"DELETE"});state.caseId=null;state.selectedDoc=null;await refreshCases(null);toast("Case and its local files deleted","success");}catch(err){toast(err.message,"error");}});
  document.querySelectorAll(".edit-requirement").forEach(b=>b.addEventListener("click",()=>editRequirement(b.dataset.id)));
  document.querySelectorAll(".history-requirement").forEach(b=>b.addEventListener("click",()=>showRequirementHistory(b.dataset.id)));
  document.querySelectorAll(".delete-requirement").forEach(b=>b.addEventListener("click",async()=>{if(!confirm("Remove this item from the current checklist? Its old versions and linked evidence will remain in the audit history."))return;try{await api(`/api/requirements/${b.dataset.id}`,{method:"DELETE"});await openCase(state.caseId);}catch(err){toast(err.message,"error");}}));
  $("#fileInput")?.addEventListener("change",async e=>{await uploadFiles([...e.target.files]);e.target.value="";});
  const drop=$("#dropZone");if(drop){drop.addEventListener("dragover",e=>{e.preventDefault();drop.classList.add("dragging")});drop.addEventListener("dragleave",()=>drop.classList.remove("dragging"));drop.addEventListener("drop",async e=>{e.preventDefault();drop.classList.remove("dragging");await uploadFiles([...e.dataTransfer.files]);});}
  document.querySelectorAll("[data-open-doc]").forEach(b=>b.addEventListener("click",()=>inspectDocument(b.dataset.openDoc,1)));
  document.querySelectorAll("[data-delete-doc]").forEach(b=>b.addEventListener("click",async()=>{if(!confirm("Delete this file and all extracted pages and evidence linked to it?"))return;try{await api(`/api/documents/${b.dataset.deleteDoc}`,{method:"DELETE"});if(state.selectedDoc===b.dataset.deleteDoc){state.selectedDoc=null;state.page=null;}await openCase(state.caseId);toast("Document and extracted text deleted","success");}catch(err){toast(err.message,"error");}}));
  $("#closeInspector")?.addEventListener("click",()=>{state.selectedDoc=null;state.page=null;state.captureQuote=null;renderCase();});
  $("#prevPage")?.addEventListener("click",()=>inspectDocument(state.selectedDoc,Math.max(1,state.selectedPage-1)));
  $("#nextPage")?.addEventListener("click",()=>{const doc=state.detail.documents.find(d=>d.id===state.selectedDoc);inspectDocument(state.selectedDoc,Math.min(doc.page_count,state.selectedPage+1));});
  document.querySelectorAll("[data-capture]").forEach(b=>b.addEventListener("click",()=>{const item=state.page?.suggestions?.[Number(b.dataset.capture)];state.captureQuote=item?.claim_text||"";state.captureRegionId=item?.region_id||"";renderCase();}));
  $("#cancelCapture")?.addEventListener("click",()=>{state.captureQuote=null;state.captureRegionId="";renderCase();});
  $("#captureForm")?.addEventListener("submit",saveEvidence);
  document.querySelectorAll("[data-review]").forEach(b=>b.addEventListener("click",()=>reviewEvidence(b.dataset.review,b.dataset.disposition)));
  document.querySelectorAll("[data-source]").forEach(b=>b.addEventListener("click",()=>inspectDocument(b.dataset.source,Number(b.dataset.page))));
}
async function inspectDocument(docId,pageNumber){
  state.selectedDoc=docId;state.selectedPage=pageNumber;state.captureQuote=null;state.page=null;renderCase();
  try{state.page=await api(`/api/documents/${encodeURIComponent(docId)}/pages/${pageNumber}`);renderCase();setTimeout(()=>$("#inspector")?.scrollIntoView({behavior:"smooth",block:"nearest"}),30);}
  catch(error){toast(error.message,"error");}
}
async function uploadFiles(files){
  for(const file of files){const data=new FormData();data.append("file",file);try{const result=await api(`/api/cases/${state.caseId}/documents`,{method:"POST",body:data});toast(`${file.name} added to the processing queue`);await openCase(state.caseId);if(result.job_id)scheduleRefresh();}catch(error){toast(`${file.name}: ${error.message}`,"error");}}
}
async function saveEvidence(event){
  event.preventDefault();const form=new FormData(event.currentTarget);const payload={document_id:state.selectedDoc,page_number:state.selectedPage,claim_text:form.get("claim_text"),claim_type:form.get("claim_type"),requirement_id:form.get("requirement_id")||null,region_id:state.captureRegionId,provenance:"human_observed"};
  const documentId=state.selectedDoc,pageNumber=state.selectedPage;
  try{await api(`/api/cases/${state.caseId}/evidence`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});state.captureQuote=null;await openCase(state.caseId);await inspectDocument(documentId,pageNumber);toast("Evidence linked to the original page","success");}
  catch(error){toast(error.message,"error");}
}
async function reviewEvidence(id,disposition){
  const noteField=$(`[data-note="${CSS.escape(id)}"]`);const payload={disposition};if(noteField)payload.reviewer_note=noteField.value;
  try{await api(`/api/evidence/${encodeURIComponent(id)}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});await openCase(state.caseId);toast(disposition==="unreviewed"?"Evidence returned to review":"Reviewer disposition saved","success");}
  catch(error){toast(error.message,"error");}
}
function scheduleRefresh(){clearInterval(state.pollTimer);state.pollTimer=setInterval(async()=>{if(!state.caseId)return;try{const oldState=JSON.stringify(state.detail?.jobs||[]);state.detail=await api(`/api/cases/${state.caseId}`);renderCase();const newState=JSON.stringify(state.detail.jobs||[]);if(oldState!==newState){const result=await api(`/api/cases/${state.caseId}/checks`);state.checks=result.potential_discrepancies;state.checksPartial=result.partial_scan;state.checksPagesScanned=result.pages_scanned;renderCase();}}catch{}},2500);}
async function createDemo(){try{const result=await api("/api/demo",{method:"POST"});state.caseId=result.case.id;await refreshCases(state.caseId);toast("Synthetic case created. No real person or credential is represented.","success");}catch(error){toast(error.message,"error");}}

$("#newCaseBtn").addEventListener("click",()=>openDialog("#caseDialog"));
$("#helpBtn").addEventListener("click",()=>openDialog("#helpDialog"));
document.querySelectorAll("[data-close]").forEach(b=>b.addEventListener("click",closeDialogs));
document.querySelectorAll("dialog").forEach(d=>d.addEventListener("click",e=>{if(e.target===d)d.close();}));
$("#caseForm").addEventListener("submit",async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.currentTarget));try{const result=await api("/api/cases",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});closeDialogs();e.currentTarget.reset();await refreshCases(result.case.id);toast("Case created","success");}catch(error){toast(error.message,"error");}});
$("#requirementForm").addEventListener("submit",async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.currentTarget));data.required=new FormData(e.currentTarget).has("required");data.source_checked_at=data.source_checked_at||"";data.guidance=data.guidance||"";const id=state.editRequirementId;try{await api(id?`/api/requirements/${id}`:`/api/cases/${state.caseId}/requirements`,{method:id?"PUT":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});state.editRequirementId=null;closeDialogs();e.currentTarget.reset();await openCase(state.caseId);toast(id?"New requirement version saved; prior evidence remains attached to the old version":"Requirement and source recorded","success");}catch(error){toast(error.message,"error");}});
$("#appVersion").textContent="0.1";
refreshCases().catch(error=>{console.error(error);toast(`Could not open workspace: ${error.message}`,"error");$("#workspace").innerHTML=`<div class="empty-note"><b>Workspace could not load</b>${esc(error.message)}<br>Check the local server log and restart SkillProof.</div>`;});
