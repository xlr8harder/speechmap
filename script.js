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
        modelSummaryData: [],
        questionThemeSummaryData: [],
        modelThemeSummaryData: {},
        complianceOrder: [],
        modelMetadata: {},
        stats: { models: 0, themes: 0, judgments: 0, complete: 0 },
        isMetadataLoading: true,
        isMetadataLoaded: false,
        currentThemeDetailData: null,
        isThemeDetailLoading: false,
        themeDetailErrorMessage: null,
        currentView: 'about',
        selectedModel: null,
        selectedGroupingKey: null,
        currentLoadingThemeKey: null,
        currentThemeAnchor: null,
        availableFilters: { models: [], domains: [], variations: [], grouping_keys: [], creators: [] },
        activeModelDomainFilters: [],
        internalNavigationInProgress: false,
        timelineFilterDomain: 'all',
        timelineFilterJudgment: 'pct_complete_overall',
        timelineFilterCreator: 'all',
        timelineChart: null,
        currentChartInitId: 0,
        timelineJudgmentOptions: Object.entries(JUDGMENT_KEYS).map(([value, {label}]) => ({value, label})),
        minReleaseDate: null,
        maxReleaseDate: null,
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
                        // else console.warn(`Could not parse release date for ${modelName}: ${releaseDateStr}`);
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
            this.internalNavigationInProgress = false;
            this.currentChartInitId = 0;

            this.parseHash(); // Initial parse on load
            this.setupWatchers();

            try {
                await this.loadMetadata();
                this.isMetadataLoaded = true;
                this.isMetadataLoading = false;
                this.loadingMessage = '';
                this.errorMessage = null;
                this.parseHash(true); // Re-parse after metadata loaded, force update
            } catch (e) {
                console.error("Init error (Metadata Load):", e);
                this.errorMessage = `Failed initial load: ${e.message}`;
                this.isMetadataLoading = false;
                this.loadingMessage = '';
            }
            window.addEventListener('hashchange', () => {
                 if (this.internalNavigationInProgress) {
                     this.internalNavigationInProgress = false;
                     // console.log("Hashchange event ignored (internal navigation)");
                     return;
                 }
                 console.log("hashchange event triggered externally, parsing...");
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

                 // Set X-axis range with padding using standard Date methods
                 const today = new Date();
                 const approxMonthInMillis = 30 * 24 * 60 * 60 * 1000;

                 if (earliestDate) {
                     this.minReleaseDate = new Date(earliestDate.getTime() - approxMonthInMillis);
                 } else {
                     // Fallback if no dates found - maybe set to today minus X months?
                     // Or leave null and let chart decide (though padding is preferred)
                     this.minReleaseDate = new Date(today.getTime() - 6 * approxMonthInMillis); // Default to 6 months ago if no dates
                     console.warn("No earliest release date found, using default min date.");
                 }

                 this.maxReleaseDate = new Date(today.getTime() + approxMonthInMillis);

                 console.log("Timeline Date Range Set:", this.minReleaseDate, this.maxReleaseDate);

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
                  if (targetAnchor) this.$nextTick(() => this.smoothScroll(targetAnchor));
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

                  if (this.selectedGroupingKey === groupingKey) {
                     this.currentThemeDetailData = parsed_json;
                     console.log(`Successfully loaded ${this.currentThemeDetailData.records.length} records for theme: ${groupingKey}`);
                     if (this.currentThemeAnchor) {
                         this.$nextTick(() => { this.smoothScroll(this.currentThemeAnchor); });
                     }
                  } else {
                      console.log(`View changed during load for ${groupingKey}, discarding loaded data.`);
                  }
             } catch (e) {
                 console.error(`Failed to load or process theme detail for ${groupingKey}:`, e);
                  if (this.selectedGroupingKey === groupingKey) {
                     this.themeDetailErrorMessage = `Failed to load details for theme "${groupingKey}": ${e.message}`;
                     this.currentThemeDetailData = null;
                  }
             } finally {
                 if (this.currentLoadingThemeKey === groupingKey) {
                    this.isThemeDetailLoading = false;
                    this.currentLoadingThemeKey = null;
                 }
             }
        },

        parseHash(forceUpdate = false) {
            const previousView = this.currentView;
            const previousModel = this.selectedModel;
            const previousKey = this.selectedGroupingKey;
            const previousAnchor = this.currentThemeAnchor;
            const previousDomainFilter = this.timelineFilterDomain;
            const previousCreatorFilter = this.timelineFilterCreator;
            const previousMetricFilter = this.timelineFilterJudgment;

            // console.log(`Parsing hash: ${location.hash} (forceUpdate: ${forceUpdate})`);
            const fullHash = location.hash.slice(1);
            const anchorMatch = fullHash.match(/#([^#]*)$/);
            const anchor = anchorMatch ? anchorMatch[1] : null;
            const pathAndQuery = anchorMatch ? fullHash.substring(0, anchorMatch.index) : fullHash;
            const pathParts = pathAndQuery.split('?');
            const path = pathParts[0];
            const query = pathParts[1] || '';
            const cleanPathParts = path.split('/').filter(Boolean);

            let viewTarget = 'about';
            let modelTarget = null;
            let keyTarget = null;
            let domainTarget = 'all';
            let creatorTarget = 'all';
            let metricTarget = 'pct_complete_overall';

            if (cleanPathParts[0] === 'overview') { viewTarget = 'overview'; }
            else if (cleanPathParts[0] === 'model' && cleanPathParts[1]) { viewTarget = 'model_detail'; modelTarget = decodeURIComponent(cleanPathParts[1]); }
            else if (cleanPathParts[0] === 'questions') {
                if (cleanPathParts[1]) { viewTarget = 'question_theme_detail'; keyTarget = decodeURIComponent(cleanPathParts[1]); }
                else { viewTarget = 'question_themes'; }
            } else if (cleanPathParts[0] === 'timeline') {
                viewTarget = 'model_timeline';
                const params = new URLSearchParams(query);
                domainTarget = params.get('domain') || 'all';
                creatorTarget = params.get('creator') || 'all';
                metricTarget = params.get('metric') || 'pct_complete_overall';
            }

            if (!this.isMetadataLoaded && !forceUpdate) {
                // console.log("Metadata not loaded, setting tentative view:", viewTarget);
                if (viewTarget !== previousView) this.currentView = viewTarget;
                return;
            }

            let viewChanged = viewTarget !== previousView;
            let modelChanged = modelTarget !== previousModel;
            let keyChanged = keyTarget !== previousKey;
            let anchorChanged = anchor !== previousAnchor;
            let timelineFiltersChanged = (
                viewTarget === 'model_timeline' &&
                (domainTarget !== previousDomainFilter ||
                 creatorTarget !== previousCreatorFilter ||
                 metricTarget !== previousMetricFilter)
            );

            const stateChanged = forceUpdate || viewChanged || modelChanged || keyChanged || anchorChanged || timelineFiltersChanged;

            // console.log(`Parsed: view=${viewTarget}, model=${modelTarget}, key=${keyTarget}, anchor=${anchor}`);
            // console.log(`Current: view=${previousView}, model=${previousModel}, key=${previousKey}, anchor=${previousAnchor}`);
            // console.log(`Changes: view=${viewChanged}, model=${modelChanged}, key=${keyChanged}, anchor=${anchorChanged}, filters=${timelineFiltersChanged}, stateChanged=${stateChanged}`);

            if (!stateChanged) {
                // console.log("No relevant state change detected, exiting parseHash.");
                return;
            }

             console.log("Updating state based on parsed URL...");
             this.currentView = viewTarget;
             this.selectedModel = modelTarget;
             this.selectedGroupingKey = keyTarget;
             this.currentThemeAnchor = anchor;

             if (viewTarget === 'model_timeline') {
                 const validDomain = domainTarget === 'all' || this.availableFilters.domains.includes(domainTarget);
                 const validCreator = creatorTarget === 'all' || this.availableFilters.creators.includes(creatorTarget);
                 const validMetric = Object.keys(JUDGMENT_KEYS).includes(metricTarget);
                 this.timelineFilterDomain = validDomain ? domainTarget : 'all';
                 this.timelineFilterCreator = validCreator ? creatorTarget : 'all';
                 this.timelineFilterJudgment = validMetric ? metricTarget : 'pct_complete_overall';
             }

             if (this.currentView === 'model_detail' && this.selectedModel && !this.availableFilters.models.includes(this.selectedModel)) {
                  console.warn(`Model '${this.selectedModel}' invalid.`); this.navigate('about', true); return;
             }
             if (this.currentView === 'question_theme_detail' && this.selectedGroupingKey && !this.availableFilters.grouping_keys.includes(this.selectedGroupingKey)) {
                  console.warn(`Key '${this.selectedGroupingKey}' invalid.`); this.navigate('question_themes', true); return;
             }

             console.log("Triggering UI updates...");
             this.destroyAllUI();
             this.$nextTick(() => { // Initialize UI based on *new* state
                 try {
                     console.log("Initializing UI for:", this.currentView);
                     if (this.currentView === 'overview') { this.initOverviewTable(); }
                     else if (this.currentView === 'question_themes') { this.initQuestionThemesTable(); }
                     else if (this.currentView === 'model_detail') { this.initModelDetailTable(); }
                     else if (this.currentView === 'model_timeline') { this.initOrUpdateTimelineChart(); }
                 } catch (error) {
                     console.error(`Error initializing UI for view ${this.currentView}:`, error);
                     this.errorMessage = `Error rendering ${this.currentView}.`;
                 }
             });


             if (this.currentView === 'question_theme_detail') {
                 if (keyChanged || (viewChanged && !this.currentThemeDetailData) || forceUpdate ) {
                     console.log("Key changed or data missing, loading theme data...");
                     this.loadThemeDetailData(this.selectedGroupingKey, this.currentThemeAnchor)
                         .catch(e => console.error("Error loading theme data from hash:", e));
                 } else if (anchorChanged && this.currentThemeDetailData) {
                     console.log("Only anchor changed, scrolling...");
                     this.$nextTick(() => this.smoothScroll(this.currentThemeAnchor));
                 } else if (this.currentThemeAnchor && this.currentThemeDetailData) {
                     console.log("Navigating back to theme with anchor, ensuring scroll...");
                     this.$nextTick(() => this.smoothScroll(this.currentThemeAnchor));
                 }
             } else if (previousView === 'question_theme_detail'){
                 this.currentThemeDetailData = null;
                 this.themeDetailErrorMessage = null;
                 this.currentThemeAnchor = null;
             }
        },
        navigate(view, replaceHistory = false, selectionKey = null, anchor = null) {
            let basePath = '#/';
            let queryParams = '';

            if (view === 'overview') { basePath += 'overview'; }
            else if (view === 'question_themes') { basePath += 'questions'; }
            else if (view === 'model_timeline') {
                basePath += 'timeline';
                const params = new URLSearchParams();
                if(this.timelineFilterDomain !== 'all') params.set('domain', this.timelineFilterDomain);
                if(this.timelineFilterCreator !== 'all') params.set('creator', this.timelineFilterCreator);
                if(this.timelineFilterJudgment !== 'pct_complete_overall') params.set('metric', this.timelineFilterJudgment);
                queryParams = params.toString();
            } else if (view === 'model_detail') {
                const m = selectionKey || this.selectedModel;
                if (m) basePath += `model/${encodeURIComponent(m)}`;
                else { console.warn("Missing model key for model_detail navigation"); return; }
            } else if (view === 'question_theme_detail') {
                const k = selectionKey || this.selectedGroupingKey;
                if (k) basePath += `questions/${encodeURIComponent(k)}`;
                else { console.warn("Missing theme key for question_theme_detail navigation"); return; }
            } else if (view === 'about') {
                 basePath += 'about';
            } else {
                 console.warn("Invalid view target in navigate:", view);
                 basePath += 'about';
            }

            let pathAndQuery = basePath;
            if (queryParams) pathAndQuery += '?' + queryParams;

            let finalHash = pathAndQuery;
            if (anchor) {
                finalHash += '#' + anchor; // Append anchor correctly
            }

            console.log(`Navigate: Target hash constructed: ${finalHash}`);
            if (location.hash !== finalHash) {
                 console.log("Updating history state...");
                 this.internalNavigationInProgress = true; // Set flag before changing history state
                 if (replaceHistory) { history.replaceState(null, '', finalHash); }
                 else { history.pushState(null, '', finalHash); }
                 // Call parseHash directly after modifying history state
                 this.parseHash();
            } else {
                 console.log("Hash is the same, potentially scrolling or re-initializing.");
                 if (view === 'question_theme_detail' && anchor && this.currentThemeAnchor !== anchor) {
                     this.currentThemeAnchor = anchor;
                     if(this.currentThemeDetailData) { this.$nextTick(() => this.smoothScroll(anchor)); }
                 } else if (!['model_timeline', 'question_theme_detail'].includes(view)) {
                    this.parseHash(true); // Force re-evaluation if clicking same nav link again
                }
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
                  this.internalNavigationInProgress = true; // Set flag before changing history
                  history.replaceState(null, '', newHash);
                  // Let hashchange listener handle parse and potential UI update if needed
             }
        },
        selectModel(modelName) {
            this.navigate('model_detail', false, modelName);
        },
        selectQuestionTheme(groupingKey, modelAnchorId = null) {
             console.log(`[selectQuestionTheme] Key: ${groupingKey}, Anchor: ${modelAnchorId}`);
             this.navigate('question_theme_detail', false, groupingKey, modelAnchorId);
        },

        // Removed initializeView function

        initOverviewTable() {
            const t = document.getElementById("overview-table");
            if (!t || this.currentView !== 'overview' || !this.isMetadataLoaded) { /* console.log("Skipping overview table init."); */ return; }
            // console.log("Initializing Overview Table");
            this.overviewTable = new Tabulator(t, {
                data: [...this.modelSummaryData], layout: "fitDataFill", height: "60vh", placeholder: "No models.", selectable: false, initialSort: [ {column:"pct_complete_overall", dir:"asc"} ],
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
             if (!t || this.currentView !== 'question_themes' || !this.isMetadataLoaded) { /* console.log("Skipping question themes table init."); */ return; }
            // console.log("Initializing Question Themes Table");
            this.questionThemesTable = new Tabulator(t, {
                data: [...this.questionThemeSummaryData], layout: "fitDataFill", height: "60vh", placeholder: "No themes found.", selectable: false, initialSort: [ {column:"pct_complete_overall", dir:"asc"} ],
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
            if (!t || this.currentView !== 'model_detail' || !this.selectedModel || !this.isMetadataLoaded) { /* console.log("Skipping model detail table init."); */ return; }
            // console.log("Initializing Model Detail Table");
            const d = this.selectedModelQuestionSummary;
            this.modelDetailTable = new Tabulator(t, {
                data: [...d], layout: "fitDataFill", height: "60vh", placeholder: "No Question Themes found for this model (or matching domain filter).", selectable: false, initialSort: [ {column:"pct_complete", dir:"asc"} ],
                columns: [
                    {
                        title: "Grouping Key", field: "grouping_key", widthGrow: 2, frozen: true, headerFilter: "input",
                        cellClick: (e, cell) => {
                            const rowData = cell.getRow().getData();
                            const key = rowData.grouping_key;
                            const anchor = `model-${this.generateSafeIdForFilename(this.selectedModel)}`;
                            // console.log(`[ModelDetailTable Click] Key: ${key}, Anchor: ${anchor}`);
                            this.selectQuestionTheme(key, anchor);
                        },
                        cssClass: "clickable-cell"
                    },
                    { title: "Domain", field: "domain", width: 150, headerFilter: "select", headerFilterParams: { values: ["", ...this.availableFilters.domains.filter(dm => d.some(q => q.domain === dm))] } },
                    { title: "# Resp", field: "num_responses", width: 90, hozAlign: "right", sorter: "number" },
                    { title: "% Complete", field: "pct_complete", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.COMPLETE } },
                    { title: "% Evas", field: "pct_evasive", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.EVASIVE } },
                    { title: "% Deny", field: "pct_denial", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.DENIAL } },
                    { title: "% Err", field: "pct_error", width: 100, hozAlign: "right", sorter: "number", formatter: percentWithBgBarFormatter, formatterParams: { color: COMPLIANCE_COLORS.ERROR } }
                ],
            });
        },
        initOrUpdateTimelineChart() {
            if (this.currentView !== 'model_timeline') { return; }
            if (!this.isMetadataLoaded || !this.minReleaseDate || !this.maxReleaseDate) { return; }

            this.destroyChart(this.timelineChart);

            const canvas = document.getElementById('timeline-chart-canvas');
            if (!canvas) { console.error("Timeline canvas not found right before chart creation"); return; }
            const ctx = canvas.getContext('2d');
             if (!ctx) { console.error("Failed to get 2D context right before chart creation."); return; }

            // --- Add Init ID ---
            this.currentChartInitId++; // Increment the global counter
            const initId = this.currentChartInitId; // Capture the ID for this specific attempt
            // console.log(`Attempting chart init with ID: ${initId}`);

            const dataPoints = this.timelineChartData;
            const judgmentInfo = JUDGMENT_KEYS[this.timelineFilterJudgment];
            const yAxisLabel = judgmentInfo ? judgmentInfo.label : 'Percentage';

            // console.log("Initializing Timeline Chart");
            try {
                // Final check before instantiation using the captured ID
                if (this.currentView !== 'model_timeline' || initId !== this.currentChartInitId) {
                    console.warn(`Chart init ${initId} aborted: View changed or newer init started (${this.currentChartInitId}).`);
                    return;
                }

                const chartInstance = new Chart(ctx, {
                    type: 'scatter',
                    data: {
                        datasets: [{
                            label: 'Models',
                            data: dataPoints,
                            pointBackgroundColor: context => judgmentInfo?.color || COMPLIANCE_COLORS.UNKNOWN,
                            pointBorderColor: context => judgmentInfo?.color || COMPLIANCE_COLORS.UNKNOWN,
                            pointRadius: 5,
                            pointHoverRadius: 7
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        onClick: (event) => {
                            const elements = this.timelineChart?.getElementsAtEventForMode(event, 'point', { intersect: true }, true);
                            if (elements && elements.length > 0) {
                                const { datasetIndex, index } = elements[0];
                                const point = this.timelineChart.config.data.datasets[datasetIndex].data[index];
                                if (point && point.label) {
                                    this.navigate('model_detail', false, point.label);
                                }
                            }
                        },
                        scales: {
                            x: {
                                type: 'time',
                                min: this.minReleaseDate ? this.minReleaseDate.valueOf() : undefined,
                                max: this.maxReleaseDate ? this.maxReleaseDate.valueOf() : undefined,
                                time: { unit: 'month', tooltipFormat: 'yyyy-MM-dd', displayFormats: { month: 'yyyy-MM', year: 'yyyy' } },
                                title: { display: true, text: 'Model Release Date' },
                                ticks: { source: 'auto', maxRotation: 45, minRotation: 0 }
                            },
                            y: {
                                title: { display: true, text: yAxisLabel },
                                min: 0, max: 100,
                                ticks: { callback: function(value) { return value + '%'; } }
                            }
                        },
                        plugins: {
                            tooltip: {
                                callbacks: {
                                    label: function(context) {
                                        const point = context.raw;
                                        let label = point.label || '';
                                        if (label) label += ': ';
                                        label += `${point.y.toFixed(1)}%`;
                                        if (point.creator) { label += ` (${point.creator})`; }
                                        return label;
                                    }
                                }
                            },
                            legend: { display: false }
                        }
                    }
                });

                if (initId === this.currentChartInitId) {
                    // console.log(`Chart init ${initId} succeeded and is current.`);
                    this.timelineChart = chartInstance;
                } else {
                    console.log(`Chart init ${initId} succeeded but is outdated (current is ${this.currentChartInitId}), destroying.`);
                    chartInstance.destroy();
                    this.timelineChart = null;
                }

            } catch (error) {
                console.error(`Error during Chart instantiation (Init ID: ${initId}):`, error);
                this.errorMessage = "Failed to render timeline chart.";
                this.timelineChart = null;
            }
        },

        // --- Cleanup ---
        destroyTable(tableInstance) { if (tableInstance) { try { tableInstance.destroy(); } catch (e) {} } return null; },
        destroyChart(chartInstance) { if (chartInstance) { try { chartInstance.destroy(); } catch (e) {} } return null; },
        destroyAllUI() {
            this.overviewTable = this.destroyTable(this.overviewTable);
            this.questionThemesTable = this.destroyTable(this.questionThemesTable);
            this.modelDetailTable = this.destroyTable(this.modelDetailTable);
            this.timelineChart = this.destroyChart(this.timelineChart);
            this.timelineChart = null;
        },

        // --- Watchers ---
        setupWatchers() {
            this.$watch('activeModelDomainFilters', () => {
                 if (this.currentView === 'model_detail' && this.isMetadataLoaded) {
                     this.$nextTick(() => { this.initModelDetailTable(); });
                 }
             });
            // Timeline filter watchers now trigger URL update AND chart redraw directly
            this.$watch('timelineFilterDomain', () => {
                if (this.currentView === 'model_timeline') {
                    this.updateTimelineUrlParams();
                    this.initOrUpdateTimelineChart(); // Directly update chart
                }
            });
            this.$watch('timelineFilterJudgment', () => {
                if (this.currentView === 'model_timeline') {
                    this.updateTimelineUrlParams();
                    this.initOrUpdateTimelineChart(); // Directly update chart
                 }
            });
            this.$watch('timelineFilterCreator', () => {
                if (this.currentView === 'model_timeline') {
                    this.updateTimelineUrlParams();
                    this.initOrUpdateTimelineChart(); // Directly update chart
                }
            });
        },

        // --- Helper Methods ---
        getVariationDescription(variation) { return VARIATION_MAP[String(variation)] || `Type ${variation || 'N/A'}`; },
        renderMarkdown(text) { if (!text) return ''; try { const clean = DOMPurify.sanitize(marked.parse(text), { USE_PROFILES: { html: true } }); return clean; } catch (e) { console.error("Markdown error:", e); return `<pre>Err:\n${sanitize(text)}</pre>`; } },
        smoothScroll(selector, updateUrl = false) {
             const idSelector = selector.startsWith('#') ? selector : '#' + selector;
             const anchorId = selector.startsWith('#') ? selector.substring(1) : selector;

            const el = document.querySelector(idSelector);
            if(el){
                 //console.log("Scrolling to:", idSelector, "Update URL:", updateUrl);
                 setTimeout(() => el.scrollIntoView({behavior:'smooth',block:'start'}), 100);

                 if (updateUrl && this.currentView === 'question_theme_detail' && this.selectedGroupingKey) {
                     const basePath = `#/questions/${encodeURIComponent(this.selectedGroupingKey)}`;
                     const newHash = `${basePath}#${anchorId}`;
                     if (location.hash !== newHash) {
                         // this.internalNavigationInProgress = true; // Flag removed for replaceState
                         history.replaceState(null, '', newHash);
                         this.currentThemeAnchor = anchorId;
                     }
                 }
            } else {
                console.warn("Smooth scroll target not found:", idSelector);
            }
        },
        getComplianceBoxStyle(percent) { let c=COMPLIANCE_COLORS.UNKNOWN; if(typeof percent==='number'&&!isNaN(percent)){c=percent>=90?COMPLIANCE_COLORS.COMPLETE:(percent>=25?COMPLIANCE_COLORS.EVASIVE:COMPLIANCE_COLORS.DENIAL);} const t=(c===COMPLIANCE_COLORS.EVASIVE||c===COMPLIANCE_COLORS.UNKNOWN)?'#333':'white'; return `background-color:${c};color:${t};`; },
        groupResponsesByModel(records) {
             if (!records) return [];
             const grouped = records.reduce((acc, record) => {
                 if (!acc[record.model]) { acc[record.model] = { model: record.model, responses: [] }; }
                 acc[record.model].responses.push(record);
                 return acc;
             }, {});
             return Object.values(grouped).sort((a, b) => a.model.localeCompare(b.model));
        },
        generateOpenRouterLink(modelName, prompt) {
            const baseUrl = "https://openrouter.ai/chat";
            const safeModelName = modelName || "";
            const modelsParam = `${safeModelName}`;
            const messageParam = encodeURIComponent(prompt || "");
            return `${baseUrl}?models=${modelsParam}&message=${messageParam}`;
        },
        generateSafeIdForFilename(text) {
             if (!text) return 'id';
             const nfkd_form = text.normalize('NFKD');
             const only_ascii = nfkd_form.replace(/[\u0300-\u036f]/g, '').toString();
             let safe_text = only_ascii.toLowerCase().replace(/[^\w\s-]/g, '').replace(/\s+/g, '-').replace(/-+/g, '-');
             safe_text = safe_text.replace(/^-+|-+$/g, '').substring(0, 100);
             return safe_text || "id";
        },
        init() { /* Called from x-init, starts initialize() */ }

    }));
});

// --- Standalone Helper Functions ---
function complianceFormatter(cell, formatterParams, onRendered) { const value = cell.getValue(); if (value === null || value === undefined) return ""; const color = COMPLIANCE_COLORS[value] || COMPLIANCE_COLORS['UNKNOWN']; const textColor = (value === 'EVASIVE' || value === 'UNKNOWN') ? '#333' : 'white'; const span = document.createElement('span'); span.textContent = value; span.classList.add('compliance-label'); span.style.backgroundColor = color; span.style.color = textColor; return span; }
function truncateText(text, maxLength = 100) { if (!text) return ""; text = String(text); return text.length <= maxLength ? text : text.substring(0, maxLength) + "..."; }
function formatDate(dateString) { if (!dateString) return "N/A"; try { return new Date(dateString).toLocaleString('sv-SE'); } catch (e) { return dateString; } }
function sanitize(str) { if (str === null || str === undefined) return ''; const temp = document.createElement('div'); temp.textContent = String(str); return temp.innerHTML; }
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
    try { // Attempt date comparison robustly
        const dateA = new Date(a);
        const dateB = new Date(b);
        if (!isNaN(dateA) && !isNaN(dateB)) { return dateA - dateB; }
    } catch(e) {}
    return String(a).localeCompare(String(b)); // Fallback
}
