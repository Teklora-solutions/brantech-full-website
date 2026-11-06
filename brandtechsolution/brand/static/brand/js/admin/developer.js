/**
 * Teklora Admin - Developer Agent Setup & Configuration
 */

(function () {
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

    // Keep function signature for core.js section switcher hook
    window.loadDeveloperKeys = function () {
        // Setup cards are statically pre-rendered with the canonical setup link.
    };

    document.addEventListener('DOMContentLoaded', function () {
        const setupLinkInput = document.getElementById('agentSetupLinkInput');
        const copySetupLinkBtn = document.getElementById('copySetupLinkBtn');
        const copyPromptBtn = document.getElementById('copyAgentPromptBtn');

        if (copySetupLinkBtn && setupLinkInput) {
            copySetupLinkBtn.addEventListener('click', function () {
                copyToClipboard(setupLinkInput.value.trim(), copySetupLinkBtn);
            });
        }

        if (copyPromptBtn && setupLinkInput) {
            copyPromptBtn.addEventListener('click', function () {
                const setupUrl = setupLinkInput.value.trim() || `${window.location.origin}/developer/setup/`;
                const prompt = `Read instructions at ${setupUrl} and set up the Teklora Developer skill and MCP server for me.`;
                copyToClipboard(prompt, copyPromptBtn);
            });
        }

        // Quick copy buttons with data-copy-target
        document.querySelectorAll('[data-copy-target]').forEach(btn => {
            btn.addEventListener('click', function () {
                const targetId = this.getAttribute('data-copy-target');
                const targetEl = document.getElementById(targetId);
                if (targetEl) {
                    copyToClipboard(targetEl.textContent.trim(), this);
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
                if (tab === 'claude') {
                    const el = document.getElementById('agentTabClaude');
                    if (el) el.classList.remove('hidden');
                } else if (tab === 'cursor') {
                    const el = document.getElementById('agentTabCursor');
                    if (el) el.classList.remove('hidden');
                } else if (tab === 'antigravity') {
                    const el = document.getElementById('agentTabAntigravity');
                    if (el) el.classList.remove('hidden');
                }
            });
        });
    });
})();
