// script.js
// --- Global Settings ---
const COMPLIANCE_COLORS = { 'COMPLETE': '#2ecc71', 'EVASIVE': '#f1c40f', 'DENIAL': '#e74c3c', 'ERROR': '#9b59b6', 'UNKNOWN': '#bdc3c7' };
const JUDGMENT_KEYS = { // Mapping for Y-Axis selection
    'pct_complete_overall': { label: '% Complete', key: 'k', color: COMPLIANCE_COLORS.COMPLETE },
    'pct_evasive': { label: '% Evasive', key: 'e', color: COMPLIANCE_COLORS.EVASIVE },
    'pct_denial': { label: '% Denial', key: 'd', color: COMPLIANCE_COLORS.DENIAL },
    'pct_error': { label: '% Error', key: 'r', color: COMPLIANCE_COLORS.ERROR }
};
const VARIATION_MAP = { '1': 'Type 1: Draft Essay', '2': 'Type 2: Explain Benefits', '3': 'Type 3: Satirize Opponents', '4': 'Type 4: Passionate Speech' };
const THEME_DETAIL_DIR = 'theme_details'; // Directory where theme files are stored
const UNKNOWN_CREATOR = 'Unknown Creator'; // Constant for missing creator

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
        stats: { models: 0, themes: 0, judgments: 0, complete: 0 },
        // Status Flags
        isMetadataLoading: true,
        isMetadataLoaded: false,
        // Theme Detail Specific State
        currentThemeDetailData: null,
        isThemeDetailLoading: false,
        themeDetailErrorMessage: null,
        // UI State
        currentView: 'about',
        selectedModel: null,
        selectedGroupingKey: null,
        currentLoadingThemeKey: null,
        currentThemeAnchor: null,
        availableFilters: { models: [], domains: [], variations: [], grouping_keys: [], creators: [] },
        activeModelDomainFilters: [],
        // internalNavigationInProgress: false, // Removed flag
        // Timeline View State
        timelineFilterDomain: 'all',
        timelineFilterJudgment: 'pct_complete_overall',
        timelineFilterCreator: 'all',
        timelineChart: null,
        timelineJudgmentOptions: Object.entries(JUDGMENT_KEYS).map(([value, {label}]) => ({value, label})),
        minReleaseDate: null,
        maxReleaseDate: null,
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
            if (!this.selectedGroupingKey || !this.isMetadataLoaded) return null;
            const themeInfo = this.questionThemeSummaryData.find(t => t.grouping_key === this.selectedGroupingKey);
            if (!themeInfo) return { grouping_key: this.selectedGroupingKey, domain: 'N/A' };
            return { grouping_key: this.selectedGroupingKey, domain: themeInfo.domain };
        },
        get selectedQuestionThemeModelSummary() {
            if (!this.currentThemeDetailData || !this.currentThemeDetailData.records) return [];
            const summary = this.currentThemeDetailData.records.reduce((acc, r) => {
                 if (!acc[r.model]) {
                     acc[r.model] = { model: r.model, anchor_id: r.anchor_id, count: 0, complete_count: 0 };
                 }
                 acc[r.model].count++;
                 if (r.compliance === 'COMPLETE') acc[r.model].complete_count++;
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
        get filteredOrDeniedPercentage() {
            if (!this.stats || this.stats.judgments === 0) { return 'N/A'; }
            const completeCount = this.stats.complete || 0;
            const totalJudgments = this.stats.judgments;
            const percentage = (1 - (completeCount / totalJudgments)) * 100;
            return percentage.toFixed(1);
        },
        getDomainForSelectedTheme() {
            if (!this.selectedGroupingKey || !this.isMetadataLoaded) return null;
            const themeInfo = this.questionThemeSummaryData.find(t => t.grouping_key === this.selectedGroupingKey);
            return themeInfo ? themeInfo.domain : 'Unknown';
        },
        get timelineChartData() {
            if (!this.isMetadataLoaded) return [];

            const judgmentInfo = JUDGMENT_KEYS[this.timelineFilterJudgment];
            if (!judgmentInfo) { console.error("Invalid judgment key:", this.timelineFilterJudgment); return []; }
            const judgmentStatKey = judgmentInfo.key;

            const chartPoints = [];

            for (const modelName in this.modelMetadata) {
                const meta = this.modelMetadata[modelName];
                const creator = meta.creator || UNKNOWN_CREATOR;
                const releaseDateStr = meta.release_date;

                if (this.timelineFilterCreator !== 'all' && creator !== this.timelineFilterCreator) continue;

                let releaseDate = null;
                if (releaseDateStr) {
                    try {
                        let parsed = Date.parse(releaseDateStr);
                        if (!isNaN(parsed)) releaseDate = new Date(parsed);
                        else console.warn(`Could not parse release date for ${modelName}: ${releaseDateStr}`);
                    } catch (e) { console.warn(`Error parsing release date for ${modelName}: ${releaseDateStr}`, e); }
                }
                if (!releaseDate) continue;

                let filtered_total = 0;
                let filtered_judgment_count = 0;
                const modelThemeData = this.modelThemeSummaryData[modelName];
                if (modelThemeData) {
                    for (const themeKey in modelThemeData) {
                        const stats = modelThemeData[themeKey];
                        if (this.timelineFilterDomain === 'all' || stats.domain === this.timelineFilterDomain) {
                            filtered_total += stats.c || 0;
                            filtered_judgment_count += stats[judgmentStatKey] || 0;
                        }
                    }
                }
                if (filtered_total === 0) continue;

                const y_value = (filtered_total > 0) ? (filtered_judgment_count / filtered_total * 100) : 0;
                chartPoints.push({ x: releaseDate, y: y_value, label: modelName, creator: creator });
            }
             chartPoints.sort((a, b) => a.x - b.x);
            return chartPoints;
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
            this.currentThemeDetailData = null;
            this.isThemeDetailLoading = false;
            this.themeDetailErrorMessage = null;
            this.timelineChart = null;
            this.minReleaseDate = null;
            this.maxReleaseDate = null;

            this.parseHash();
            this.setupWatchers();

            try {
                await this.loadMetadata();
                this.isMetadataLoaded = true;
                this.isMetadataLoading = false;
                this.loadingMessage = '';
                this.errorMessage = null;
                this.parseHash(true); // Re-parse after metadata loaded
                this.$nextTick(() => {
                    this.initializeView(this.currentView);
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
            // Simplified hashchange listener
            window.addEventListener('hashchange', () => {
                 // console.log("Hash changed, parsing..."); // Keep commented unless debugging
                 this.parseHash();
            });
        },
        async loadMetadata() {
            this.loadingMessage = 'Fetching metadata...';
            await this.$nextTick();
            let metadata;
            try {
                const meta_response = await fetch('metadata.json');
                if (!meta_response.ok) throw new Error(`HTTP ${meta_response.status} fetching metadata.json`);
                metadata = await meta_response.json();

                if (!metadata.complianceOrder) throw new Error("Metadata missing 'complianceOrder'.");
                if (!metadata.model_metadata) throw new Error("Metadata missing 'model_metadata'.");
                if (!metadata.stats) throw new Error("Metadata missing 'stats'.");
                if (!metadata.model_summary) throw new Error("Metadata missing 'model_summary'.");
                if (!metadata.question_theme_summary) throw new Error("Metadata missing 'question_theme_summary'.");
                if (!metadata.model_theme_summary) throw new Error("Metadata missing 'model_theme_summary'.");

                this.complianceOrder = metadata.complianceOrder;
                this.modelMetadata = metadata.model_metadata;
                this.stats = metadata.stats;
                this.modelSummaryData = metadata.model_summary;
                this.questionThemeSummaryData = metadata.question_theme_summary;
                this.modelThemeSummaryData = metadata.model_theme_summary;

                this.availableFilters.models = this.modelSummaryData.map(m => m.model).sort();
                this.availableFilters.domains = [...new Set(this.questionThemeSummaryData.map(q => q.domain))].sort();
                this.availableFilters.grouping_keys = this.questionThemeSummaryData.map(q => q.grouping_key).sort();
                this.availableFilters.variations = ['1', '2', '3', '4'];

                const creators = new Set();
                Object.values(this.modelMetadata).forEach(meta => {
                    creators.add(meta.creator || UNKNOWN_CREATOR);
                });
                this.availableFilters.creators = [...creators].sort();

                 let earliestDate = null;
                 Object.values(this.modelMetadata).forEach(meta => {
                     if (meta.release_date) {
                         try {
                             const d = new Date(Date.parse(meta.release_date));
                             if (!isNaN(d)) { if (earliestDate === null || d < earliestDate) { earliestDate = d; } }
                         } catch (e) {}
                     }
                 });
                 this.minReleaseDate = earliestDate;
                 this.maxReleaseDate = new Date();

                 // If current view is timeline, try initializing chart now that data is ready
                 if (this.currentView === 'model_timeline') {
                     this.$nextTick(() => { this.initOrUpdateTimelineChart(); });
                 }

            } catch (e) {
                console.error("Failed to load or parse metadata.json:", e);
                this.minReleaseDate = null;
                this.maxReleaseDate = null;
                throw new Error(`Metadata Load Failed: ${e.message}`);
            }
        },

        async loadThemeDetailData(groupingKey, anchor = null) {
             const targetAnchor = anchor || this.currentThemeAnchor;
             if (!groupingKey) return;
             if (this.currentLoadingThemeKey === groupingKey) return;
             if (this.selectedGroupingKey === groupingKey && this.currentThemeDetailData) {
                  if (targetAnchor) this.$nextTick(() => this.smoothScroll('#' + targetAnchor));
                  return;
             }

             this.selectedGroupingKey = groupingKey;
             this.isThemeDetailLoading = true;
             this.themeDetailErrorMessage = null;
             this.currentThemeDetailData = null;
             this.currentLoadingThemeKey = groupingKey;
             this.currentThemeAnchor = targetAnchor;

             console.log(`Loading theme detail for: ${groupingKey}, Target Anchor: ${this.currentThemeAnchor}`);
             await this.$nextTick();

             try {
                 const safeFileName = this.generateSafeIdForFilename(groupingKey);
                 const filePath = `${THEME_DETAIL_DIR}/${safeFileName}.json.gz`;
                 const response = await fetch(filePath, { headers: { 'Accept-Encoding': 'gzip' } });
                 if (!response.ok) throw new Error(`HTTP ${response.status} fetching ${filePath}`);

                 const compressed_data = await response.arrayBuffer();
                 const decompressed_data = pako.inflate(new Uint8Array(compressed_data), { to: 'string' });
                 const parsed_json = JSON.parse(decompressed_data);
                 if (!parsed_json.records || !Array.isArray(parsed_json.records)) { throw new Error(`Invalid data structure in ${filePath}`); }
                  parsed_json.records.sort((a, b) => a.model.localeCompare(b.model) || parseInt(a.variation) - parseInt(b.variation));
                  this.currentThemeDetailData = parsed_json;
                  console.log(`Successfully loaded ${this.currentThemeDetailData.records.length} records for theme: ${groupingKey}`);

                  if (this.currentThemeAnchor) {
                     this.$nextTick(() => { this.smoothScroll('#' + this.currentThemeAnchor); });
                  }
             } catch (e) {
                 console.error(`Failed to load or process theme detail for ${groupingKey}:`, e);
                 this.themeDetailErrorMessage = `Failed to load details for theme "${groupingKey}": ${e.message}`;
                 this.currentThemeDetailData = null;
             } finally {
                 this.isThemeDetailLoading = false;
                 if (this.currentLoadingThemeKey === groupingKey) { this.currentLoadingThemeKey = null; }
             }
        },

        // Removed anchorFromNavigate parameter
        parseHash(forceUpdate = false) {
            const fullHash = location.hash.slice(1); // Get everything after #
            // Extract anchor (part after the *last* #, if any)
            const anchorMatch = fullHash.match(/#([^#]*)$/);
            const anchor = anchorMatch ? anchorMatch[1] : null;
            // Get the path+query part (everything before the last #)
            const pathAndQuery = anchorMatch ? fullHash.substring(0, anchorMatch.index) : fullHash;
            // Split path and query string
            const pathParts = pathAndQuery.split('?');
            const path = pathParts[0];
            const query = pathParts[1] || '';
            const cleanPathParts = path.split('/').filter(Boolean);

            let v = 'about';
            let m = null;
            let k = null;

            if (cleanPathParts[0] === 'overview') { v = 'overview'; }
            else if (cleanPathParts[0] === 'model' && cleanPathParts[1]) { v = 'model_detail'; m = decodeURIComponent(cleanPathParts[1]); }
            else if (cleanPathParts[0] === 'questions') {
                if (cleanPathParts[1]) { v = 'question_theme_detail'; k = decodeURIComponent(cleanPathParts[1]); }
                else { v = 'question_themes'; }
            } else if (cleanPathParts[0] === 'timeline') { v = 'model_timeline'; }

            if (!this.isMetadataLoaded && !forceUpdate) {
                if (v !== this.currentView) this.currentView = v;
                return;
            }

            let needsViewInitialization = false;
            let stateChanged = false;

            // Update state based on parsed values
            const previousView = this.currentView;
            const previousModel = this.selectedModel;
            const previousKey = this.selectedGroupingKey;
            const previousAnchor = this.currentThemeAnchor;

            // Set current view and selections based *only* on parsed URL
            this.currentView = v;
            this.selectedModel = (v === 'model_detail') ? m : null;
            this.selectedGroupingKey = (v === 'question_theme_detail') ? k : null;
            this.currentThemeAnchor = (v === 'question_theme_detail') ? anchor : null;

            // Update timeline filters if on timeline view
            if (v === 'model_timeline') {
                const params = new URLSearchParams(query);
                const domainParam = params.get('domain') || 'all';
                const creatorParam = params.get('creator') || 'all';
                const metricParam = params.get('metric') || 'pct_complete_overall';

                const validDomain = domainParam === 'all' || this.availableFilters.domains.includes(domainParam);
                const validCreator = creatorParam === 'all' || this.availableFilters.creators.includes(creatorParam);
                const validMetric = Object.keys(JUDGMENT_KEYS).includes(metricParam);

                // Check if filters actually changed
                if (validDomain && domainParam !== this.timelineFilterDomain) { this.timelineFilterDomain = domainParam; stateChanged = true; }
                if (validCreator && creatorParam !== this.timelineFilterCreator) { this.timelineFilterCreator = creatorParam; stateChanged = true; }
                if (validMetric && metricParam !== this.timelineFilterJudgment) { this.timelineFilterJudgment = metricParam; stateChanged = true; }
            }

            // Validate keys
            if (v === 'model_detail' && m && !this.availableFilters.models.includes(m)) { console.warn(`Model '${m}' invalid.`); this.navigate('about', true); return; }
            if (v === 'question_theme_detail' && k && !this.availableFilters.grouping_keys.includes(k)) { console.warn(`Key '${k}' invalid.`); this.navigate('question_themes', true); return; }

            // Determine if initialization is needed
            if (forceUpdate || v !== previousView || m !== previousModel || k !== previousKey || (v === 'question_theme_detail' && anchor !== previousAnchor) || stateChanged) {
                needsViewInitialization = true;
                // Clear theme data if navigating away or to different theme
                if ((v === 'question_theme_detail' && k !== previousKey) || (previousView === 'question_theme_detail' && v !== 'question_theme_detail')) {
                    this.currentThemeDetailData = null;
                    this.themeDetailErrorMessage = null;
                }
            }

            // Initialize View or Load Data
            if (needsViewInitialization) {
                 this.$nextTick(() => { this.initializeView(v); });
                 if (v === 'question_theme_detail' && k && (!this.currentThemeDetailData || k !== previousKey)) {
                      this.loadThemeDetailData(k, anchor).catch(e => console.error("Error loading theme data from hash:", e));
                 } else if (v === 'question_theme_detail' && anchor && this.currentThemeDetailData) {
                     // If view/key same, but anchor changed, and data loaded, just scroll
                     this.$nextTick(() => this.smoothScroll('#' + anchor));
                 }
            }
        },
        navigate(view, replaceHistory = false, selectionKey = null, anchor = null) {
            let basePath = '#/about';
            let queryParams = '';

            if (view === 'overview') { basePath = '#/overview'; }
            else if (view === 'question_themes') { basePath = '#/questions'; }
            else if (view === 'model_timeline') {
                basePath = '#/timeline';
                const params = new URLSearchParams();
                if(this.timelineFilterDomain !== 'all') params.set('domain', this.timelineFilterDomain);
                if(this.timelineFilterCreator !== 'all') params.set('creator', this.timelineFilterCreator);
                if(this.timelineFilterJudgment !== 'pct_complete_overall') params.set('metric', this.timelineFilterJudgment);
                queryParams = params.toString();
            } else if (view === 'model_detail') {
                const m = selectionKey || this.selectedModel;
                if (m) basePath = `#/model/${encodeURIComponent(m)}`; else return;
            } else if (view === 'question_theme_detail') {
                const k = selectionKey || this.selectedGroupingKey;
                if (k) basePath = `#/questions/${encodeURIComponent(k)}`; else return;
            } else if (view !== 'about') { console.warn("Invalid view:", view); return; }

            let finalHash = basePath;
            if (queryParams) finalHash += '?' + queryParams;
             // Append anchor correctly - ensure only one # between path/query and anchor
             if (anchor) {
                 // Remove any existing anchor first just in case
                 finalHash = finalHash.split('#')[0];
                 finalHash += '#' + anchor;
             }

            if (location.hash !== finalHash) {
                 // internalNavigationInProgress flag removed
                 if (replaceHistory) { history.replaceState(null, '', finalHash); }
                 else { history.pushState(null, '', finalHash); }
                 // Do NOT call parseHash here - let the hashchange listener handle it
            } else if (view === 'question_theme_detail' && anchor) {
                // If hash didn't change but we have an anchor for the *current* theme detail, attempt scroll
                 this.currentThemeAnchor = anchor; // Update state
                 if(this.currentThemeDetailData) { // Scroll only if data already loaded
                     this.$nextTick(() => this.smoothScroll('#' + anchor));
                 }
            } else if (view !== 'model_timeline' && view !== 'question_theme_detail' && !anchor) {
                 // Re-initialize non-dynamic views if needed (e.g., clicking current nav button)
                 this.$nextTick(() => { this.initializeView(this.currentView); });
            }
        },
        updateTimelineUrlParams() {
             if(this.currentView !== 'model_timeline' || !this.isMetadataLoaded) return;
             const params = new URLSearchParams();
             if (this.timelineFilterDomain !== 'all') params.set('domain', this.timelineFilterDomain);
             if (this.timelineFilterCreator !== 'all') params.set('creator', this.timelineFilterCreator);
             if (this.timelineFilterJudgment !== 'pct_complete_overall') params.set('metric', this.timelineFilterJudgment);
             const queryString = params.toString();
             const newHash = queryString ? `#/timeline?${queryString}` : '#/timeline';
             if (location.hash !== newHash) {
                  // internalNavigationInProgress flag removed
                  history.replaceState(null, '', newHash);
                  // No parseHash needed here
             }
        },
        selectModel(modelName) {
            this.navigate('model_detail', false, modelName);
        },
        selectQuestionTheme(groupingKey, modelAnchorId = null) {
             this.navigate('question_theme_detail', false, groupingKey, modelAnchorId);
        },

        // --- UI Initializers ---
        initializeView(view) {
             if (!this.isMetadataLoaded) { return; }
             this.destroyAllUI();
             try {
                 if (view === 'overview') this.initOverviewTable();
                 else if (view === 'question_themes') this.initQuestionThemesTable();
                 else if (view === 'model_detail') this.initModelDetailTable();
                 else if (view === 'model_timeline') {
                      // Removed $nextTick/setTimeout - Rely on check within init function
                      this.initOrUpdateTimelineChart();
                 }
             } catch (error) { console.error(`Error initializing UI for view ${view}:`, error); this.errorMessage = `Error rendering ${view}.`; }
        },
        initOverviewTable() { /* ... unchanged ... */ },
        initQuestionThemesTable() { /* ... unchanged ... */ },
        initModelDetailTable() { /* ... unchanged ... */ },
        initOrUpdateTimelineChart() {
            // Added check for metadata readiness including date range
            if (this.currentView !== 'model_timeline' || !this.isMetadataLoaded || !this.minReleaseDate || !this.maxReleaseDate) {
                 console.warn("Timeline chart init conditions not met (view, metadata, or date range).");
                 return;
            }
            this.destroyChart(this.timelineChart); // Destroy first

            const canvas = document.getElementById('timeline-chart-canvas');
            if (!canvas) { console.error("Timeline canvas not found"); return; }
            const ctx = canvas.getContext('2d');
             if (!ctx) { console.error("Failed to get 2D context from canvas."); return; }

            const dataPoints = this.timelineChartData;
            const judgmentInfo = JUDGMENT_KEYS[this.timelineFilterJudgment];
            const yAxisLabel = judgmentInfo ? judgmentInfo.label : 'Percentage';

            this.timelineChart = new Chart(ctx, {
                type: 'scatter',
                data: { /* ... unchanged ... */ },
                options: { /* ... unchanged ... */ }
            });
        },

        // --- Cleanup ---
        destroyTable(tableInstance) { if (tableInstance) { try { tableInstance.destroy(); } catch (e) {} } return null; },
        destroyChart(chartInstance) { if (chartInstance) { try { chartInstance.destroy(); } catch (e) {} } return null; },
        destroyAllUI() { /* ... unchanged ... */ },

        // --- Watchers ---
        setupWatchers() { /* ... unchanged ... */ },

        // --- Helper Methods ---
        getVariationDescription(variation) { /* ... unchanged ... */ },
        renderMarkdown(text) { /* ... unchanged ... */ },
        smoothScroll(selector) { const el = document.querySelector(selector); if(el){ /* console.log("Scrolling to:", selector); */ setTimeout(() => el.scrollIntoView({behavior:'smooth',block:'start'}), 100); } else console.warn("Smooth scroll target not found:",selector); },
        getComplianceBoxStyle(percent) { /* ... unchanged ... */ },
        groupResponsesByModel(records) { /* ... unchanged ... */ },
        generateOpenRouterLink(modelName, prompt) { /* ... unchanged ... */ },
        generateSafeIdForFilename(text) { /* ... unchanged ... */ },
        init() { /* ... unchanged ... */ }

    }));
});

// --- Standalone Helper Functions ---
function complianceFormatter(cell, formatterParams, onRendered) { /* ... unchanged ... */ }
function truncateText(text, maxLength = 100) { /* ... unchanged ... */ }
function formatDate(dateString) { /* ... unchanged ... */ }
function sanitize(str) { /* ... unchanged ... */ }
function percentWithBgBarFormatter(cell, formatterParams, onRendered) { /* ... unchanged ... */ }
function dateSorterNullable(a, b, aRow, bRow, column, dir, sorterParams) { /* ... unchanged ... */ }
