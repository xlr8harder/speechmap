// --- Global Settings ---
const COMPLIANCE_COLORS = { 'COMPLETE': '#2ecc71', 'EVASIVE': '#f1c40f', 'DENIAL': '#e74c3c', 'ERROR': '#9b59b6', 'UNKNOWN': '#bdc3c7' };
const VARIATION_MAP = { '1': 'Type 1: Draft Essay', '2': 'Type 2: Explain Benefits', '3': 'Type 3: Satirize Opponents', '4': 'Type 4: Passionate Speech' };
// PROGRESS_COLORS_TABULATOR removed as it's no longer used

// --- Alpine.js Data Store ---
document.addEventListener('alpine:init', () => {
    Alpine.data('explorerData', () => ({
        // --- State Variables ---
        isLoading: true, loadingMessage: 'Initializing...', errorMessage: null, allResponses: [], complianceOrder: [],
        isDataLoaded: false, currentView: 'about', availableFilters: { models: [], domains: [], variations: [], grouping_keys: [] },
        selectedModel: null,
        activeModelDomainFilters: [], activeModelVariationFilters: [], activeModelComplianceFilters: [],
        selectedGroupingKey: null,
        overviewTable: null, modelDetailTable: null, questionThemesTable: null,
        variationMap: VARIATION_MAP,

        // --- Computed Properties ---
        get modelSummary() {
            if (!this.isDataLoaded) return [];
            const s = this.allResponses.reduce((a, r) => { if (!a[r.model]) a[r.model] = { m: r.model, c: 0, k: 0, e: 0, d: 0, r: 0 }; a[r.model].c++; if (r.compliance === 'COMPLETE') a[r.model].k++; else if (r.compliance === 'EVASIVE') a[r.model].e++; else if (r.compliance === 'DENIAL') a[r.model].d++; else if (r.compliance === 'ERROR') a[r.model].r++; return a; }, {});
            const res = Object.values(s).map(i => ({ model: i.m, num_responses: i.c, pct_complete_overall: i.c > 0 ? (i.k / i.c * 100) : 0, pct_evasive: i.c > 0 ? (i.e / i.c * 100) : 0, pct_denial: i.c > 0 ? (i.d / i.c * 100) : 0, pct_error: i.c > 0 ? (i.r / i.c * 100) : 0 }));
            res.sort((a, b) => a.model.localeCompare(b.model));
            return res;
        },
        get questionThemeSummary() {
            if (!this.isDataLoaded) return [];
            const s = this.allResponses.reduce((a, r) => {
                if (!a[r.grouping_key]) { a[r.grouping_key] = { k: r.grouping_key, d: r.domain, c: 0, p: 0, e: 0, de: 0, er: 0, models: new Set() }; }
                a[r.grouping_key].c++; a[r.grouping_key].models.add(r.model); a[r.grouping_key].d = r.domain;
                if (r.compliance === 'COMPLETE') a[r.grouping_key].p++; else if (r.compliance === 'EVASIVE') a[r.grouping_key].e++; else if (r.compliance === 'DENIAL') a[r.grouping_key].de++; else if (r.compliance === 'ERROR') a[r.grouping_key].er++;
                return a;
            }, {});
            const res = Object.values(s).map(i => ({ grouping_key: i.k, domain: i.d, num_responses: i.c, num_models: i.models.size, pct_complete_overall: i.c > 0 ? (i.p / i.c * 100) : 0, pct_evasive: i.c > 0 ? (i.e / i.c * 100) : 0, pct_denial: i.c > 0 ? (i.de / i.c * 100) : 0, pct_error: i.c > 0 ? (i.er / i.c * 100) : 0, }));
            res.sort((a, b) => a.grouping_key.localeCompare(b.grouping_key));
            return res;
        },
        get selectedModelQuestionSummary() {
            if (!this.selectedModel || !this.isDataLoaded) return [];
            const f = this.allResponses.filter(r => r.model === this.selectedModel && (this.activeModelDomainFilters.length === 0 || this.activeModelDomainFilters.includes(r.domain)) && (this.activeModelVariationFilters.length === 0 || this.activeModelVariationFilters.includes(r.variation)) && (this.activeModelComplianceFilters.length === 0 || this.activeModelComplianceFilters.includes(r.compliance)));
            const s = f.reduce((a, r) => {
                if (!a[r.grouping_key]) { a[r.grouping_key] = { k: r.grouping_key, d: r.domain, c: 0, p: 0, e: 0, de: 0, er: 0 }; }
                a[r.grouping_key].c++; a[r.grouping_key].d = r.domain;
                if (r.compliance === 'COMPLETE') a[r.grouping_key].p++; else if (r.compliance === 'EVASIVE') a[r.grouping_key].e++; else if (r.compliance === 'DENIAL') a[r.grouping_key].de++; else if (r.compliance === 'ERROR') a[r.grouping_key].er++;
                return a;
            }, {});
            const res = Object.values(s).map(i => ({ grouping_key: i.k, domain: i.d, num_responses: i.c, pct_complete: i.c > 0 ? (i.p / i.c * 100) : 0, pct_evasive: i.c > 0 ? (i.e / i.c * 100) : 0, pct_denial: i.c > 0 ? (i.de / i.c * 100) : 0, pct_error: i.c > 0 ? (i.er / i.c * 100) : 0, }));
            res.sort((a, b) => a.grouping_key.localeCompare(b.grouping_key));
            return res;
        },
        get selectedModelData() { if (!this.selectedModel || !this.isDataLoaded) return null; return this.modelSummary.find(m => m.model === this.selectedModel) || null; },
        get selectedQuestionThemeData() { if (!this.selectedGroupingKey || !this.isDataLoaded) return null; const firstRecord = this.allResponses.find(r => r.grouping_key === this.selectedGroupingKey); if (!firstRecord) return null; const domain = firstRecord.domain; const responsesForTheme = this.allResponses .filter(r => r.grouping_key === this.selectedGroupingKey) .sort((a,b) => a.model.localeCompare(b.model) || parseInt(a.variation) - parseInt(b.variation)); return { grouping_key: this.selectedGroupingKey, domain: domain, responses: responsesForTheme }; },
        get selectedQuestionThemeModelSummary() { if (!this.selectedQuestionThemeData || !this.selectedQuestionThemeData.responses) return []; const summary = this.selectedQuestionThemeData.responses.reduce((acc, r) => { if (!acc[r.model]) acc[r.model] = { model: r.model, anchor_id: r.anchor_id, count: 0, complete_count: 0 }; acc[r.model].count++; if (r.compliance === 'COMPLETE') acc[r.model].complete_count++; acc[r.model].anchor_id = r.anchor_id; return acc; }, {}); return Object.values(summary).map(s => ({ model: s.model, anchor_id: s.anchor_id, count: s.count, pct_complete: s.count > 0 ? (s.complete_count / s.count * 100) : 0, })).sort((a,b) => a.model.localeCompare(b.model)); },
        get selectedModelDetailedStats() { if (!this.selectedModel || !this.isDataLoaded) { return { overall: { count: 0, complete_count: 0, pct_complete: 0, counts: {}, percentages: {} }, by_domain: [], by_variation: [], by_domain_sorted: [] }; } const modelResponses = this.allResponses.filter(r => r.model === this.selectedModel); const overall = { count: 0, complete_count: 0, counts: {}, percentages: {} }; const by_domain = {}; const by_variation = {}; this.complianceOrder.forEach(level => { overall.counts[level] = 0; }); this.availableFilters.domains.forEach(d => { by_domain[d] = { domain: d, count: 0, complete_count: 0 }; }); this.availableFilters.variations.forEach(v => { by_variation[v] = { variation: v, count: 0, complete_count: 0 }; }); for (const r of modelResponses) { overall.count++; if(this.complianceOrder.includes(r.compliance)) overall.counts[r.compliance]++; else overall.counts['UNKNOWN']++; if (r.compliance === 'COMPLETE') overall.complete_count++; if (!by_domain[r.domain]) by_domain[r.domain] = { domain: r.domain, count: 0, complete_count: 0 }; by_domain[r.domain].count++; if (r.compliance === 'COMPLETE') by_domain[r.domain].complete_count++; if (!by_variation[r.variation]) by_variation[r.variation] = { variation: r.variation, count: 0, complete_count: 0 }; by_variation[r.variation].count++; if (r.compliance === 'COMPLETE') by_variation[r.variation].complete_count++; } overall.pct_complete = overall.count > 0 ? (overall.complete_count / overall.count * 100) : 0; this.complianceOrder.forEach(level => { overall.percentages[level] = overall.count > 0 ? (overall.counts[level] / overall.count * 100) : 0; }); const domain_results = Object.values(by_domain).map(d => ({ ...d, pct_complete: d.count > 0 ? (d.complete_count / d.count * 100) : 0 }));
            const variation_results = Object.values(by_variation).map(v => ({ ...v, pct_complete: v.count > 0 ? (v.complete_count / v.count * 100) : 0 })).sort((a,b) => parseInt(a.variation) - parseInt(b.variation)); const domain_results_sorted = [...domain_results].sort((a,b) => Number(a.pct_complete) - Number(b.pct_complete)); return { overall: overall, by_domain: domain_results, by_variation: variation_results, by_domain_sorted: domain_results_sorted }; },

        // --- Methods ---
        async initialize() { console.log('Alpine initializing...'); this.isLoading = true; this.loadingMessage = 'Fetching data...'; this.errorMessage = null; this.isDataLoaded = false; this.parseHash(); this.setupWatchers(); this.loadData().then(() => { this.isDataLoaded = true; this.parseHash(true); this.$nextTick(() => { this.isLoading = false; this.initializeTableForView(this.currentView); }); }).catch(e => { console.error("Init error:", e); this.errorMessage = `Failed load: ${e.message}`; this.isLoading = false; }).finally(() => { this.loadingMessage = ''; console.log("Data loading attempt finished."); }); window.addEventListener('hashchange', () => this.parseHash()); },
        async loadData() { this.loadingMessage = 'Fetching data...'; const r=await fetch('us_hard_data.json.gz',{headers:{'Accept-Encoding':'gzip'}}); if (!r.ok) throw new Error(`HTTP ${r.status}`); this.loadingMessage = 'Decompressing...'; await this.$nextTick(); const c=await r.arrayBuffer(); const d=pako.inflate(new Uint8Array(c),{to:'string'}); this.loadingMessage = 'Parsing...'; await this.$nextTick(); const j=JSON.parse(d); this.allResponses=j.records||[]; this.complianceOrder=j.complianceOrder||[]; if(this.allResponses.length===0) throw new Error("No records."); this.availableFilters.models=[...new Set(this.allResponses.map(r=>r.model))].sort(); this.availableFilters.domains=[...new Set(this.allResponses.map(r=>r.domain))].sort(); this.availableFilters.variations=[...new Set(this.allResponses.map(r=>r.variation))].sort((a,b)=>parseInt(a)-parseInt(b)); this.availableFilters.grouping_keys=[...new Set(this.allResponses.map(r=>r.grouping_key))].sort(); console.log("Data loaded."); },
        parseHash(forceUpdate = false) {
            console.log("Parsing Hash:", location.hash);
            const h = location.hash.slice(1);
            const parts = h.split('#');
            const pathParts = parts[0].split('/').filter(Boolean);
            const anchor = parts[1] || null;
            let v = 'about';
            let m = null;
            let k = null;
            if (pathParts[0] === 'overview') { v = 'overview'; }
            else if (pathParts[0] === 'model' && pathParts[1]) {
                const pM = decodeURIComponent(pathParts[1]);
                if (!this.isDataLoaded || this.availableFilters.models.includes(pM)) { v = 'model_detail'; m = pM; }
                else { console.warn(`Model '${pM}' invalid.`); this.navigate('about', true); return; }
            } else if (pathParts[0] === 'questions') {
                if (pathParts[1]) {
                    const pK = decodeURIComponent(pathParts[1]);
                    if (!this.isDataLoaded || this.availableFilters.grouping_keys.includes(pK)) { v = 'question_theme_detail'; k = pK; }
                    else { console.warn(`Key '${pK}' invalid.`); this.navigate('question_themes', true); return; }
                } else { v = 'question_themes'; }
            }

            if (forceUpdate || v !== this.currentView || m !== this.selectedModel || k !== this.selectedGroupingKey) {
                console.log(`State update: view=${v}, model=${m}, key=${k}`);
                const previousView = this.currentView;
                this.currentView = v;
                if (v !== 'model_detail') this.selectedModel = null;
                if (v !== 'question_theme_detail') this.selectedGroupingKey = null;
                this.selectedModel = m;
                this.selectedGroupingKey = k;
                if (v === 'model_detail' && m !== this.selectedModel) this.clearModelDetailFilters(false);
                if (this.isDataLoaded) {
                    setTimeout(() => {
                        this.destroyAllTables();
                        console.log("Attempting table init for view:", this.currentView);
                        try {
                            if (this.currentView === 'overview') this.initOverviewTable();
                            if (this.currentView === 'question_themes') this.initQuestionThemesTable();
                            if (this.currentView === 'model_detail') this.initModelDetailTable();
                        } catch (e) {
                            console.error("Error initializing table:", e);
                            this.errorMessage = "Error rendering table.";
                        }
                        if (anchor && this.currentView === 'question_theme_detail') this.smoothScroll('#' + anchor);
                    }, 50);
                }
            } else {
                console.log("State matches hash.");
                if (anchor && this.currentView === 'question_theme_detail') this.smoothScroll('#' + anchor);
            }
        },
        navigate(view, replaceHistory = false, selectionKey = null, anchor = null) { let h='#/about'; if(view==='overview'){h='#/overview';} else if(view==='question_themes'){h='#/questions';} else if(view==='model_detail'){const m=selectionKey||this.selectedModel; if(m)h=`#/model/${encodeURIComponent(m)}`;else return;} else if(view==='question_theme_detail'){const k=selectionKey||this.selectedGroupingKey; if(k)h=`#/questions/${encodeURIComponent(k)}`;else return;} else if(view!=='about'){console.warn("Invalid view:",view);return;} const nH=anchor?`${h}#${anchor}`:h; if(location.hash !== nH){console.log(`URL Update: ${nH} (repl:${replaceHistory})`); if(replaceHistory)history.replaceState(null,'',nH); else history.pushState(null,'',nH); this.parseHash();} else if(replaceHistory||anchor){console.log("Same hash nav, ensuring redraw/scroll."); setTimeout(()=>{if(this.isDataLoaded)this.initializeTableForView(this.currentView); if(anchor && view === 'question_theme_detail')this.smoothScroll('#'+anchor);},50);} },
        selectModel(modelName) { this.selectedModel = modelName; this.clearModelDetailFilters(false); this.navigate('model_detail', false, modelName); },
        selectQuestionTheme(groupingKey, modelAnchorId = null) { this.selectedGroupingKey = groupingKey; this.navigate('question_theme_detail', false, groupingKey, modelAnchorId); },
        clearModelDetailFilters(doNavigate = true) { this.activeModelDomainFilters = []; this.activeModelVariationFilters = []; this.activeModelComplianceFilters = []; if(doNavigate) this.navigate('model_detail', true); },

        // --- Tabulator Initializers ---
        initOverviewTable() {
            const t = document.getElementById("overview-table");
            if (!t || this.currentView !== 'overview') return;
            this.destroyTable(this.overviewTable);
            const d = this.modelSummary;
            console.log("Init Overview, #", d.length);
            this.overviewTable = new Tabulator(t, {
                data: [...d], layout: "fitDataFill", height: "60vh", placeholder: "No models.", selectable: false, columns: [
                    { title: "Model", field: "model", widthGrow: 2, frozen: true, headerFilter: "input", cellClick: (e, c) => this.selectModel(c.getRow().getData().model), cssClass: "clickable-cell" },
                    { title: "# Resp", field: "num_responses", width: 90, hozAlign: "right", sorter: "number" },
                    { title: "% Comp", field: "pct_complete_overall", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.COMPLETE } }, // Updated formatter
                    { title: "% Evas", field: "pct_evasive", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.EVASIVE } },
                    { title: "% Deny", field: "pct_denial", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.DENIAL } },
                    { title: "% Err", field: "pct_error", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.ERROR } },
                ],
            });
        },
        initQuestionThemesTable() {
            const t = document.getElementById("question-themes-table");
            if (!t || this.currentView !== 'question_themes') return;
            this.destroyTable(this.questionThemesTable);
            const d = this.questionThemeSummary;
            console.log("Init Q Themes, #", d.length);
            this.questionThemesTable = new Tabulator(t, {
                data: [...d], layout: "fitDataFill", height: "60vh", placeholder: "No themes found.", selectable: false, columns: [
                    { title: "Grouping Key", field: "grouping_key", widthGrow: 2, frozen: true, headerFilter: "input", cellClick: (e, c) => this.selectQuestionTheme(c.getRow().getData().grouping_key), cssClass: "clickable-cell" },
                    { title: "Domain", field: "domain", width: 150, headerFilter: "select", headerFilterParams: { values: ["", ...this.availableFilters.domains] } },
                    { title: "Distinct Models", field: "num_models", width: 100, hozAlign: "right", sorter: "number" },
                    { title: "# Resp", field: "num_responses", width: 90, hozAlign: "right", sorter: "number" },
                    { title: "% Complete", field: "pct_complete_overall", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.COMPLETE } }, // Updated formatter
                    { title: "% Evas", field: "pct_evasive", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.EVASIVE } },
                    { title: "% Deny", field: "pct_denial", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.DENIAL } },
                    { title: "% Err", field: "pct_error", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.ERROR } }
                ],
            });
        },
        initModelDetailTable() {
            const t = document.getElementById("model-detail-table");
            if (!t || this.currentView !== 'model_detail' || !this.selectedModel) return;
            this.destroyTable(this.modelDetailTable);
            const d = this.selectedModelQuestionSummary;
            console.log(`Init Model Detail ${this.selectedModel}, #`, d.length);
            this.modelDetailTable = new Tabulator(t, {
                data: [...d], layout: "fitDataFill", height: "60vh", placeholder: "No Qs matching filters.", selectable: false, columns: [
                    { title: "Grouping Key", field: "grouping_key", widthGrow: 2, frozen: true, headerFilter: "input", cellClick: (e, c) => this.selectQuestionTheme(c.getRow().getData().grouping_key, `response-${generateSafeId(this.selectedModel)}`), cssClass: "clickable-cell" },
                    { title: "Domain", field: "domain", width: 150, headerFilter: "select", headerFilterParams: { values: ["", ...this.availableFilters.domains.filter(dm => d.some(q => q.domain === dm))] } },
                    { title: "# Resp", field: "num_responses", width: 90, hozAlign: "right", sorter: "number" },
                    { title: "% Complete", field: "pct_complete", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.COMPLETE } }, // Updated formatter
                    { title: "% Evas", field: "pct_evasive", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.EVASIVE } },
                    { title: "% Deny", field: "pct_denial", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.DENIAL } },
                    { title: "% Err", field: "pct_error", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.ERROR } }
                ],
            });
        },
        initializeTableForView(view, anchor = null) { if (!this.isDataLoaded) { console.log("Deferring table init, data not loaded."); return; } console.log(`Initializing table for view: ${view}`); this.destroyAllTables(); try { if (view === 'overview') this.initOverviewTable(); else if (view === 'question_themes') this.initQuestionThemesTable(); else if (view === 'model_detail') this.initModelDetailTable(); if (anchor && view === 'question_theme_detail') { setTimeout(() => this.smoothScroll('#' + anchor), 150); } } catch (error) { console.error(`Error initializing table for view ${view}:`, error); this.errorMessage = `Error rendering ${view} table.`; } },
        destroyTable(tableInstance) { if (tableInstance) { try { tableInstance.destroy(); } catch (e) {} } return null; },
        destroyAllTables() { this.overviewTable = this.destroyTable(this.overviewTable); this.questionThemesTable = this.destroyTable(this.questionThemesTable); this.modelDetailTable = this.destroyTable(this.modelDetailTable); },

        // --- Watchers ---
        setupWatchers() {
            this.$watch('activeModelDomainFilters', () => { if (this.currentView === 'model_detail') this.navigate('model_detail', true); });
            this.$watch('activeModelVariationFilters', () => { if (this.currentView === 'model_detail') this.navigate('model_detail', true); });
            this.$watch('activeModelComplianceFilters', () => { if (this.currentView === 'model_detail') this.navigate('model_detail', true); });
        },

        // --- Helper Methods ---
        getVariationDescription(variation) { return VARIATION_MAP[String(variation)] || `Type ${variation || 'N/A'}`; },
        renderMarkdown(text) { if (!text) return ''; try { const clean = DOMPurify.sanitize(marked.parse(text), { USE_PROFILES: { html: true } }); return clean; } catch (e) { console.error("Markdown error:", e); return `<pre>Err:\n${sanitize(text)}</pre>`; } },
        smoothScroll(selector) { const el = document.querySelector(selector); if(el){ console.log("Scrolling to:", selector); setTimeout(() => el.scrollIntoView({behavior:'smooth',block:'start'}), 150); } else console.warn("Smooth scroll target not found:",selector); },
        getComplianceBoxStyle(percent) { let c=COMPLIANCE_COLORS.UNKNOWN; if(typeof percent==='number'&&!isNaN(percent)){c=percent>=90?COMPLIANCE_COLORS.COMPLETE:(percent>=25?COMPLIANCE_COLORS.EVASIVE:COMPLIANCE_COLORS.DENIAL);} const t=(c===COMPLIANCE_COLORS.EVASIVE||c===COMPLIANCE_COLORS.UNKNOWN)?'#333':'white'; return `background-color:${c};color:${t};`; },
        groupResponsesByModel(responses) { if (!responses) return []; const g = responses.reduce((a, r) => { if (!a[r.model]) { a[r.model] = { model: r.model, responses: [] }; } a[r.model].responses.push(r); return a; }, {}); return Object.values(g).sort((a,b) => a.model.localeCompare(b.model)); },
        generateOpenRouterLink(modelName, prompt) {
            const baseUrl = "https://openrouter.ai/chat";
            const safeModelName = modelName || "";
            const modelsParam = `${safeModelName}`;
            const messageParam = encodeURIComponent(prompt || "");
            return `${baseUrl}?models=${modelsParam}&message=${messageParam}`;
        },
        init() { /* Called from x-init */ }

    }));
});

// --- Standalone Helper Functions ---
function complianceFormatter(cell, formatterParams, onRendered) { const value = cell.getValue(); if (value === null || value === undefined) return ""; const color = COMPLIANCE_COLORS[value] || COMPLIANCE_COLORS['UNKNOWN']; const textColor = (value === 'EVASIVE' || value === 'UNKNOWN') ? '#333' : 'white'; const span = document.createElement('span'); span.textContent = value; span.classList.add('compliance-label'); span.style.backgroundColor = color; span.style.color = textColor; return span; }
function truncateText(text, maxLength = 100) { if (!text) return ""; text = String(text); return text.length <= maxLength ? text : text.substring(0, maxLength) + "..."; }
function formatDate(dateString) { if (!dateString) return "N/A"; try { return new Date(dateString).toLocaleString('sv-SE'); } catch (e) { return dateString; } }
function sanitize(str) { if (str === null || str === undefined) return ''; const temp = document.createElement('div'); temp.textContent = String(str); return temp.innerHTML; }
function generateSafeId(text) { if (!text) return 'id'; let s = String(text).toLowerCase().replace(/[^\w\s-]/g, '').replace(/\s+/g, '-').replace(/-+/g, '-'); return s.replace(/^-+|-+$/g, '') || "id"; }

// Formatter for percentage cells showing bar + text
function percentWithBgBarFormatter(cell, formatterParams, onRendered) {
    const value = cell.getValue();
    if (typeof value !== 'number' || isNaN(value)) return "";

    const color = formatterParams.color || COMPLIANCE_COLORS.UNKNOWN;
    // Determine default text color based on background for contrast
    let textColorClass = (color === COMPLIANCE_COLORS.EVASIVE || color === COMPLIANCE_COLORS.UNKNOWN || color === COMPLIANCE_COLORS.COMPLETE) ? 'dark-text' : 'light-text';

    // Override to dark text if value is low, as background color won't be prominent
    if (value < 10) {
        textColorClass = 'dark-text';
    }

    const container = document.createElement('div');
    container.classList.add('percent-bar-container');

    const bar = document.createElement('div');
    bar.classList.add('percent-bar-bg');
    bar.style.width = `${value}%`;
    bar.style.backgroundColor = color;

    const text = document.createElement('span');
    text.classList.add('percent-bar-text', textColorClass);
    text.textContent = value.toFixed(1) + '%';

    container.appendChild(bar);
    container.appendChild(text);

    return container;
}
