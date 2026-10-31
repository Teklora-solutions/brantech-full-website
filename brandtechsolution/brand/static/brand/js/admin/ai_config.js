/**
 * AI Configuration & Touchpoint Hub Management
 * Manages LLM Provider toggles, Codex Device Code authorization flow,
 * Touchpoint Model/Provider routing, and Model Catalogue browsing.
 */

(function () {
    'use strict';

    let configData = {
        providers: [],
        touchpoints: [],
        models_by_provider: {},
        codex: {}
    };

    let activeCodexSessionId = null;
    let codexPollInterval = null;

    document.addEventListener('DOMContentLoaded', initAIConfig);

    function initAIConfig() {
        const refreshBtn = document.getElementById('refreshCatalogueBtn');
        const openCodexBtn = document.getElementById('openCodexModalBtn');
        const closeCodexBtn = document.getElementById('closeCodexModalBtn');
        const startCodexBtn = document.getElementById('startCodexFlowBtn');
        const copyCodeBtn = document.getElementById('copyCodexCodeBtn');
        const finishCodexBtn = document.getElementById('finishCodexModalBtn');
        const searchInput = document.getElementById('touchpointSearchInput');
        const catalogueFilter = document.getElementById('catalogueProviderFilter');

        if (refreshBtn) refreshBtn.addEventListener('click', handleRefreshCatalogue);
        if (openCodexBtn) openCodexBtn.addEventListener('click', openCodexModal);
        if (closeCodexBtn) closeCodexBtn.addEventListener('click', closeCodexModal);
        if (startCodexBtn) startCodexBtn.addEventListener('click', handleStartCodexAuth);
        if (copyCodeBtn) copyCodeBtn.addEventListener('click', handleCopyCodexCode);
        if (finishCodexBtn) finishCodexBtn.addEventListener('click', () => { closeCodexModal(); loadAIConfig(); });
        if (searchInput) searchInput.addEventListener('input', renderTouchpointsTable);
        if (catalogueFilter) catalogueFilter.addEventListener('change', renderCatalogueGrid);

        // Initial load
        loadAIConfig();
    }

    async function loadAIConfig() {
        try {
            const res = await fetch('/api/ai/config/', { credentials: 'same-origin' });
            if (!res.ok) throw new Error('Failed to load AI config');
            const data = await res.json();
            if (data.success) {
                configData = data;
                renderProvidersGrid();
                renderTouchpointsTable();
                renderCatalogueGrid();
            }
        } catch (err) {
            console.error('[AI Config] Error loading summary:', err);
            if (window.showToast) window.showToast('Failed loading AI configuration', 'error');
        }
    }

    // ============================================================
    // Providers Grid Rendering & Toggling
    // ============================================================

    function renderProvidersGrid() {
        const container = document.getElementById('aiProvidersGrid');
        if (!container) return;

        if (!configData.providers || configData.providers.length === 0) {
            container.innerHTML = `<div class="col-span-full p-6 text-center text-sm text-secondaryText">No providers configured</div>`;
            return;
        }

        const providerIcons = {
            gemini: { icon: 'fa-google', color: 'text-amber-400', badge: 'bg-amber-500/10 text-amber-400 border-amber-500/20' },
            vertex: { icon: 'fa-cloud', color: 'text-blue-400', badge: 'bg-blue-500/10 text-blue-400 border-blue-500/20' },
            openai: { icon: 'fa-bolt', color: 'text-emerald-400', badge: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' },
            anthropic: { icon: 'fa-feather', color: 'text-orange-400', badge: 'bg-orange-500/10 text-orange-400 border-orange-500/20' },
            deepseek: { icon: 'fa-compass', color: 'text-cyan-400', badge: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20' },
            openrouter: { icon: 'fa-route', color: 'text-purple-400', badge: 'bg-purple-500/10 text-purple-400 border-purple-500/20' },
            codex: { icon: 'fa-robot', color: 'text-teal-400', badge: 'bg-teal-500/10 text-teal-400 border-teal-500/20' },
        };

        container.innerHTML = configData.providers.map(p => {
            const meta = providerIcons[p.name] || { icon: 'fa-server', color: 'text-gray-400', badge: 'bg-gray-500/10 text-gray-400 border-gray-500/20' };
            const isConnected = p.has_credential;
            const isEnabled = p.enabled;
            const statusBadge = isConnected && isEnabled
                ? `<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"><span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span> Active</span>`
                : (isConnected
                    ? `<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">Disabled</span>`
                    : `<span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-gray-500/10 text-gray-400 border border-gray-500/20">Key Absent</span>`);

            return `
                <div class="clean-card rounded-2xl p-5 border border-borderLight bg-surface relative overflow-hidden flex flex-col justify-between hover:border-purple-500/30 transition-all duration-200">
                    <div>
                        <div class="flex items-center justify-between mb-3">
                            <div class="flex items-center gap-2.5">
                                <div class="w-10 h-10 rounded-xl ${meta.badge} border flex items-center justify-center text-lg">
                                    <i class="fas ${meta.icon}"></i>
                                </div>
                                <div>
                                    <h3 class="font-bold text-base text-primaryText capitalize font-heading">${p.name}</h3>
                                    <span class="text-xs text-secondaryText capitalize">${p.billing} billed • Rank #${p.preference}</span>
                                </div>
                            </div>
                            <div>${statusBadge}</div>
                        </div>

                        <div class="space-y-2 py-2 text-xs">
                            <div class="flex items-center justify-between text-secondaryText">
                                <span>Default Model:</span>
                                <span class="font-mono text-primaryText font-medium truncate max-w-[140px]" title="${p.default_model || 'None'}">${p.default_model || '<span class="italic text-gray-500">Unset</span>'}</span>
                            </div>
                            <div class="flex items-center justify-between text-secondaryText">
                                <span>Discovered Models:</span>
                                <span class="font-semibold text-primaryText">${p.model_count}</span>
                            </div>
                        </div>
                    </div>

                    <div class="pt-4 border-t border-borderLight mt-2 flex items-center justify-between">
                        <label class="relative inline-flex items-center cursor-pointer">
                            <input type="checkbox" class="sr-only peer provider-toggle-cb" data-provider="${p.name}" ${isEnabled && isConnected ? 'checked' : ''} ${!isConnected ? 'disabled' : ''}>
                            <div class="w-9 h-5 bg-background border border-borderLight peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-secondaryText peer-checked:after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-purple-600"></div>
                            <span class="ml-2 text-xs text-secondaryText peer-checked:text-primaryText font-medium">${isEnabled ? 'Enabled' : 'Off'}</span>
                        </label>

                        ${p.name === 'codex' && !isConnected ? `
                            <button type="button" class="text-xs px-2.5 py-1 rounded-lg bg-teal-500/10 text-teal-400 hover:bg-teal-500/20 transition-colors font-medium connect-codex-shortcut-btn">
                                <i class="fas fa-plug-circle-bolt mr-1"></i> Connect
                            </button>
                        ` : ''}
                    </div>
                </div>
            `;
        }).join('');

        // Attach listeners
        container.querySelectorAll('.provider-toggle-cb').forEach(cb => {
            cb.addEventListener('change', async (e) => {
                const name = e.target.dataset.provider;
                const enabled = e.target.checked;
                await handleToggleProvider(name, enabled);
            });
        });

        container.querySelectorAll('.connect-codex-shortcut-btn').forEach(btn => {
            btn.addEventListener('click', openCodexModal);
        });
    }

    async function handleToggleProvider(name, enabled) {
        try {
            const res = await fetch(`/api/ai/providers/${name}/toggle/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken(),
                },
                body: JSON.stringify({ enabled })
            });
            const data = await res.json();
            if (data.success) {
                if (window.showToast) window.showToast(`Provider ${name} updated`, 'success');
                loadAIConfig();
            } else {
                throw new Error(data.error || 'Failed updating provider');
            }
        } catch (err) {
            console.error('[AI Config] Toggle error:', err);
            if (window.showToast) window.showToast(err.message, 'error');
            loadAIConfig();
        }
    }

    // ============================================================
    // Touchpoints Table Rendering & Routing
    // ============================================================

    function renderTouchpointsTable() {
        const tbody = document.getElementById('touchpointsTableBody');
        const searchInput = document.getElementById('touchpointSearchInput');
        if (!tbody) return;

        const query = (searchInput ? searchInput.value : '').toLowerCase().trim();
        let list = configData.touchpoints || [];

        if (query) {
            list = list.filter(tp =>
                tp.name.toLowerCase().includes(query) ||
                tp.key.toLowerCase().includes(query) ||
                tp.description.toLowerCase().includes(query)
            );
        }

        if (list.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" class="py-8 text-center text-secondaryText text-sm">
                        No touchpoints match your query.
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = list.map(tp => {
            const providerOptions = configData.providers.map(p =>
                `<option value="${p.name}" ${tp.pinned_provider === p.name ? 'selected' : ''}>${p.name.toUpperCase()} (${p.has_credential ? 'Ready' : 'No Key'})</option>`
            ).join('');

            // Available models for this touchpoint
            const curProvider = tp.pinned_provider || 'gemini';
            const models = configData.models_by_provider[curProvider] || [];
            const modelOptions = models.map(m =>
                `<option value="${m.model_id}" ${tp.pinned_model === m.model_id ? 'selected' : ''}>${m.display_name || m.model_id}</option>`
            ).join('');

            return `
                <tr class="hover:bg-white/[0.01] transition-colors" data-touchpoint="${tp.key}">
                    <td class="py-4 px-6">
                        <div class="font-bold text-primaryText font-heading">${tp.name}</div>
                        <div class="text-xs text-secondaryText font-mono">${tp.key}</div>
                        <div class="text-xs text-secondaryText/80 mt-0.5 max-w-sm truncate" title="${tp.description}">${tp.description || 'No description provided.'}</div>
                    </td>
                    <td class="py-4 px-6">
                        <span class="inline-flex px-2 py-0.5 rounded text-xs font-semibold bg-white/5 border border-borderLight text-secondaryText capitalize">${tp.default_role}</span>
                    </td>
                    <td class="py-4 px-6">
                        <select class="tp-provider-select px-2.5 py-1.5 rounded-lg bg-background border border-borderLight text-xs text-primaryText focus:border-purple-400 focus:outline-none w-36">
                            <option value="">(Global Ladder)</option>
                            ${providerOptions}
                        </select>
                    </td>
                    <td class="py-4 px-6">
                        <select class="tp-model-select px-2.5 py-1.5 rounded-lg bg-background border border-borderLight text-xs text-primaryText focus:border-purple-400 focus:outline-none w-44" ${!tp.pinned_provider ? 'disabled' : ''}>
                            <option value="">(Provider Default)</option>
                            ${modelOptions}
                        </select>
                    </td>
                    <td class="py-4 px-6">
                        <label class="inline-flex items-center cursor-pointer text-xs text-secondaryText">
                            <input type="checkbox" class="tp-fallback-cb rounded bg-background border-borderLight text-purple-600 focus:ring-0 mr-1.5" ${tp.allow_fallback ? 'checked' : ''}>
                            Allow
                        </label>
                    </td>
                    <td class="py-4 px-6 text-right font-mono font-medium text-xs text-primaryText">
                        ${tp.total_invocations.toLocaleString()}
                    </td>
                    <td class="py-4 px-6 text-center">
                        <button type="button" class="tp-save-btn px-3 py-1.5 rounded-lg bg-purple-600/10 hover:bg-purple-600 text-purple-400 hover:text-white border border-purple-500/20 text-xs font-semibold transition-all">
                            Save
                        </button>
                    </td>
                </tr>
            `;
        }).join('');

        // Attach change and save listeners
        tbody.querySelectorAll('tr[data-touchpoint]').forEach(row => {
            const key = row.dataset.touchpoint;
            const provSelect = row.querySelector('.tp-provider-select');
            const modSelect = row.querySelector('.tp-model-select');
            const fallCb = row.querySelector('.tp-fallback-cb');
            const saveBtn = row.querySelector('.tp-save-btn');

            provSelect.addEventListener('change', () => {
                const selProvider = provSelect.value;
                if (!selProvider) {
                    modSelect.disabled = true;
                    modSelect.innerHTML = `<option value="">(Provider Default)</option>`;
                } else {
                    modSelect.disabled = false;
                    const available = configData.models_by_provider[selProvider] || [];
                    modSelect.innerHTML = `<option value="">(Provider Default)</option>` + available.map(m =>
                        `<option value="${m.model_id}">${m.display_name || m.model_id}</option>`
                    ).join('');
                }
            });

            saveBtn.addEventListener('click', async () => {
                saveBtn.disabled = true;
                saveBtn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i>`;
                await handleSaveTouchpoint(key, {
                    pinned_provider: provSelect.value,
                    pinned_model: modSelect.value,
                    allow_fallback: fallCb.checked,
                });
                saveBtn.disabled = false;
                saveBtn.innerHTML = `Save`;
            });
        });
    }

    async function handleSaveTouchpoint(key, payload) {
        try {
            const res = await fetch(`/api/ai/touchpoints/${key}/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken(),
                },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (data.success) {
                if (window.showToast) window.showToast(`Touchpoint ${key} routing saved`, 'success');
                loadAIConfig();
            } else {
                throw new Error(data.error || 'Failed saving touchpoint');
            }
        } catch (err) {
            console.error('[AI Config] Touchpoint save error:', err);
            if (window.showToast) window.showToast(err.message, 'error');
        }
    }

    // ============================================================
    // Model Catalogue Grid Rendering
    // ============================================================

    function renderCatalogueGrid() {
        const container = document.getElementById('catalogueCardsGrid');
        const filterSelect = document.getElementById('catalogueProviderFilter');
        if (!container) return;

        const selProvider = filterSelect ? filterSelect.value : 'all';
        let allModels = [];

        Object.keys(configData.models_by_provider || {}).forEach(prov => {
            if (selProvider === 'all' || selProvider === prov) {
                configData.models_by_provider[prov].forEach(m => {
                    allModels.push({ ...m, provider: prov });
                });
            }
        });

        if (allModels.length === 0) {
            container.innerHTML = `<div class="col-span-full py-8 text-center text-secondaryText text-sm">No models found for selected provider</div>`;
            return;
        }

        container.innerHTML = allModels.slice(0, 48).map(m => {
            const inPrice = m.input_price !== null ? `$${m.input_price.toFixed(2)}/1M` : 'Unknown';
            const outPrice = m.output_price !== null ? `$${m.output_price.toFixed(2)}/1M` : 'Unknown';

            return `
                <div class="p-4 rounded-xl bg-background border border-borderLight flex flex-col justify-between hover:border-borderMedium transition-colors text-xs">
                    <div>
                        <div class="flex items-center justify-between mb-1.5">
                            <span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-white/5 text-purple-400 border border-purple-500/20">${m.provider}</span>
                            <span class="font-mono text-secondaryText text-[10px]">${m.context_tokens ? (m.context_tokens / 1000).toFixed(0) + 'k ctx' : ''}</span>
                        </div>
                        <h4 class="font-bold text-primaryText font-heading text-sm truncate" title="${m.display_name}">${m.display_name}</h4>
                        <div class="font-mono text-[11px] text-secondaryText truncate mt-0.5" title="${m.model_id}">${m.model_id}</div>
                    </div>
                    
                    <div class="pt-3 border-t border-borderLight mt-3 flex items-center justify-between text-[11px] text-secondaryText">
                        <span>In: <strong class="text-primaryText">${inPrice}</strong></span>
                        <span>Out: <strong class="text-primaryText">${outPrice}</strong></span>
                    </div>
                </div>
            `;
        }).join('');
    }

    async function handleRefreshCatalogue() {
        const btn = document.getElementById('refreshCatalogueBtn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = `<i class="fas fa-arrows-rotate fa-spin text-purple-400"></i> Refreshing...`;
        }
        try {
            const res = await fetch('/api/ai/providers/refresh/', {
                method: 'POST',
                headers: { 'X-CSRFToken': getCsrfToken() }
            });
            if (!res.ok) {
                const text = await res.text();
                let errMsg = 'Refresh failed';
                try { errMsg = JSON.parse(text).error || errMsg; } catch(e) { console.error("Non-JSON response"); }
                throw new Error(errMsg);
            }
            const data = await res.json();
            if (data.success) {
                if (window.showToast) window.showToast('Model catalogue refreshed', 'success');
                loadAIConfig();
            } else {
                throw new Error(data.error || 'Refresh failed');
            }
        } catch (err) {
            console.error('[AI Config] Refresh error:', err);
            if (window.showToast) window.showToast(err.message, 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = `<i class="fas fa-arrows-rotate text-purple-400"></i> <span>Refresh Catalogue</span>`;
            }
        }
    }

    // ============================================================
    // Codex Device Code Authorization Modal & Polling
    // ============================================================

    function openCodexModal() {
        const modal = document.getElementById('codexAuthModal');
        if (!modal) return;
        modal.classList.remove('hidden');
        modal.classList.add('flex');

        // Reset steps
        document.getElementById('codexStepInit').classList.remove('hidden');
        document.getElementById('codexStepActive').classList.add('hidden');
        document.getElementById('codexStepSuccess').classList.add('hidden');
    }

    function closeCodexModal() {
        const modal = document.getElementById('codexAuthModal');
        if (!modal) return;
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        if (codexPollInterval) {
            clearInterval(codexPollInterval);
            codexPollInterval = null;
        }
        activeCodexSessionId = null;
    }

    async function handleStartCodexAuth() {
        const startBtn = document.getElementById('startCodexFlowBtn');
        if (startBtn) {
            startBtn.disabled = true;
            startBtn.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> Initializing Device Code...`;
        }

        try {
            const res = await fetch('/api/ai/codex/device-auth/', {
                method: 'POST',
                headers: { 'X-CSRFToken': getCsrfToken() }
            });
            const data = await res.json();

            if (data.user_code) {
                activeCodexSessionId = data.session_id;
                document.getElementById('codexStepInit').classList.add('hidden');
                document.getElementById('codexStepActive').classList.remove('hidden');
                document.getElementById('codexUserCodeDisplay').textContent = data.user_code;

                // Start polling
                startCodexPolling(data.session_id);
            } else {
                throw new Error(data.error || 'Could not retrieve device code');
            }
        } catch (err) {
            console.error('[Codex Auth] Start error:', err);
            if (window.showToast) window.showToast(err.message, 'error');
        } finally {
            if (startBtn) {
                startBtn.disabled = false;
                startBtn.innerHTML = `<i class="fas fa-key"></i> <span>Generate One-Time Device Code</span>`;
            }
        }
    }

    function startCodexPolling(sessionId) {
        if (codexPollInterval) clearInterval(codexPollInterval);
        codexPollInterval = setInterval(async () => {
            try {
                const res = await fetch(`/api/ai/codex/poll/?session_id=${sessionId}`, { credentials: 'same-origin' });
                const data = await res.json();

                if (data.status === 'success' || data.completed) {
                    clearInterval(codexPollInterval);
                    codexPollInterval = null;
                    document.getElementById('codexStepActive').classList.add('hidden');
                    document.getElementById('codexStepSuccess').classList.remove('hidden');
                    if (window.showToast) window.showToast('Codex subscription authorized!', 'success');
                }
            } catch (err) {
                console.error('[Codex Auth] Polling error:', err);
            }
        }, 2000);
    }

    function handleCopyCodexCode() {
        const code = document.getElementById('codexUserCodeDisplay').textContent.trim();
        if (navigator.clipboard) {
            navigator.clipboard.writeText(code);
            if (window.showToast) window.showToast(`Code ${code} copied to clipboard!`, 'info');
        }
    }

    function getCsrfToken() {
        const match = document.cookie.match(/csrftoken=([^;]+)/);
        return match ? match[1] : '';
    }

})();
