/**
 * Teklora Admin - Developer API Keys & Agent Setup
 */

(function () {
    const KEYS_API_URL = '/api/staff/developer/keys/';
    let currentKeys = [];
    let latestSecretKey = null;

    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    function copyToClipboard(text, btnElement) {
        if (!text) return;
        navigator.clipboard.writeText(text).then(() => {
            if (btnElement) {
                const origHtml = btnElement.innerHTML;
                btnElement.innerHTML = '<i class="fas fa-check text-emerald-400"></i>';
                setTimeout(() => {
                    btnElement.innerHTML = origHtml;
                }, 2000);
            }
        }).catch(() => {
            // Fallback for older browsers
            const el = document.createElement('textarea');
            el.value = text;
            document.body.appendChild(el);
            el.select();
            document.execCommand('copy');
            document.body.removeChild(el);
            if (btnElement) {
                const origHtml = btnElement.innerHTML;
                btnElement.innerHTML = '<i class="fas fa-check text-emerald-400"></i>';
                setTimeout(() => {
                    btnElement.innerHTML = origHtml;
                }, 2000);
            }
        });
    }

    function updateSetupCards(secretKey) {
        const baseUrl = window.location.origin;
        const keyVal = secretKey || '<YOUR_KEY>';
        const setupUrl = `${baseUrl}/developer/setup/?key=${encodeURIComponent(keyVal)}`;
        const agentPrompt = `Read instructions at ${setupUrl} and set up the Teklora Developer skill and MCP server for me.`;

        const linkInput = document.getElementById('agentSetupLinkInput');
        if (linkInput) {
            linkInput.value = secretKey ? setupUrl : '';
            linkInput.placeholder = secretKey ? setupUrl : 'Generate or select an API key to reveal your auto-setup link';
        }

        const claudeSnippet = document.getElementById('claudeCodeSnippet');
        if (claudeSnippet) {
            claudeSnippet.textContent = `claude mcp add teklora python ~/.teklora/teklora_mcp.py --env TEKLORA_API_KEY="${keyVal}" TEKLORA_BASE_URL="${baseUrl}"`;
        }

        const cursorSnippet = document.getElementById('cursorJsonSnippet');
        if (cursorSnippet) {
            cursorSnippet.textContent = JSON.stringify({
                mcpServers: {
                    teklora: {
                        command: "python",
                        args: ["~/.teklora/teklora_mcp.py"],
                        env: {
                            TEKLORA_API_KEY: keyVal,
                            TEKLORA_BASE_URL: baseUrl
                        }
                    }
                }
            }, null, 2);
        }

        const antigravitySnippet = document.getElementById('antigravitySnippet');
        if (antigravitySnippet) {
            antigravitySnippet.textContent = `curl -fsSL "${setupUrl}"`;
        }

        // Store prompt for copy button
        const copyPromptBtn = document.getElementById('copyAgentPromptBtn');
        if (copyPromptBtn) {
            copyPromptBtn.onclick = function () {
                if (!secretKey) {
                    alert('Please generate a Developer API key first to copy a personalized prompt.');
                    return;
                }
                copyToClipboard(agentPrompt, copyPromptBtn);
            };
        }
    }

    window.loadDeveloperKeys = function () {
        const tbody = document.getElementById('developerKeysTableBody');
        if (!tbody) return;

        fetch(KEYS_API_URL, {
            headers: { 'Accept': 'application/json' },
            credentials: 'same-origin',
        })
            .then(res => {
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                return res.json();
            })
            .then(keys => {
                currentKeys = keys || [];
                renderKeysTable(currentKeys);

                const active = currentKeys.find(k => k.is_active);
                if (active && !latestSecretKey) {
                    // Update preview snippets with prefix hint
                    updateSetupCards(active.prefix);
                } else if (!latestSecretKey) {
                    updateSetupCards(null);
                }
            })
            .catch(err => {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="6" class="py-6 text-center text-rose-400">
                            Failed to load developer keys: ${err.message}
                        </td>
                    </tr>
                `;
            });
    };

    function renderKeysTable(keys) {
        const tbody = document.getElementById('developerKeysTableBody');
        if (!tbody) return;

        if (!keys.length) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" class="py-8 text-center text-secondaryText">
                        <p class="mb-2">No API keys created yet.</p>
                        <button type="button" onclick="document.getElementById('openNewKeyModalBtn').click()"
                            class="text-xs text-brandBlue hover:underline">
                            + Generate your first key
                        </button>
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = keys.map(k => {
            const created = k.created_at ? new Date(k.created_at).toLocaleDateString() : '—';
            const lastUsed = k.last_used_at ? new Date(k.last_used_at).toLocaleDateString() : 'Never';
            const statusBadge = k.is_active
                ? '<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">Active</span>'
                : '<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">Revoked</span>';

            const actions = k.is_active
                ? `<button type="button" data-revoke-key="${k.id}" data-key-name="${k.name}" class="text-xs text-rose-400 hover:text-rose-300 font-medium transition-colors">Revoke</button>`
                : `<span class="text-xs text-secondaryText italic">—</span>`;

            return `
                <tr class="hover:bg-white/[0.02] transition-colors">
                    <td class="py-3 px-4 font-medium text-primaryText">${k.name || 'Unnamed Key'}</td>
                    <td class="py-3 px-4 font-mono text-xs text-secondaryText">${k.prefix}</td>
                    <td class="py-3 px-4 text-secondaryText text-xs">${created}</td>
                    <td class="py-3 px-4 text-secondaryText text-xs">${lastUsed}</td>
                    <td class="py-3 px-4">${statusBadge}</td>
                    <td class="py-3 px-4 text-right">${actions}</td>
                </tr>
            `;
        }).join('');

        // Wire revoke buttons
        tbody.querySelectorAll('[data-revoke-key]').forEach(btn => {
            btn.addEventListener('click', function () {
                const keyId = this.getAttribute('data-revoke-key');
                const keyName = this.getAttribute('data-key-name');
                if (confirm(`Are you sure you want to revoke API key "${keyName}"? Autonomous agents using this key will immediately lose access.`)) {
                    revokeKey(keyId);
                }
            });
        });
    }

    function revokeKey(keyId) {
        fetch(`${KEYS_API_URL}${keyId}/revoke/`, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCookie('csrftoken'),
                'Content-Type': 'application/json',
            },
            credentials: 'same-origin',
        })
            .then(res => {
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                return res.json();
            })
            .then(() => {
                window.loadDeveloperKeys();
            })
            .catch(err => {
                alert(`Error revoking key: ${err.message}`);
            });
    }

    document.addEventListener('DOMContentLoaded', function () {
        // Modal toggles
        const openModalBtn = document.getElementById('openNewKeyModalBtn');
        const newKeyModal = document.getElementById('newKeyModal');
        const keyCreatedModal = document.getElementById('keyCreatedModal');

        if (openModalBtn && newKeyModal) {
            openModalBtn.addEventListener('click', () => {
                newKeyModal.classList.remove('hidden');
                newKeyModal.classList.add('flex');
                const nameInput = document.getElementById('newKeyName');
                if (nameInput) nameInput.focus();
            });
        }

        document.querySelectorAll('[data-close-modal]').forEach(btn => {
            btn.addEventListener('click', function () {
                const modalId = this.getAttribute('data-close-modal');
                const modal = document.getElementById(modalId);
                if (modal) {
                    modal.classList.add('hidden');
                    modal.classList.remove('flex');
                }
            });
        });

        // Create key form
        const newKeyForm = document.getElementById('newKeyForm');
        if (newKeyForm) {
            newKeyForm.addEventListener('submit', function (e) {
                e.preventDefault();
                const name = document.getElementById('newKeyName').value.trim();
                const submitBtn = document.getElementById('submitCreateKeyBtn');
                submitBtn.disabled = true;
                submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Generating...';

                fetch(KEYS_API_URL, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCookie('csrftoken'),
                    },
                    body: JSON.stringify({ name: name }),
                    credentials: 'same-origin',
                })
                    .then(res => {
                        if (!res.ok) throw new Error(`HTTP ${res.status}`);
                        return res.json();
                    })
                    .then(data => {
                        submitBtn.disabled = false;
                        submitBtn.innerHTML = '<i class="fas fa-bolt"></i><span>Generate Key</span>';
                        newKeyForm.reset();

                        // Close create modal
                        newKeyModal.classList.add('hidden');
                        newKeyModal.classList.remove('flex');

                        // Open reveal modal
                        latestSecretKey = data.key;
                        document.getElementById('revealedSecretKey').textContent = data.key;
                        document.getElementById('revealedSetupUrl').textContent = data.setup_url;
                        document.getElementById('revealedAgentPrompt').textContent = data.agent_prompt;

                        keyCreatedModal.classList.remove('hidden');
                        keyCreatedModal.classList.add('flex');

                        // Update setup cards on main section
                        updateSetupCards(data.key);

                        // Reload table
                        window.loadDeveloperKeys();
                    })
                    .catch(err => {
                        submitBtn.disabled = false;
                        submitBtn.innerHTML = '<i class="fas fa-bolt"></i><span>Generate Key</span>';
                        alert(`Failed to generate key: ${err.message}`);
                    });
            });
        }

        // Copy buttons in reveal modal
        const copyRevKeyBtn = document.getElementById('copyRevealedKeyBtn');
        if (copyRevKeyBtn) {
            copyRevKeyBtn.addEventListener('click', function () {
                const text = document.getElementById('revealedSecretKey').textContent;
                copyToClipboard(text, this);
            });
        }

        const copyRevUrlBtn = document.getElementById('copyRevealedUrlBtn');
        if (copyRevUrlBtn) {
            copyRevUrlBtn.addEventListener('click', function () {
                const text = document.getElementById('revealedSetupUrl').textContent;
                copyToClipboard(text, this);
            });
        }

        const copyRevPromptBtn = document.getElementById('copyRevealedPromptBtn');
        if (copyRevPromptBtn) {
            copyRevPromptBtn.addEventListener('click', function () {
                const text = document.getElementById('revealedAgentPrompt').textContent;
                copyToClipboard(text, this);
            });
        }

        const copySetupLinkBtn = document.getElementById('copySetupLinkBtn');
        if (copySetupLinkBtn) {
            copySetupLinkBtn.addEventListener('click', function () {
                const linkVal = document.getElementById('agentSetupLinkInput').value;
                if (!linkVal) {
                    alert('Please generate an API key first to copy your setup link.');
                    return;
                }
                copyToClipboard(linkVal, this);
            });
        }

        // Quick copy buttons with data-copy-target
        document.querySelectorAll('[data-copy-target]').forEach(btn => {
            btn.addEventListener('click', function () {
                const targetId = this.getAttribute('data-copy-target');
                const targetEl = document.getElementById(targetId);
                if (targetEl) {
                    copyToClipboard(targetEl.textContent, this);
                }
            });
        });

        // Agent tabs switcher
        document.querySelectorAll('[data-agent-tab]').forEach(tabBtn => {
            tabBtn.addEventListener('click', function () {
                const tab = this.getAttribute('data-agent-tab');
                document.querySelectorAll('[data-agent-tab]').forEach(b => {
                    b.classList.remove('bg-brandBlue/20', 'text-brandBlue');
                    b.classList.add('text-secondaryText');
                });
                this.classList.add('bg-brandBlue/20', 'text-brandBlue');
                this.classList.remove('text-secondaryText');

                document.querySelectorAll('.agent-tab-content').forEach(c => c.classList.add('hidden'));
                if (tab === 'claude') document.getElementById('agentTabClaude').classList.remove('hidden');
                if (tab === 'cursor') document.getElementById('agentTabCursor').classList.remove('hidden');
                if (tab === 'antigravity') document.getElementById('agentTabAntigravity').classList.remove('hidden');
            });
        });

        // Refresh button
        const refreshBtn = document.getElementById('refreshKeysBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => window.loadDeveloperKeys());
        }
    });
})();
