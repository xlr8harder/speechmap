// script.js
// --- Global Settings ---
const COMPLIANCE_COLORS = { 'COMPLETE': '#2ecc71', 'EVASIVE': '#f1c40f', 'DENIAL': '#e74c3c', 'ERROR': '#9b59b6', 'UNKNOWN': '#bdc3c7' };
const VARIATION_MAP = { '1': 'Type 1: Draft Essay', '2': 'Type 2: Explain Benefits', '3': 'Type 3: Satirize Opponents', '4': 'Type 4: Passionate Speech' };
const THEME_DETAIL_DIR = 'theme_details'; // Directory where theme files are stored

// --- Alpine.js Data Store ---
document.addEventListener('alpine:init', () => {
    Alpine.data('explorerData', () => ({
        // --- State Variables ---
        loadingMessage: 'Initializing...', errorMessage: null,
        // Data Holders (Metadata loaded initially)
        modelSummaryData: [],
        questionThemeSummaryData: [],
        modelThemeSummaryData: {},
        complianceOrder: [],
        modelMetadata: {},
        stats: { models: 0, themes: 0, judgments: 0, complete: 0 }, // Added complete stat
        // Status Flags
        isMetadataLoading: true,
        isMetadataLoaded: false,
        // Theme Detail Specific State
        currentThemeDetailData: null, // Holds data for the currently selected theme
        isThemeDetailLoading: false, // True when fetching data for a specific theme
        themeDetailErrorMessage: null, // Error message specific to theme loading
        // UI State
        currentView: 'about',
        selectedModel: null,
        selectedGroupingKey: null, // The key of the currently viewed/selected theme
        currentLoadingThemeKey: null, // Track which theme is being loaded to prevent race conditions
        currentThemeAnchor: null, // Store anchor for scrolling after load
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
        // This computed property primarily provides static info now
        get selectedQuestionThemeData() {
            if (!this.selectedGroupingKey || !this.isMetadataLoaded) return null;
            const themeInfo = this.questionThemeSummaryData.find(t => t.grouping_key === this.selectedGroupingKey);
            if (!themeInfo) return { grouping_key: this.selectedGroupingKey, domain: 'N/A' }; // Basic info if somehow missing
            return { grouping_key: this.selectedGroupingKey, domain: themeInfo.domain }; // Return static info
            // Dynamic response data comes from currentThemeDetailData
        },
        get selectedQuestionThemeModelSummary() {
            // Calculates summary based on the *dynamically loaded* theme data
            if (!this.currentThemeDetailData || !this.currentThemeDetailData.records) return [];
            const summary = this.currentThemeDetailData.records.reduce((acc, r) => {
                 if (!acc[r.model]) {
                     acc[r.model] = { model: r.model, anchor_id: r.anchor_id, count: 0, complete_count: 0 };
                 }
                 acc[r.model].count++;
                 if (r.compliance === 'COMPLETE') acc[r.model].complete_count++;
                 // Ensure anchor_id is consistent per model group (should be set in preprocessing)
                 if (!acc[r.model].anchor_id) acc[r.model].anchor_id = r.anchor_id;
                 return acc;
            }, {});
            return Object.values(summary)
                       .map(s => ({
                           model: s.model,
                           anchor_id: s.anchor_id,
                           count: s.count,
                           pct_complete: s.count > 0 ? (s.complete_count / s.count * 100) : 0,
                       }))
                       .sort((a, b) => a.model.localeCompare(b.model));
        },
        get filteredOrDeniedPercentage() { // New computed property for stats
            if (!this.stats || this.stats.judgments === 0) {
                 return 'N/A';
            }
            const completeCount = this.stats.complete || 0;
            const totalJudgments = this.stats.judgments;
            const percentage = (1 - (completeCount / totalJudgments)) * 100;
            return percentage.toFixed(1); // Return formatted percentage string
        },
        getDomainForSelectedTheme() {
            if (!this.selectedGroupingKey || !this.isMetadataLoaded) return null;
            const themeInfo = this.questionThemeSummaryData.find(t => t.grouping_key === this.selectedGroupingKey);
            return themeInfo ? themeInfo.domain : 'Unknown';
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
            this.currentThemeDetailData = null; // Reset theme data
            this.isThemeDetailLoading = false;
            this.themeDetailErrorMessage = null;

            this.parseHash(); // Parse initial hash
            this.setupWatchers();

            try {
                await this.loadMetadata(); // Load only metadata
                this.isMetadataLoaded = true;
                this.isMetadataLoading = false;
                this.loadingMessage = '';
                this.parseHash(true); // Re-parse hash now that metadata is loaded
                this.$nextTick(() => {
                    this.initializeTableForView(this.currentView);
                    // If initial view is theme detail, trigger data load
                    if (this.currentView === 'question_theme_detail' && this.selectedGroupingKey && !this.currentThemeDetailData) {
                        this.loadThemeDetailData(this.selectedGroupingKey, this.currentThemeAnchor);
                    }
                });
            } catch (e) {
                console.error("Init error (Metadata Load):", e);
                this.errorMessage = `Failed initial load: ${e.message}`;
                this.isMetadataLoading = false;
                this.loadingMessage = '';
            }
            window.addEventListener('hashchange', () => this.parseHash());
        },
        async loadMetadata() {
            this.loadingMessage = 'Fetching metadata...';
            await this.$nextTick();

            let metadata;
            try {
                const meta_response = await fetch('metadata.json');
                if (!meta_response.ok) {
                    throw new Error(`HTTP ${meta_response.status} fetching metadata.json`);
                }
                metadata = await meta_response.json();

                // Validate essential metadata fields
                if (!metadata.complianceOrder || !Array.isArray(metadata.complianceOrder)) throw new Error("Metadata missing 'complianceOrder'.");
                // if (!metadata.data_files || !Array.isArray(metadata.data_files)) throw new Error("Metadata missing 'data_files'."); // Removed
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
                    complete: Number.isFinite(metadata.stats.complete) ? metadata.stats.complete : 0
                };
                this.modelSummaryData = metadata.model_summary;
                this.questionThemeSummaryData = metadata.question_theme_summary;
                this.modelThemeSummaryData = metadata.model_theme_summary;
                // this.dataFilenames = metadata.data_files; // Removed

                // Populate available filters based on metadata
                this.availableFilters.models = this.modelSummaryData.map(m => m.model).sort();
                this.availableFilters.domains = [...new Set(this.questionThemeSummaryData.map(q => q.domain))].sort();
                this.availableFilters.grouping_keys = this.questionThemeSummaryData.map(q => q.grouping_key).sort();
                this.availableFilters.variations = ['1', '2', '3', '4']; // Assuming these are static

            } catch (e) {
                console.error("Failed to load or parse metadata.json:", e);
                throw new Error(`Metadata Load Failed: ${e.message}`);
            }
        },
        // Removed loadFullDataIfNeeded function

        async loadThemeDetailData(groupingKey, anchor = null) {
            if (!groupingKey) return;
            if (this.currentLoadingThemeKey === groupingKey) {
                 console.log(`Already loading theme: ${groupingKey}`); return; // Prevent concurrent loads for the same key
            }
            if (this.selectedGroupingKey === groupingKey && this.currentThemeDetailData) {
                 console.log(`Theme data already loaded for: ${groupingKey}`);
                 if(anchor) this.$nextTick(() => this.smoothScroll('#'+anchor));
                 return; // Data already loaded
            }

            this.selectedGroupingKey = groupingKey; // Ensure this is set
            this.isThemeDetailLoading = true;
            this.themeDetailErrorMessage = null;
            this.currentThemeDetailData = null; // Clear previous data
            this.currentLoadingThemeKey = groupingKey; // Mark as loading this key
            this.currentThemeAnchor = anchor; // Store anchor for later use

            console.log(`Loading theme detail for: ${groupingKey}`);
            await this.$nextTick(); // Ensure UI updates for loading state

            try {
                const safeFileName = this.generateSafeIdForFilename(groupingKey); // Use helper for filename
                const filePath = `${THEME_DETAIL_DIR}/${safeFileName}.json.gz`;
                const response = await fetch(filePath, { headers: { 'Accept-Encoding': 'gzip' } });

                if (!response.ok) {
                    throw new Error(`HTTP ${response.status} fetching ${filePath}`);
                }

                const compressed_data = await response.arrayBuffer();
                const decompressed_data = pako.inflate(new Uint8Array(compressed_data), { to: 'string' });
                const parsed_json = JSON.parse(decompressed_data);

                if (!parsed_json.records || !Array.isArray(parsed_json.records)) {
                    throw new Error(`Invalid data structure in ${filePath} (missing 'records' array).`);
                }

                // Sort records within the theme file for consistent display
                 parsed_json.records.sort((a, b) => a.model.localeCompare(b.model) || parseInt(a.variation) - parseInt(b.variation));


                this.currentThemeDetailData = parsed_json; // Store the whole parsed object {records: [...]}
                console.log(`Successfully loaded ${this.currentThemeDetailData.records.length} records for theme: ${groupingKey}`);

                 // Scroll after data is loaded and component updates
                 if (this.currentThemeAnchor) {
                    this.$nextTick(() => {
                        this.smoothScroll('#' + this.currentThemeAnchor);
                        this.currentThemeAnchor = null; // Clear anchor after scrolling
                    });
                 }

            } catch (e) {
                console.error(`Failed to load or process theme detail for ${groupingKey}:`, e);
                this.themeDetailErrorMessage = `Failed to load details for theme "${groupingKey}": ${e.message}`;
                this.currentThemeDetailData = null; // Ensure data is null on error
            } finally {
                this.isThemeDetailLoading = false;
                if (this.currentLoadingThemeKey === groupingKey) {
                     this.currentLoadingThemeKey = null; // Allow reloading if needed later
                }
            }
        },

        parseHash(forceUpdate = false) {
            if (!this.isMetadataLoaded && !forceUpdate) { return; } // Wait for metadata

            const h = location.hash.slice(1);
            const parts = h.split('#');
            const pathParts = parts[0].split('/').filter(Boolean);
            const anchor = parts[1] || null; // Capture the anchor (e.g., model ID)

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

             const viewChanged = v !== this.currentView;
             const modelChanged = m !== this.selectedModel;
             const themeChanged = k !== this.selectedGroupingKey;

             if (forceUpdate || viewChanged || modelChanged || themeChanged) {
                 const previousView = this.currentView;
                 this.currentView = v;
                 this.selectedModel = (v === 'model_detail') ? m : null;
                 this.selectedGroupingKey = (v === 'question_theme_detail') ? k : null;
                 this.currentThemeAnchor = anchor; // Store anchor potentially needed for theme load

                 // Clear theme data if navigating away from detail view or to a different theme
                 if ((viewChanged && previousView === 'question_theme_detail') || (themeChanged && v === 'question_theme_detail')) {
                     this.currentThemeDetailData = null;
                     this.themeDetailErrorMessage = null;
                 }

                 if (this.isMetadataLoaded) {
                     // If navigating to theme detail, trigger load if necessary
                     if (v === 'question_theme_detail' && k) {
                         if (!this.currentThemeDetailData || themeChanged) { // Only load if data isn't present or key changed
                            console.log("Triggering theme data load from parseHash...");
                            this.loadThemeDetailData(k, anchor).catch(e => console.error("Error loading theme data from hash:", e));
                         } else if (anchor) {
                            // Data might be loaded, but anchor changed/needs scrolling
                            this.$nextTick(() => this.smoothScroll('#'+anchor));
                         }
                     }
                      // Initialize tables for other views, or if theme view data is already loaded
                      if (v !== 'question_theme_detail' || (v === 'question_theme_detail' && this.currentThemeDetailData)) {
                          this.$nextTick(() => { this.initializeTableForView(this.currentView); });
                      } else if (v !== 'question_theme_detail' ) {
                           // Destroy tables if moving away from a view that had one
                           this.destroyAllTables();
                      }
                 }
             } else if (anchor && v === 'question_theme_detail' && this.currentThemeDetailData) {
                 // If only the anchor changed on the theme detail view and data is loaded, scroll
                 this.smoothScroll('#' + anchor);
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
                if (replaceHistory) history.replaceState(null, '', nH);
                else history.pushState(null, '', nH);
                this.parseHash(); // Let parseHash handle view changes and data loading
            } else if (anchor && view === 'question_theme_detail' && this.currentThemeDetailData) {
                // If hash didn't change but anchor exists and data loaded, just scroll
                this.smoothScroll('#'+anchor);
            } else if (replaceHistory && view !== 'question_theme_detail') {
                 // If replacing history for non-detail view, ensure table is initialized
                 this.$nextTick(() => { this.initializeTableForView(this.currentView); });
            }
        },
        selectModel(modelName) {
            //this.selectedModel = modelName; // Let navigate handle state update via parseHash
            this.navigate('model_detail', false, modelName);
        },
        selectQuestionTheme(groupingKey, modelAnchorId = null) {
             // Navigate first, let parseHash trigger data loading
             this.navigate('question_theme_detail', false, groupingKey, modelAnchorId);
        },

        // --- Tabulator Initializers ---
        initOverviewTable() {
            const t = document.getElementById("overview-table");
            if (!t || this.currentView !== 'overview' || !this.isMetadataLoaded) return;
            this.destroyTable(this.overviewTable);
            const d = this.modelSummaryData;
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
            const d = this.selectedModelQuestionSummary; // This computed property now reads from modelThemeSummaryData (metadata)
            this.modelDetailTable = new Tabulator(t, {
                data: [...d], layout: "fitDataFill", height: "60vh", placeholder: "No Question Themes found for this model (or matching domain filter).", selectable: false, initialSort: [ {column:"pct_complete", dir:"asc"} ],
                columns: [
                    // When clicking, pass the model's anchor ID for potential scrolling in the detail view
                    { title: "Grouping Key", field: "grouping_key", widthGrow: 2, frozen: true, headerFilter: "input", cellClick: (e, c) => this.selectQuestionTheme(c.getRow().getData().grouping_key, `model-${this.generateSafeIdForFilename(this.selectedModel)}`), cssClass: "clickable-cell" },
                    { title: "Domain", field: "domain", width: 150, headerFilter: "select", headerFilterParams: { values: ["", ...this.availableFilters.domains.filter(dm => d.some(q => q.domain === dm))] } },
                    { title: "# Resp", field: "num_responses", width: 90, hozAlign: "right", sorter: "number" },
                    { title: "% Complete", field: "pct_complete", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.COMPLETE } },
                    { title: "% Evas", field: "pct_evasive", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.EVASIVE } },
                    { title: "% Deny", field: "pct_denial", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.DENIAL } },
                    { title: "% Err", field: "pct_error", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.ERROR } }
                ],
            });
        },
        initializeTableForView(view) {
             if (!this.isMetadataLoaded) { return; }
             this.destroyAllTables(); // Clear previous tables first
             try {
                 if (view === 'overview') this.initOverviewTable();
                 else if (view === 'question_themes') this.initQuestionThemesTable();
                 else if (view === 'model_detail') this.initModelDetailTable();
                 // No table for question_theme_detail view itself
                 // console.log("Finished initializeTableForView for view:", view);
             } catch (error) { console.error(`Error initializing table for view ${view}:`, error); this.errorMessage = `Error rendering ${view} table.`; }
        },
        destroyTable(tableInstance) { if (tableInstance) { try { tableInstance.destroy(); } catch (e) {} } return null; },
        destroyAllTables() { this.overviewTable = this.destroyTable(this.overviewTable); this.questionThemesTable = this.destroyTable(this.questionThemesTable); this.modelDetailTable = this.destroyTable(this.modelDetailTable); },

        // --- Watchers ---
        setupWatchers() {
            // Re-initialize model detail table if domain filters change
            this.$watch('activeModelDomainFilters', () => { if (this.currentView === 'model_detail' && this.isMetadataLoaded) this.initModelDetailTable(); });
            // No need to watch for full data load anymore
        },

        // --- Helper Methods ---
        getVariationDescription(variation) { return VARIATION_MAP[String(variation)] || `Type ${variation || 'N/A'}`; },
        renderMarkdown(text) { if (!text) return ''; try { const clean = DOMPurify.sanitize(marked.parse(text), { USE_PROFILES: { html: true } }); return clean; } catch (e) { console.error("Markdown error:", e); return `<pre>Err:\n${sanitize(text)}</pre>`; } },
        smoothScroll(selector) { const el = document.querySelector(selector); if(el){ console.log("Scrolling to:", selector); setTimeout(() => el.scrollIntoView({behavior:'smooth',block:'start'}), 100); } else console.warn("Smooth scroll target not found:",selector); }, // Reduced timeout slightly
        getComplianceBoxStyle(percent) { let c=COMPLIANCE_COLORS.UNKNOWN; if(typeof percent==='number'&&!isNaN(percent)){c=percent>=90?COMPLIANCE_COLORS.COMPLETE:(percent>=25?COMPLIANCE_COLORS.EVASIVE:COMPLIANCE_COLORS.DENIAL);} const t=(c===COMPLIANCE_COLORS.EVASIVE||c===COMPLIANCE_COLORS.UNKNOWN)?'#333':'white'; return `background-color:${c};color:${t};`; },
        groupResponsesByModel(records) { // Accepts records array directly
             if (!records) return [];
             const grouped = records.reduce((acc, record) => {
                 if (!acc[record.model]) {
                      acc[record.model] = { model: record.model, responses: [] };
                 }
                 acc[record.model].responses.push(record);
                 return acc;
             }, {});
             // Ensure consistent sorting by model name
             return Object.values(grouped).sort((a, b) => a.model.localeCompare(b.model));
        },
        generateOpenRouterLink(modelName, prompt) {
            const baseUrl = "https://openrouter.ai/chat";
            const safeModelName = modelName || "";
            const modelsParam = `${safeModelName}`;
            const messageParam = encodeURIComponent(prompt || "");
            return `${baseUrl}?models=${modelsParam}&message=${messageParam}`;
        },
        // Helper specifically for creating filesystem/URL safe IDs from potentially complex strings
        generateSafeIdForFilename(text) {
             if (!text) return 'id';
             // Normalize unicode characters, remove accents etc.
             const nfkd_form = text.normalize('NFKD');
             const only_ascii = nfkd_form.replace(/[\u0300-\u036f]/g, '').toString();
             // Replace non-alphanumeric with hyphen, ensure single hyphens
             let safe_text = only_ascii.toLowerCase().replace(/[^\w\s-]/g, '').replace(/\s+/g, '-').replace(/-+/g, '-');
             // Trim leading/trailing hyphens and limit length
             safe_text = safe_text.replace(/^-+|-+$/g, '').substring(0, 100);
             return safe_text || "id"; // Fallback if everything gets stripped
        },
        init() { /* Called from x-init, starts initialize() */ }

    }));
});

// --- Standalone Helper Functions ---
function complianceFormatter(cell, formatterParams, onRendered) { const value = cell.getValue(); if (value === null || value === undefined) return ""; const color = COMPLIANCE_COLORS[value] || COMPLIANCE_COLORS['UNKNOWN']; const textColor = (value === 'EVASIVE' || value === 'UNKNOWN') ? '#333' : 'white'; const span = document.createElement('span'); span.textContent = value; span.classList.add('compliance-label'); span.style.backgroundColor = color; span.style.color = textColor; return span; }
function truncateText(text, maxLength = 100) { if (!text) return ""; text = String(text); return text.length <= maxLength ? text : text.substring(0, maxLength) + "..."; }
function formatDate(dateString) { if (!dateString) return "N/A"; try { return new Date(dateString).toLocaleString('sv-SE'); } catch (e) { return dateString; } }
function sanitize(str) { if (str === null || str === undefined) return ''; const temp = document.createElement('div'); temp.textContent = String(str); return temp.innerHTML; }
// Removed standalone generateSafeId as it's now part of Alpine component for filenames

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
    // Attempt date comparison first, fallback to localeCompare
    const dateA = new Date(a);
    const dateB = new Date(b);
    if (!isNaN(dateA) && !isNaN(dateB)) {
        return dateA - dateB;
    }
    // Fallback for non-date strings or invalid dates
    return String(a).localeCompare(String(b));
}
