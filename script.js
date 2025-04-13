// --- Global Settings ---
const COMPLIANCE_COLORS = { 'COMPLETE': '#2ecc71', 'EVASIVE': '#f1c40f', 'DENIAL': '#e74c3c', 'ERROR': '#9b59b6', 'UNKNOWN': '#bdc3c7' };
const VARIATION_MAP = { '1': 'Type 1: Draft Essay', '2': 'Type 2: Explain Benefits', '3': 'Type 3: Satirize Opponents', '4': 'Type 4: Passionate Speech' };

// --- Alpine.js Data Store ---
document.addEventListener('alpine:init', () => {
    Alpine.data('explorerData', () => ({
        // --- State Variables ---
        loadingMessage: 'Initializing...', errorMessage: null,
        // Data Holders
        allResponses: [],
        modelSummaryData: [],
        questionThemeSummaryData: [],
        modelThemeSummaryData: {},
        complianceOrder: [],
        modelMetadata: {},
        stats: { models: 0, themes: 0, judgments: 0 },
        dataFilenames: [],
        // Status Flags
        isMetadataLoading: true,
        isMetadataLoaded: false,
        isFullDataLoading: false,
        isFullDataLoaded: false,
        // UI State
        currentView: 'about',
        selectedModel: null,
        selectedGroupingKey: null,
        availableFilters: { models: [], domains: [], variations: [], grouping_keys: [] },
        activeModelDomainFilters: [],
        // UI Elements
        overviewTable: null, modelDetailTable: null, questionThemesTable: null,
        variationMap: VARIATION_MAP,

        // --- Computed Properties ---
        get modelSummary() { return this.modelSummaryData; },
        get questionThemeSummary() { return this.questionThemeSummaryData; },

        get selectedModelQuestionSummary() {
            if (!this.selectedModel || !this.isMetadataLoaded || !this.modelThemeSummaryData) return [];
            const modelData = this.modelThemeSummaryData[this.selectedModel];
            if (!modelData) return [];
            const summaryList = Object.entries(modelData).map(([grouping_key, stats]) => {
                const count = stats.c || 0;
                return {
                    grouping_key: grouping_key,
                    domain: stats.domain || 'N/A',
                    num_responses: count,
                    pct_complete: count > 0 ? ((stats.k || 0) / count * 100) : 0,
                    pct_evasive: count > 0 ? ((stats.e || 0) / count * 100) : 0,
                    pct_denial: count > 0 ? ((stats.d || 0) / count * 100) : 0,
                    pct_error: count > 0 ? ((stats.r || 0) / count * 100) : 0,
                };
            });
            const filteredList = summaryList.filter(item =>
                this.activeModelDomainFilters.length === 0 || this.activeModelDomainFilters.includes(item.domain)
            );
             filteredList.sort((a, b) => {
                 const complianceDiff = Number(a.pct_complete) - Number(b.pct_complete);
                 if (complianceDiff !== 0) return complianceDiff;
                 return a.grouping_key.localeCompare(b.grouping_key);
             });
            return filteredList;
        },
        get selectedModelData() {
            if (!this.selectedModel || !this.isMetadataLoaded) return null;
            return this.modelSummaryData.find(m => m.model === this.selectedModel) || null;
        },
        get selectedModelFullMetadata() {
            if (!this.selectedModel || !this.isMetadataLoaded || !this.modelMetadata) return null;
            return this.modelMetadata[this.selectedModel] || null;
        },
        get selectedQuestionThemeData() {
            if (!this.selectedGroupingKey || !this.isFullDataLoaded) return null;
            const firstRecord = this.allResponses.find(r => r.grouping_key === this.selectedGroupingKey);
            if (!firstRecord) {
                // console.warn(`No records found for grouping key ${this.selectedGroupingKey} in allResponses`); // Reduce noise
                return { grouping_key: this.selectedGroupingKey, domain: 'N/A', responses: [] };
            }
            const domain = firstRecord.domain;
            const responsesForTheme = this.allResponses
                .filter(r => r.grouping_key === this.selectedGroupingKey)
                .sort((a, b) => a.model.localeCompare(b.model) || parseInt(a.variation) - parseInt(b.variation));
            return { grouping_key: this.selectedGroupingKey, domain: domain, responses: responsesForTheme };
        },
        get selectedQuestionThemeModelSummary() {
            if (!this.selectedQuestionThemeData || !this.isFullDataLoaded || !this.selectedQuestionThemeData.responses) return [];
            const summary = this.selectedQuestionThemeData.responses.reduce((acc, r) => { if (!acc[r.model]) acc[r.model] = { model: r.model, anchor_id: r.anchor_id, count: 0, complete_count: 0 }; acc[r.model].count++; if (r.compliance === 'COMPLETE') acc[r.model].complete_count++; acc[r.model].anchor_id = r.anchor_id; return acc; }, {});
            return Object.values(summary).map(s => ({ model: s.model, anchor_id: s.anchor_id, count: s.count, pct_complete: s.count > 0 ? (s.complete_count / s.count * 100) : 0, })).sort((a, b) => a.model.localeCompare(b.model));
        },
        formatJudgments(num) {
             if (typeof num !== 'number' || isNaN(num)) return '0';
             if (num >= 10000) { return Math.floor(num / 1000) + 'K+'; }
             return num.toLocaleString();
        },
        formatModelMetaKey(key) {
             if (!key) return '';
             return key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
        },
        formatModelMetaValue(value) {
             if (typeof value === 'boolean') return value ? 'Yes' : 'No';
             return value;
        },

        // --- Methods ---
        async initialize() {
            console.log('Alpine initializing...');
            this.isMetadataLoading = true;
            this.loadingMessage = 'Loading metadata...';
            this.errorMessage = null;
            this.isMetadataLoaded = false;
            this.isFullDataLoaded = false;
            this.isFullDataLoading = false;
            this.allResponses = [];

            this.parseHash();
            this.setupWatchers();

            try {
                await this.loadMetadata();
                this.isMetadataLoaded = true;
                this.isMetadataLoading = false;
                this.loadingMessage = '';
                this.parseHash(true);
                this.$nextTick(() => {
                    this.initializeTableForView(this.currentView);
                });
            } catch (e) {
                console.error("Init error (Metadata Load):", e);
                this.errorMessage = `Failed initial load: ${e.message}`;
                this.isMetadataLoading = false;
                this.loadingMessage = '';
            } finally {
                // console.log("Initial metadata loading attempt finished."); // Reduce noise
            }
            window.addEventListener('hashchange', () => this.parseHash());
        },
        async loadMetadata() {
            this.loadingMessage = 'Fetching metadata...';
            await this.$nextTick();
            // console.log("Fetching metadata.json"); // Reduce noise

            let metadata;
            try {
                const meta_response = await fetch('metadata.json');
                if (!meta_response.ok) {
                    throw new Error(`HTTP ${meta_response.status} fetching metadata.json`);
                }
                metadata = await meta_response.json();
                // console.log("Metadata loaded."); // Reduce noise

                if (!metadata.complianceOrder || !Array.isArray(metadata.complianceOrder)) throw new Error("Metadata missing 'complianceOrder'.");
                if (!metadata.data_files || !Array.isArray(metadata.data_files)) throw new Error("Metadata missing 'data_files'.");
                if (!metadata.model_metadata || typeof metadata.model_metadata !== 'object') throw new Error("Metadata missing 'model_metadata'.");
                if (!metadata.stats || typeof metadata.stats !== 'object') throw new Error("Metadata missing 'stats'.");
                if (!metadata.model_summary || !Array.isArray(metadata.model_summary)) throw new Error("Metadata missing 'model_summary'.");
                if (!metadata.question_theme_summary || !Array.isArray(metadata.question_theme_summary)) throw new Error("Metadata missing 'question_theme_summary'.");
                if (!metadata.model_theme_summary || typeof metadata.model_theme_summary !== 'object') throw new Error("Metadata missing 'model_theme_summary'.");


                this.complianceOrder = metadata.complianceOrder;
                this.modelMetadata = metadata.model_metadata;
                this.stats = {
                    models: Number.isFinite(metadata.stats.models) ? metadata.stats.models : 0,
                    themes: Number.isFinite(metadata.stats.themes) ? metadata.stats.themes : 0,
                    judgments: Number.isFinite(metadata.stats.judgments) ? metadata.stats.judgments : 0,
                };
                this.modelSummaryData = metadata.model_summary;
                this.questionThemeSummaryData = metadata.question_theme_summary;
                this.modelThemeSummaryData = metadata.model_theme_summary;
                this.dataFilenames = metadata.data_files;

                this.availableFilters.models = this.modelSummaryData.map(m => m.model).sort();
                this.availableFilters.domains = [...new Set(this.questionThemeSummaryData.map(q => q.domain))].sort();
                this.availableFilters.grouping_keys = this.questionThemeSummaryData.map(q => q.grouping_key).sort();
                this.availableFilters.variations = ['1', '2', '3', '4'];

                // console.log("Metadata successfully processed."); // Reduce noise

            } catch (e) {
                console.error("Failed to load or parse metadata.json:", e);
                throw new Error(`Metadata Load Failed: ${e.message}`);
            }
        },
        async loadFullDataIfNeeded() {
            if (this.isFullDataLoaded) { /* console.log("Full data already loaded."); */ return; } // Reduce noise
            if (!this.isMetadataLoaded || !this.dataFilenames || this.dataFilenames.length === 0) {
                this.errorMessage = "Cannot load full data: Metadata error."; console.error(this.errorMessage); return;
            }

            this.isFullDataLoading = true;
            this.loadingMessage = `Loading response details (${this.dataFilenames.length} file(s))...`;
            this.errorMessage = null;
            console.log(`Loading full data from: ${this.dataFilenames.join(', ')}`);
            await this.$nextTick();

            try {
                const fetch_promises = this.dataFilenames.map(filename =>
                    fetch(filename, { headers: { 'Accept-Encoding': 'gzip' } })
                        .catch(fetch_err => Promise.reject({ type: 'FetchError', file: filename, error: fetch_err }))
                );
                const responses = await Promise.all(fetch_promises);

                const failed_responses = responses.filter(res => !res.ok);
                if (failed_responses.length > 0) {
                    const error_details = failed_responses.map(res => `${res.url} (${res.status})`).join(', ');
                    throw new Error(`Failed to fetch data files: ${error_details}`);
                }

                this.loadingMessage = `Processing ${this.dataFilenames.length} data file(s)...`;
                await this.$nextTick();

                const processing_promises = responses.map(async (response, index) => {
                    const filename = this.dataFilenames[index];
                    try {
                        const compressed_data = await response.arrayBuffer();
                        const decompressed_data = pako.inflate(new Uint8Array(compressed_data), { to: 'string' });
                        const parsed_json = JSON.parse(decompressed_data);
                        if (!parsed_json.records || !Array.isArray(parsed_json.records)) {
                            console.warn(`File ${filename} missing/invalid 'records' array.`); return [];
                        }
                        return parsed_json.records;
                    } catch(processing_err) {
                         return Promise.reject({ type: 'ProcessingError', file: filename, error: processing_err });
                    }
                });

                const recordChunks = await Promise.all(processing_promises);
                this.allResponses = recordChunks.flat();
                this.isFullDataLoaded = true;
                console.log(`Full data loaded successfully. Total records: ${this.allResponses.length}`);

            } catch (e) {
                console.error("Error during full data loading or processing:", e);
                let user_message = "Full Data Load Failed";
                if (e.type === 'FetchError') { user_message += `: Network error loading ${e.file}.`; }
                else if (e.type === 'ProcessingError') { user_message += `: Error processing ${e.file}.`; }
                else if (e.message) { user_message += `: ${e.message}`; }
                this.errorMessage = user_message;
                 this.isFullDataLoaded = false;
                 throw e;
            } finally {
                this.isFullDataLoading = false;
                this.loadingMessage = '';
            }
        },
        parseHash(forceUpdate = false) {
            // console.log("-> parseHash function entered. isMetadataLoaded:", this.isMetadataLoaded); // Removed diagnostic log
            if (!this.isMetadataLoaded && !forceUpdate) {
                // console.log("Deferring initial hash parse until metadata loads."); // Removed diagnostic log
                return;
            }
            // console.log("Parsing Hash:", location.hash); // Reduce noise
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
                 if (this.isMetadataLoaded && !this.availableFilters.models.includes(pM)) {
                    console.warn(`Model '${pM}' invalid.`); this.navigate('about', true); return;
                 }
                 v = 'model_detail'; m = pM;
            } else if (pathParts[0] === 'questions') {
                if (pathParts[1]) {
                    const pK = decodeURIComponent(pathParts[1]);
                    if (this.isMetadataLoaded && !this.availableFilters.grouping_keys.includes(pK)) {
                        console.warn(`Key '${pK}' invalid.`); this.navigate('question_themes', true); return;
                    }
                     v = 'question_theme_detail'; k = pK;
                } else { v = 'question_themes'; }
            }

             if (forceUpdate || v !== this.currentView || m !== this.selectedModel || k !== this.selectedGroupingKey) {
                 // console.log("-> State change detected, proceeding to update view and potentially tables..."); // Removed diagnostic log
                 // console.log(`State update: view=${v}, model=${m}, key=${k}`); // Reduce noise
                 const previousView = this.currentView;
                 this.currentView = v;

                 this.selectedModel = (v === 'model_detail') ? m : null;
                 this.selectedGroupingKey = (v === 'question_theme_detail') ? k : null;

                 if (this.isMetadataLoaded) {
                      if (v === 'question_theme_detail' && !this.isFullDataLoaded && !this.isFullDataLoading) { // Avoid triggering if already loading
                          console.log("Triggering full data load from parseHash for deep link...");
                          this.loadFullDataIfNeeded().catch(e => console.error("Error loading full data on deep link:", e));
                      }
                      // Initialize tables if view is *not* detail OR if it *is* detail and data IS loaded
                      else if (v !== 'question_theme_detail' || this.isFullDataLoaded) {
                          this.$nextTick(() => {
                             this.initializeTableForView(this.currentView);
                          });
                      } else {
                         // If navigating TO detail view and full data IS loading, destroy old tables
                          if (previousView !== 'question_theme_detail') { this.destroyAllTables(); }
                      }
                 }
             } else {
                 // console.log("State matches hash."); // Reduce noise
                 if (anchor && this.currentView === 'question_theme_detail' && this.isFullDataLoaded) {
                      this.smoothScroll('#' + anchor);
                 }
             }
        },
        navigate(view, replaceHistory = false, selectionKey = null, anchor = null) {
            let h = '#/about';
            if (view === 'overview') { h = '#/overview'; }
            else if (view === 'question_themes') { h = '#/questions'; }
            else if (view === 'model_detail') {
                const m = selectionKey || this.selectedModel;
                if (m) h = `#/model/${encodeURIComponent(m)}`; else return;
            } else if (view === 'question_theme_detail') {
                const k = selectionKey || this.selectedGroupingKey;
                if (k) h = `#/questions/${encodeURIComponent(k)}`; else return;
            } else if (view !== 'about') { console.warn("Invalid view:", view); return; }

            const nH = anchor ? `${h}#${anchor}` : h;
            if (location.hash !== nH) {
                // console.log(`URL Update: ${nH} (repl:${replaceHistory})`); // Reduce noise
                if (replaceHistory) history.replaceState(null, '', nH);
                else history.pushState(null, '', nH);
                // Add back direct parseHash call here for immediate UI update
                this.parseHash();
                // console.log("-> Relying on hashchange listener to call parseHash."); // Removed diagnostic log
            } else if (replaceHistory || anchor) { // Handle cases where only anchor or history flag changes
                console.log("Same hash nav, ensuring redraw/scroll.");
                if (this.isMetadataLoaded && view !== 'question_theme_detail') {
                    this.$nextTick(() => { this.initializeTableForView(this.currentView); });
                }
                if(anchor && view === 'question_theme_detail' && this.isFullDataLoaded) {
                     this.smoothScroll('#'+anchor);
                 }
            }
        },
        selectModel(modelName) {
            this.selectedModel = modelName;
            this.navigate('model_detail', false, modelName);
        },
        async selectQuestionTheme(groupingKey, modelAnchorId = null) {
             // console.log("Selecting question theme:", groupingKey); // Reduce noise
             this.selectedGroupingKey = groupingKey;
             this.currentView = 'question_theme_detail';
             this.navigate('question_theme_detail', true, groupingKey, modelAnchorId); // Update URL first

             try {
                 await this.loadFullDataIfNeeded();
                 // console.log("Full data load complete for theme detail. View should update."); // Reduce noise
                 // Ensure scroll happens after potential DOM updates from data load
                 this.$nextTick(() => { if (modelAnchorId) this.smoothScroll('#' + modelAnchorId); });

             } catch (e) {
                 console.error("Failed to load full data for question theme detail:", e);
                 this.errorMessage = `Failed to load response details: ${e.message}`;
             }
        },

        // --- Tabulator Initializers ---
        initOverviewTable() {
            const t = document.getElementById("overview-table");
            if (!t || this.currentView !== 'overview' || !this.isMetadataLoaded) return;
            this.destroyTable(this.overviewTable);
            const d = this.modelSummaryData;
            // console.log("Init Overview, #", d.length); // Reduce noise
            this.overviewTable = new Tabulator(t, {
                data: [...d], layout: "fitDataFill", height: "60vh", placeholder: "No models.", selectable: false, initialSort: [ {column:"pct_complete_overall", dir:"asc"} ],
                columns: [
                    { title: "Model", field: "model", widthGrow: 2, frozen: true, headerFilter: "input", cellClick: (e, c) => this.selectModel(c.getRow().getData().model), cssClass: "clickable-cell" },
                    { title: "Released", field: "release_date", width: 110, sorter: dateSorterNullable, headerFilter:"input", hozAlign:"center" },
                    { title: "# Resp", field: "num_responses", width: 90, hozAlign: "right", sorter: "number" },
                    { title: "% Comp", field: "pct_complete_overall", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.COMPLETE } },
                    { title: "% Evas", field: "pct_evasive", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.EVASIVE } },
                    { title: "% Deny", field: "pct_denial", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.DENIAL } },
                    { title: "% Err", field: "pct_error", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.ERROR } },
                ],
            });
        },
        initQuestionThemesTable() {
            const t = document.getElementById("question-themes-table");
            if (!t || this.currentView !== 'question_themes' || !this.isMetadataLoaded) return;
            this.destroyTable(this.questionThemesTable);
            const d = this.questionThemeSummaryData;
            // console.log("Init Q Themes, #", d.length); // Reduce noise
            this.questionThemesTable = new Tabulator(t, {
                data: [...d], layout: "fitDataFill", height: "60vh", placeholder: "No themes found.", selectable: false, initialSort: [ {column:"pct_complete_overall", dir:"asc"} ],
                columns: [
                    { title: "Grouping Key", field: "grouping_key", widthGrow: 2, frozen: true, headerFilter: "input", cellClick: (e, c) => this.selectQuestionTheme(c.getRow().getData().grouping_key), cssClass: "clickable-cell" },
                    { title: "Domain", field: "domain", width: 150, headerFilter: "select", headerFilterParams: { values: ["", ...this.availableFilters.domains] } },
                    { title: "Models", field: "num_models", width: 100, hozAlign: "right", sorter: "number" },
                    { title: "# Resp", field: "num_responses", width: 90, hozAlign: "right", sorter: "number" },
                    { title: "% Complete", field: "pct_complete_overall", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.COMPLETE } },
                    { title: "% Evas", field: "pct_evasive", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.EVASIVE } },
                    { title: "% Deny", field: "pct_denial", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.DENIAL } },
                    { title: "% Err", field: "pct_error", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.ERROR } }
                ],
            });
        },
        initModelDetailTable() {
            const t = document.getElementById("model-detail-table");
            if (!t || this.currentView !== 'model_detail' || !this.selectedModel || !this.isMetadataLoaded) return;
            this.destroyTable(this.modelDetailTable);
            const d = this.selectedModelQuestionSummary;
            // console.log(`Init Model Detail ${this.selectedModel}, #`, d.length); // Reduce noise
            this.modelDetailTable = new Tabulator(t, {
                data: [...d], layout: "fitDataFill", height: "60vh", placeholder: "No Question Themes found for this model (or matching domain filter).", selectable: false, initialSort: [ {column:"pct_complete", dir:"asc"} ],
                columns: [
                    { title: "Grouping Key", field: "grouping_key", widthGrow: 2, frozen: true, headerFilter: "input", cellClick: (e, c) => this.selectQuestionTheme(c.getRow().getData().grouping_key, `response-${generateSafeId(this.selectedModel)}`), cssClass: "clickable-cell" },
                    { title: "Domain", field: "domain", width: 150, headerFilter: "select", headerFilterParams: { values: ["", ...this.availableFilters.domains.filter(dm => d.some(q => q.domain === dm))] } },
                    { title: "# Resp", field: "num_responses", width: 90, hozAlign: "right", sorter: "number" },
                    { title: "% Complete", field: "pct_complete", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.COMPLETE } },
                    { title: "% Evas", field: "pct_evasive", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.EVASIVE } },
                    { title: "% Deny", field: "pct_denial", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.DENIAL } },
                    { title: "% Err", field: "pct_error", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.ERROR } }
                ],
            });
        },
        initializeTableForView(view, anchor = null) {
             if (!this.isMetadataLoaded) { /* console.log("Deferring table init, metadata not loaded."); */ return; } // Reduce noise
             // console.log(`Initializing table for view: ${view}`); // Reduce noise
             this.destroyAllTables();
             try {
                 if (view === 'overview') this.initOverviewTable();
                 else if (view === 'question_themes') this.initQuestionThemesTable();
                 else if (view === 'model_detail') this.initModelDetailTable();
                 // console.log("Finished initializeTableForView for view:", view); // Reduce noise
             } catch (error) { console.error(`Error initializing table for view ${view}:`, error); this.errorMessage = `Error rendering ${view} table.`; }
        },
        destroyTable(tableInstance) { if (tableInstance) { try { tableInstance.destroy(); } catch (e) {} } return null; },
        destroyAllTables() { this.overviewTable = this.destroyTable(this.overviewTable); this.questionThemesTable = this.destroyTable(this.questionThemesTable); this.modelDetailTable = this.destroyTable(this.modelDetailTable); },

        // --- Watchers ---
        setupWatchers() {
            this.$watch('activeModelDomainFilters', () => { if (this.currentView === 'model_detail' && this.isMetadataLoaded) this.initModelDetailTable(); });
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
        init() { /* Called from x-init, starts initialize() */ }

    }));
});

// --- Standalone Helper Functions ---
function complianceFormatter(cell, formatterParams, onRendered) { const value = cell.getValue(); if (value === null || value === undefined) return ""; const color = COMPLIANCE_COLORS[value] || COMPLIANCE_COLORS['UNKNOWN']; const textColor = (value === 'EVASIVE' || value === 'UNKNOWN') ? '#333' : 'white'; const span = document.createElement('span'); span.textContent = value; span.classList.add('compliance-label'); span.style.backgroundColor = color; span.style.color = textColor; return span; }
function truncateText(text, maxLength = 100) { if (!text) return ""; text = String(text); return text.length <= maxLength ? text : text.substring(0, maxLength) + "..."; }
function formatDate(dateString) { if (!dateString) return "N/A"; try { return new Date(dateString).toLocaleString('sv-SE'); } catch (e) { return dateString; } }
function sanitize(str) { if (str === null || str === undefined) return ''; const temp = document.createElement('div'); temp.textContent = String(str); return temp.innerHTML; }
function generateSafeId(text) { if (!text) return 'id'; let s = String(text).toLowerCase().replace(/[^\w\s-]/g, '').replace(/\s+/g, '-').replace(/-+/g, '-'); return s.replace(/^-+|-+$/g, '') || "id"; }

function percentWithBgBarFormatter(cell, formatterParams, onRendered) {
    const value = cell.getValue();
    if (typeof value !== 'number' || isNaN(value)) return "";
    const color = formatterParams.color || COMPLIANCE_COLORS.UNKNOWN;
    const container = document.createElement('div');
    container.classList.add('percent-bar-container');
    const bar = document.createElement('div');
    bar.classList.add('percent-bar-bg');
    bar.style.width = `${value}%`;
    bar.style.backgroundColor = color;
    const text = document.createElement('span');
    text.classList.add('percent-bar-text');
    text.textContent = value.toFixed(1) + '%';
    container.appendChild(bar);
    container.appendChild(text);
    return container;
}

function dateSorterNullable(a, b, aRow, bRow, column, dir, sorterParams) {
    const aIsNull = a === null || a === undefined || a === '';
    const bIsNull = b === null || b === undefined || b === '';
    if (aIsNull && bIsNull) return 0;
    if (aIsNull) return dir === "asc" ? 1 : -1;
    if (bIsNull) return dir === "asc" ? -1 : 1;
    return a.localeCompare(b);
}
