const API_BASE = '/api';
function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
}
const CSRF_TOKEN = getCookie('csrftoken');

function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}


// escapeHtml() makes a value safe as TEXT, but an href is a second context:
// `javascript:alert(1)` contains no character escapeHtml touches, and would
// still execute on click. Anything not plainly http(s) or a relative path
// becomes '#'. Staff-supplied content is not trusted here - a manage_projects
// holder must not be able to plant a payload that runs in an administrator's
// session and calls the staff API with their cookies.
function safeUrl(value) {
    if (!value) return '#';
    const raw = String(value).trim();
    if (/^https?:\/\//i.test(raw)) return raw;
    if (/^\/(?!\/)/.test(raw)) return raw;
    return '#';
}

// The mobile drawer's open/close is wired once, in admin_base.html. Wiring it
// here too made one tap toggle it twice, so it never opened on this page.


// Where Mail's "back" goes: the section open before Mail was entered.
let lastPanelSection = 'dashboard';

function showSection(sectionName, clickedElement) {
    // Mail swaps the sidebar for its mailboxes; every other section restores it.
    document.body.classList.toggle('mail-mode', sectionName === 'inbox');
    if (sectionName !== 'inbox') lastPanelSection = sectionName;

    // Main content sections
    document.querySelectorAll('.section').forEach(section => { section.classList.add('hidden'); });
    const targetSection = document.getElementById(sectionName);
    if (targetSection) targetSection.classList.remove('hidden');

    // Sidebar highlighting
    document.querySelectorAll('.nav-item').forEach(link => { link.classList.remove('active'); });
    if (clickedElement) {
        clickedElement.classList.add('active');
    } else {
        const matchingLink = document.getElementById(`nav-${sectionName}`);
        if (matchingLink) matchingLink.classList.add('active');
    }

    // Close mobile menu on navigate
    const sbar = document.getElementById('sidebar');
    const ovr = document.getElementById('mobileOverlay');
    if (window.innerWidth < 1024 && sbar && ovr) {
        sbar.classList.add('-translate-x-full');
        ovr.classList.add('hidden');
    }

    // Load data
    if (sectionName === 'blogs') loadBlogs();
    if (sectionName === 'projects') loadProjects();
    if (sectionName === 'githubSync') loadGithubRepos();
    // Events removed
    if (sectionName === 'dashboard') loadDashboard();
    if (sectionName === 'inbox') loadInbox();
    if (sectionName === 'contacts') loadContacts();
    if (sectionName === 'templates') loadTemplates();
    if (sectionName === 'campaigns') loadCampaigns();
    if (sectionName === 'staff') loadStaff();
    if (sectionName === 'tasks') loadTasks();
    if (sectionName === 'developer' && typeof loadDeveloperKeys === 'function') loadDeveloperKeys();
}

function showAddForm(type) {
    const el = document.getElementById(`${type}Form`);
    if (!el) return;
    el.classList.remove('hidden');
    if (el.classList.contains('fixed')) {
        el.classList.add('flex');
    }
}
function hideAddForm(type) {
    const el = document.getElementById(`${type}Form`);
    if (!el) return;
    el.classList.add('hidden');
    if (el.classList.contains('fixed')) {
        el.classList.remove('flex');
    }
    const form = document.getElementById(`add${type.charAt(0).toUpperCase() + type.slice(1)}Form`);
    if (form) form.reset();
    if (typeof getEmailEditor === 'function') {
        const editor = getEmailEditor(type);
        if (editor) editor.setValue('');
    }
    // Reset header back to 'Add' state visually if needed, simplified here
}


// /api/posts/ and /api/projects/ answer {results, pagination} where
// pagination.total_items is the true row count. Reading .length off that
// object yields undefined, which is why both dashboard cards read 0. Falls
// back to the page length, and then to a bare array, so an unpaginated
// response still counts.
function payloadCount(payload) {
    if (Array.isArray(payload)) return payload.length;
    if (payload && payload.pagination && typeof payload.pagination.total_items === 'number') {
        return payload.pagination.total_items;
    }
    return (payload && payload.results ? payload.results.length : 0);
}

let topBlogsChartInstance = null;
let appointmentsChartInstance = null;
let inquiriesChartInstance = null;
let campaignsChartInstance = null;


async function loadDashboard() {
    try {
        const res = await fetch(`${API_BASE}/admin/stats/`, { credentials: 'same-origin' });
        const data = await res.json();


        // Populate metrics
        document.getElementById('blogCount').textContent = data.metrics.total_blogs ?? 0;
        document.getElementById('blogViewsCount').textContent = data.metrics.total_blog_views ?? 0;
        document.getElementById('projectCount').textContent = data.metrics.total_projects ?? 0;
        document.getElementById('eventCount').textContent = data.metrics.total_events ?? 0;
        document.getElementById('templateCount').textContent = data.metrics.total_templates ?? 0;
        document.getElementById('campaignCount').textContent = data.metrics.total_campaigns ?? 0;
        document.getElementById('inquiryCount').textContent = data.metrics.total_inquiries ?? 0;
        document.getElementById('appointmentCount').textContent = data.metrics.total_appointments ?? 0;

        const likesEl = document.getElementById('likesCount');
        if (likesEl) likesEl.textContent = data.metrics.total_likes ?? 0;
        const commentsEl = document.getElementById('commentsCount');
        if (commentsEl) commentsEl.textContent = data.metrics.total_comments ?? 0;


        // Dark theme chart settings
        const fontSettings = {
            family: 'Inter, sans-serif',
            color: '#9ca3af'
        };

        const chartOptions = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: '#9ca3af',
                        boxWidth: 12,
                        padding: 15,
                        font: { family: 'Inter, sans-serif', size: 11 }
                    }
                }
            }
        };

        // 1. Top Blogs Bar Chart
        if (topBlogsChartInstance) topBlogsChartInstance.destroy();
        const topBlogsCtx = document.getElementById('topBlogsChart')?.getContext('2d');
        if (topBlogsCtx) {
            topBlogsChartInstance = new Chart(topBlogsCtx, {
                type: 'bar',
                data: {
                    labels: data.charts.top_blogs.map(b => b.title),
                    datasets: [{
                        label: 'Views',
                        data: data.charts.top_blogs.map(b => b.views),
                        backgroundColor: 'rgba(0, 122, 255, 0.8)',
                        borderColor: '#007AFF',
                        borderWidth: 1,
                        borderRadius: 6
                    }]
                },
                options: {
                    ...chartOptions,
                    indexAxis: 'y',
                    plugins: {
                        ...chartOptions.plugins,
                        legend: { display: false }
                    },
                    scales: {
                        x: {
                            grid: { color: 'rgba(255, 255, 255, 0.05)' },
                            ticks: { color: '#9ca3af', font: { family: 'Inter' } }
                        },
                        y: {
                            grid: { display: false },
                            ticks: { color: '#9ca3af', font: { family: 'Inter' } }
                        }
                    }
                }
            });
        }

        // 2. Appointments Breakdown (Doughnut Chart)
        if (appointmentsChartInstance) appointmentsChartInstance.destroy();
        const appointmentsCtx = document.getElementById('appointmentsChart')?.getContext('2d');
        if (appointmentsCtx) {
            const labels = Object.keys(data.charts.appointments).map(s => s.toUpperCase());
            const values = Object.values(data.charts.appointments);
            const hasData = values.some(v => v > 0);

            appointmentsChartInstance = new Chart(appointmentsCtx, {
                type: 'doughnut',
                data: {
                    labels: hasData ? labels : ['NO DATA'],
                    datasets: [{
                        data: hasData ? values : [1],
                        backgroundColor: hasData ? [
                            'rgba(234, 179, 8, 0.8)',  // pending (Yellow)
                            'rgba(59, 130, 246, 0.8)', // confirmed (Blue)
                            'rgba(16, 185, 129, 0.8)', // completed (Green)
                            'rgba(239, 68, 68, 0.8)',   // cancelled (Red)
                            'rgba(168, 85, 247, 0.8)'  // rescheduled (Purple)
                        ] : ['rgba(255, 255, 255, 0.05)'],
                        borderColor: '#0D121D',
                        borderWidth: 2
                    }]
                },
                options: chartOptions
            });
        }

        // 3. Inquiries Breakdown (Pie Chart)
        if (inquiriesChartInstance) inquiriesChartInstance.destroy();
        const inquiriesCtx = document.getElementById('inquiriesChart')?.getContext('2d');
        if (inquiriesCtx) {
            const labels = Object.keys(data.charts.inquiries).map(s => s.toUpperCase());
            const values = Object.values(data.charts.inquiries);
            const hasData = values.some(v => v > 0);

            inquiriesChartInstance = new Chart(inquiriesCtx, {
                type: 'pie',
                data: {
                    labels: hasData ? labels : ['NO DATA'],
                    datasets: [{
                        data: hasData ? values : [1],
                        backgroundColor: hasData ? [
                            'rgba(249, 115, 22, 0.8)', // new (Orange)
                            'rgba(107, 114, 128, 0.8)', // read (Gray)
                            'rgba(6, 182, 212, 0.8)',  // replied (Cyan)
                            'rgba(16, 185, 129, 0.8)'  // archived (Green)
                        ] : ['rgba(255, 255, 255, 0.05)'],
                        borderColor: '#0D121D',
                        borderWidth: 2
                    }]
                },
                options: chartOptions
            });
        }

        // 4. Campaigns Overview (Doughnut Chart)
        if (campaignsChartInstance) campaignsChartInstance.destroy();
        const campaignsCtx = document.getElementById('campaignsChart')?.getContext('2d');
        if (campaignsCtx) {
            const labels = Object.keys(data.charts.campaigns).map(s => s.toUpperCase());
            const values = Object.values(data.charts.campaigns);
            const hasData = values.some(v => v > 0);

            campaignsChartInstance = new Chart(campaignsCtx, {
                type: 'doughnut',
                data: {
                    labels: hasData ? labels : ['NO DATA'],
                    datasets: [{
                        data: hasData ? values : [1],
                        backgroundColor: hasData ? [
                            'rgba(107, 114, 128, 0.8)', // draft (Gray)
                            'rgba(234, 179, 8, 0.8)',  // queued (Yellow)
                            'rgba(14, 165, 233, 0.8)', // sending (Light Blue)
                            'rgba(16, 185, 129, 0.8)', // sent (Green)
                            'rgba(168, 85, 247, 0.8)', // paused (Purple)
                            'rgba(239, 68, 68, 0.8)'   // failed (Red)
                        ] : ['rgba(255, 255, 255, 0.05)'],
                        borderColor: '#0D121D',
                        borderWidth: 2
                    }]
                },
                options: chartOptions
            });
        }

    } catch (error) { console.error('Error loading dashboard:', error); }
}

// CRUD helpers
async function addItem(endpoint, form) {
    const formData = new FormData(form);
    if (formData.has('featured')) { formData.set('featured', formData.get('featured') === 'on' ? 'true' : 'false'); } else { formData.set('featured', 'false'); }
    try {
        await fetchJson(`${API_BASE}/${endpoint}/`, { method: 'POST', body: formData, headers: { 'X-CSRFToken': CSRF_TOKEN } });
        toast.success('Saved.');
        form.reset();
        // hideAddForm call moved to specific blocks below to ensure correct ID is used
        if (endpoint === 'posts') { hideAddForm('blog'); loadBlogs(); }
        if (endpoint === 'projects') { hideAddForm('project'); loadProjects(); }
    } catch (e) { console.error(e); toastApiError(e, 'The item could not be saved.'); }
}

async function updateItem(endpoint, id, form) {
    const formData = new FormData(form);
    if (formData.has('featured')) { formData.set('featured', formData.get('featured') === 'on' ? 'true' : 'false'); } else { formData.set('featured', 'false'); }

    try {
        // Use POST for updates to support file uploads (Django doesn't handle multipart PUT well)
        await fetchJson(`${API_BASE}/${endpoint}/${id}/`, { method: 'POST', body: formData, headers: { 'X-CSRFToken': CSRF_TOKEN } });
        toast.success('Updated.');
        form.reset();
        form.onsubmit = null; // Remove override

        // Reset UI text
        const type = endpoint === 'posts' ? 'blog' : 'project';
        document.querySelector(`#${type}Form h3`).textContent = type === 'blog' ? 'New Blog Post' : 'New Project Details';
        document.querySelector(`#${type}Form button[type="submit"]`).textContent = type === 'blog' ? 'Save Post' : 'Save Project';

        if (endpoint === 'posts') { hideAddForm('blog'); loadBlogs(); document.getElementById('addBlogForm').onsubmit = async (e) => { e.preventDefault(); await addItem('posts', e.target); }; }
        if (endpoint === 'projects') { hideAddForm('project'); loadProjects(); document.getElementById('addProjectForm').onsubmit = async (e) => { e.preventDefault(); await addItem('projects', e.target); }; }
    } catch (e) { console.error(e); toastApiError(e, 'The update failed.'); }
}

async function deleteItem(endpoint, id) {
    const ok = await tkConfirm('This permanently deletes the item. It cannot be undone.', {
        title: 'Delete this item?', confirmText: 'Delete', danger: true
    });
    if (!ok) return;
    try {
        await fetchJson(`${API_BASE}/${endpoint}/${id}/`, { method: 'DELETE', headers: { 'X-CSRFToken': CSRF_TOKEN } });
        toast.success('Deleted.');
        if (endpoint === 'posts') loadBlogs();
        if (endpoint === 'projects') loadProjects();
    } catch (e) { console.error(e); toastApiError(e, 'The item could not be deleted.'); }
}

// Init
document.addEventListener('DOMContentLoaded', () => {
    if (window.location.pathname.startsWith('/admin-panel/')) {
        // Intercept sidebar clicks on /admin-panel/ to prevent reload
        document.querySelectorAll('.nav-item').forEach(link => {
            const href = link.getAttribute('href');
            if (href && href.includes('?section=')) {
                link.addEventListener('click', (e) => {
                    e.preventDefault();
                    const urlParams = new URLSearchParams(href.split('?')[1]);
                    const section = urlParams.get('section');
                    if (section) {
                        showSection(section, link);
                        // Update browser URL without reload
                        history.pushState(null, '', href);
                    }
                });
            }
        });

        // Load correct section from URL query param or default to dashboard
        const urlParams = new URLSearchParams(window.location.search);
        const section = urlParams.get('section') || 'dashboard';
        const activeLink = document.getElementById(`nav-${section}`);
        showSection(section, activeLink);
    }
});
