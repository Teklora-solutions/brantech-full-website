// Tasks section.
//
// The two rules from staff.js hold here too:
//   1. Every value from the API goes through escapeHtml() before it is
//      interpolated into markup.
//   2. No JavaScript is built inside an on* attribute. Rows carry data-*
//      attributes and delegated listeners read them.
//
// Every top-level name is prefixed. staff.js is a peer module sharing this
// global scope, and a second `const ROLES` anywhere would be a redeclaration
// SyntaxError that silently kills whichever file parsed second - taking an
// unrelated section down with it. For the same reason this file defines its
// own fetch helper rather than borrowing staff.js's apiFetch: escapeHtml and
// CSRF_TOKEN come from core.js, which is the shared base, but section modules
// do not depend on each other.
const TASK_API = '/api/work';

let TASK_WORKSPACE = new URLSearchParams(window.location.search).get('task_view') === 'backlog' ? 'backlog' : 'board';
let TASK_PROJECT = '';
let TASK_PROJECTS = [];
let TASK_REQUEST = 0;
let TASK_MODAL_FOCUS = null;
let TASK_TAB = 'mine';
let TASK_ROWS = [];
let TASK_NEXT = null;
let TASK_SEARCH = '';
let TASK_PEOPLE = [];
let TASK_CAN_MANAGE = false;
let TASK_LOADED = false;

async function taskApi(path, options = {}) {
    const url = path.startsWith('http') ? path : `${TASK_API}${path}`;
    const response = await fetch(url, {
        credentials: 'same-origin',
        headers: { 'X-CSRFToken': CSRF_TOKEN, 'Content-Type': 'application/json' },
        ...options,
    });
    if (!response.ok) {
        let detail = 'Request failed';
        try {
            const body = await response.json();
            detail = typeof body === 'string'
                ? body
                : (body.detail || Object.values(body).flat().join(' ') || JSON.stringify(body));
        } catch (e) { /* response had no JSON body */ }
        throw new Error(detail);
    }
    return response.status === 204 ? null : response.json();
}

// DRF returns `next` as an absolute URL. Only follow it if it points back at
// this origin, so a spoofed or misconfigured link cannot make the panel send
// its session cookie to another host.
function taskSameOrigin(next) {
    if (!next) return null;
    try {
        const url = new URL(next, window.location.href);
        return url.origin === window.location.origin ? url.toString() : null;
    } catch (e) { return null; }
}

/* ---------- rendering helpers ---------- */

function renderTaskMarkdown(rawText) {
    if (!rawText) return '<p class="text-sm text-gray-500 italic">No description.</p>';
    if (typeof marked !== 'undefined' && typeof marked.parse === 'function') {
        return marked.parse(rawText);
    }
    return `<div class="whitespace-pre-line">${escapeHtml(rawText)}</div>`;
}

// Priority is carried by the card's left edge, using the same border-l-4
// device as the dashboard's stat cards - so urgency is legible while scanning
// a column of cards, without a pill competing with the status for attention.
const TASK_PRIORITY = {
    4: { label: 'Urgent', edge: 'border-l-red-500',    text: 'text-red-400' },
    3: { label: 'High',   edge: 'border-l-orange-500', text: 'text-orange-400' },
    2: { label: 'Normal', edge: 'border-l-brand-blue', text: 'text-blue-400' },
    1: { label: 'Low',    edge: 'border-l-gray-600',   text: 'text-gray-500' },
};

// Matches the inbox's status badges: uppercase, rounded-full, tinted
// background with a border of the same hue.
const TASK_STATUS_BADGE = {
    open: 'text-brand-blue bg-blue-900/30 border border-blue-500/30',
    in_review: 'text-yellow-400 bg-yellow-900/30 border border-yellow-500/30',
    done: 'text-brand-green bg-green-900/30 border border-green-500/30',
};

function taskPriority(task) {
    return TASK_PRIORITY[task.priority] || TASK_PRIORITY[2];
}

function taskStatusBadge(task) {
    const tone = TASK_STATUS_BADGE[task.status] || 'text-gray-300 bg-white/5';
    return `<span class="text-xs font-semibold px-2.5 py-1 rounded-full uppercase tracking-wide ${tone}">
        ${escapeHtml(task.status_display)}
    </span>`;
}

function taskDueLabel(task) {
    if (!task.due_date) return '';
    const tone = task.is_overdue ? 'text-red-400' : 'text-gray-500';
    // The whole class, not a suffix: "fas" and "far" are different Font
    // Awesome families and emitting both leaves the glyph up to stylesheet
    // order.
    const icon = task.is_overdue
        ? 'fas fa-triangle-exclamation'
        : 'far fa-calendar';
    const label = task.is_overdue
        ? `Overdue &middot; ${escapeHtml(task.due_date)}`
        : `Due ${escapeHtml(task.due_date)}`;
    return `<span class="inline-flex items-center gap-1.5 ${tone}">
        <i class="${icon}"></i>${label}
    </span>`;
}

// One initial per assignee, ringed green once that person has finished.
// Reuses the inbox's avatar treatment, and is the fastest read of the thing
// this section exists to show: who holds this, and how far along they are.
function taskAvatars(task) {
    if (!task.assignees.length) {
        return `<span class="text-xs text-gray-600 italic">Unassigned</span>`;
    }
    return `<div class="flex -space-x-2">${task.assignees.map(a => `
        <span title="${escapeHtml(a.username)}${a.done ? ' - done' : ''}"
            class="relative w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold
                ring-2 ring-dark-card ${a.done
                    ? 'bg-brand-green/20 border border-green-500/40 text-brand-green'
                    : 'bg-white/5 border border-white/10 text-gray-400'}">
            ${escapeHtml((a.username || '?').charAt(0).toUpperCase())}
        </span>`).join('')}</div>`;
}

// A shared task's real state is "how many of us are finished", which no
// single status pill can express: four people with three done looks the same
// as four with none. The bar makes that the most glanceable thing on the card.
function taskProgressBar(task) {
    const total = task.assignees.length;
    if (!total) return '';
    const done = task.assignees.filter(a => a.done).length;
    const pct = Math.round((done / total) * 100);
    const complete = done === total;
    return `
    <div class="mt-4">
        <div class="flex justify-between items-center text-xs mb-1.5">
            <span class="${complete ? 'text-brand-green' : 'text-gray-500'}">
                ${done} of ${total} finished
            </span>
            <span class="text-gray-600">${pct}%</span>
        </div>
        <div class="h-1.5 rounded-full bg-white/5 overflow-hidden">
            <div class="h-full rounded-full transition-all duration-500 ${complete ? 'bg-brand-green' : 'bg-brand-blue'}"
                style="width: ${pct}%"></div>
        </div>
    </div>`;
}

function taskCard(task) {
    const priority = taskPriority(task);
    return `
    <div class="bg-dark-card border border-dark-border border-l-4 ${priority.edge} p-6 rounded-xl shadow-lg
        hover:border-brand-blue/30 transition-all duration-300 cursor-pointer group"
        data-action="open-task" data-id="${escapeHtml(task.id)}">

        <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 pb-4 border-b border-white/5">
            <div class="min-w-0">
                <h3 class="text-lg font-bold text-white truncate group-hover:text-brand-blue transition-colors">
                    ${escapeHtml(task.title)}
                </h3>
                <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-400 mt-1">
                    <span class="font-semibold ${priority.text}">${escapeHtml(priority.label)}</span>
                    <span>#${escapeHtml(task.id)}</span>
                    ${task.repository_name ? `<span>${escapeHtml(task.repository_name)} · ${escapeHtml(task.source_display)}</span>` : ''}
                    ${taskDueLabel(task)}
                    ${task.comment_count ? `<span class="flex items-center gap-1.5">
                        <i class="far fa-comment"></i>${escapeHtml(task.comment_count)}
                    </span>` : ''}
                </div>
            </div>
            <div class="flex items-center gap-3 self-end md:self-auto shrink-0">
                ${taskAvatars(task)}
                ${taskStatusBadge(task)}
            </div>
        </div>

        ${taskProgressBar(task)}
    </div>`;
}

// The dashboard's accent-card idiom, so the board opens on the same footing
// as the Overview rather than dropping straight into a list.
function taskStatCard(label, value, colour, icon) {
    return `
    <div class="bg-dark-card border border-dark-border border-l-4 ${colour.edge} rounded-xl p-5
        relative overflow-hidden group hover:${colour.hover} transition-all duration-300">
        <div class="absolute top-0 right-0 p-3 opacity-10 group-hover:opacity-20 transition-opacity">
            <i class="fas ${icon} text-5xl ${colour.text}"></i>
        </div>
        <div class="relative z-10">
            <p class="text-xs font-medium text-gray-400 mb-1 uppercase tracking-wider">${escapeHtml(label)}</p>
            <h3 class="text-3xl font-bold text-white">${escapeHtml(value)}</h3>
        </div>
    </div>`;
}

function renderTaskStats(summary) {
    const cards = [
        taskStatCard('Assigned to me', summary.my_open,
            { edge: 'border-l-brand-blue', text: 'text-brand-blue', hover: 'border-brand-blue/30' },
            'fa-user-check'),
        taskStatCard('Overdue', summary.overdue,
            { edge: 'border-l-red-500', text: 'text-red-500', hover: 'border-red-500/30' },
            'fa-triangle-exclamation'),
        taskStatCard('Completed', summary.done,
            { edge: 'border-l-brand-green', text: 'text-brand-green', hover: 'border-brand-green/30' },
            'fa-circle-check'),
    ];
    // Only reviewers get the review card - it counts work waiting on a
    // decision they are the ones who make.
    if (summary.can_manage) {
        cards.splice(1, 0, taskStatCard('Waiting on review', summary.needs_review,
            { edge: 'border-l-yellow-500', text: 'text-yellow-500', hover: 'border-yellow-500/30' },
            'fa-hourglass-half'));
    }
    document.getElementById('taskStats').innerHTML = cards.join('');
}

/* ---------- list ---------- */

function taskQueryString() {
    const params = new URLSearchParams({ workspace: TASK_WORKSPACE });
    if (TASK_WORKSPACE === 'backlog') {
        if (TASK_PROJECT) params.set('repository', TASK_PROJECT);
        if (TASK_SEARCH) params.set('q', TASK_SEARCH);
        return `/tasks/?${params.toString()}`;
    }
    if (TASK_TAB === 'mine') { params.set('mine', '1'); params.set('active', '1'); }
    if (TASK_TAB === 'all') params.set('active', '1');
    if (TASK_TAB === 'review') params.set('status', 'in_review');
    if (TASK_TAB === 'done') params.set('status', 'done');
    if (TASK_SEARCH) params.set('q', TASK_SEARCH);
    return `/tasks/?${params.toString()}`;
}

// Empty states follow the inbox's: a centred card with a faded icon, not a
// bare line of grey text. Each says what the state means rather than just
// reporting zero, and the search case names the term that found nothing.
const TASK_EMPTY = {
    mine: { icon: 'fa-mug-hot', text: 'Nothing assigned to you right now.' },
    all: { icon: 'fa-list-check', text: 'No open tasks. Everything is either done or not yet created.' },
    review: { icon: 'fa-circle-check', text: 'Nothing waiting for review.' },
    done: { icon: 'fa-flag-checkered', text: 'No completed tasks yet.' },
};

function renderTaskList() {
    const container = document.getElementById('taskList');
    if (!TASK_ROWS.length) {
        const empty = TASK_WORKSPACE === 'backlog'
            ? { icon: 'fa-list-check', text: TASK_SEARCH || TASK_PROJECT
                ? 'No project tasks match these filters.'
                : 'No project tasks waiting for an owner. Roadmap items and documentation fixes appear here automatically.' }
            : TASK_SEARCH
            ? { icon: 'fa-magnifying-glass', text: `No tasks match "${TASK_SEARCH}".` }
            : (TASK_EMPTY[TASK_TAB] || TASK_EMPTY.all);
        container.innerHTML = `
        <div class="text-center py-12 bg-dark-card border border-dark-border rounded-xl text-gray-500">
            <i class="fas ${empty.icon} text-4xl mb-3 opacity-40"></i>
            <p>${escapeHtml(empty.text)}</p>
        </div>`;
    } else {
        container.innerHTML = TASK_WORKSPACE === 'backlog'
            ? `<div class="bg-dark-card border border-dark-border rounded-xl overflow-hidden divide-y divide-dark-border">${TASK_ROWS.map(taskBacklogRow).join('')}</div>`
            : TASK_ROWS.map(taskCard).join('');
    }
    document.getElementById('taskListMore').classList.toggle('hidden', !TASK_NEXT);
}

async function loadTaskPage(url, append) {
    const request = ++TASK_REQUEST;
    const data = await taskApi(url);
    if (request !== TASK_REQUEST) return;
    TASK_ROWS = append ? TASK_ROWS.concat(data.results || []) : (data.results || []);
    TASK_NEXT = taskSameOrigin(data.next);
    renderTaskList();
}

async function refreshTaskSummary() {
    try {
        const summary = await taskApi('/summary/');
        TASK_CAN_MANAGE = summary.can_manage;

        document.getElementById('newTaskBtn').classList.toggle('hidden', !TASK_CAN_MANAGE);
        document.getElementById('newTaskBtn').classList.toggle('flex', TASK_CAN_MANAGE);
        document.getElementById('taskReviewTab').classList.toggle('hidden', !TASK_CAN_MANAGE);

        const reviewCount = document.getElementById('taskReviewCount');
        reviewCount.textContent = summary.needs_review;
        reviewCount.classList.toggle('hidden', !summary.needs_review);

        document.getElementById('taskBacklogCount').textContent = summary.backlog;
        renderTaskStats(summary);

        // The sidebar badge shows whichever number the viewer can act on:
        // work waiting on them, or - for a reviewer - work waiting on their
        // approval. Reviewers see the review queue, since that is the thing
        // that stalls other people if it is ignored.
        const badge = document.getElementById('taskNavBadge');
        if (badge) {
            const count = TASK_CAN_MANAGE && summary.needs_review
                ? summary.needs_review
                : summary.my_open;
            badge.textContent = count;
            badge.classList.toggle('hidden', !count);
        }
    } catch (e) { console.error('task summary:', e); }
}

async function loadTasks() {
    document.getElementById('taskList').innerHTML = '<div class="space-y-3" aria-label="Loading tasks">' + Array.from({length: 3}, () => '<div class="bg-dark-card border border-dark-border rounded-xl p-5"><div class="h-3 bg-white/5 rounded w-2/3 mb-3"></div><div class="h-2 bg-white/5 rounded w-1/3"></div></div>').join('') + '</div>';
    try {
        await refreshTaskSummary();
        if (!TASK_LOADED) {
            TASK_PEOPLE = await taskApi('/assignable/');
            TASK_LOADED = true;
        }
        await loadTaskPage(taskQueryString(), false);
        if (TASK_WORKSPACE === 'backlog') await loadTaskBacklogProjects();
    } catch (e) {
        document.getElementById('taskList').innerHTML =
            `<div class="text-red-400 text-sm">${escapeHtml(e.message)}</div>`;
    }
}

/* ---------- detail modal ---------- */

function openTaskModal(title, body) {
    TASK_MODAL_FOCUS = document.activeElement;
    document.getElementById('taskModalTitle').textContent = title;
    document.getElementById('taskModalBody').innerHTML = body;
    const modal = document.getElementById('taskModal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    document.getElementById('taskModalClose').focus();
}

function closeTaskModal() {
    const modal = document.getElementById('taskModal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    document.getElementById('taskModalBody').innerHTML = '';
    if (TASK_MODAL_FOCUS && TASK_MODAL_FOCUS.isConnected) TASK_MODAL_FOCUS.focus();
}

const TASK_ACTIVITY_ICON = {
    comment: 'fa-comment text-gray-500',
    created: 'fa-plus text-blue-400',
    edited: 'fa-pen text-gray-500',
    assignees_changed: 'fa-users text-blue-400',
    marked_done: 'fa-check text-green-400',
    marked_undone: 'fa-rotate-left text-yellow-400',
    submitted: 'fa-paper-plane text-yellow-400',
    approved: 'fa-circle-check text-green-400',
    reopened: 'fa-arrow-rotate-left text-red-400',
    commit: 'fa-code-commit text-blue-400',
};

// A comment is something a person wrote and gets the inbox's inset message
// block. A status change is something that happened and stays a single quiet
// line - the two should not compete, and a wall of identically-weighted rows
// makes the one someone actually typed hard to find.
function taskActivityRow(entry) {
    const when = new Date(entry.created_at).toLocaleString();
    const icon = TASK_ACTIVITY_ICON[entry.kind] || 'fa-circle text-gray-600';
    const initial = escapeHtml((entry.actor_name || '?').charAt(0).toUpperCase());

    if (entry.kind === 'comment') {
        return `
        <div class="flex gap-3">
            <span class="w-8 h-8 rounded-full bg-brand-blue/20 border border-brand-blue/30 text-brand-blue
                text-xs font-bold flex items-center justify-center shrink-0">${initial}</span>
            <div class="min-w-0 flex-1">
                <div class="flex items-baseline gap-2 mb-1">
                    <span class="text-sm font-semibold text-white">${escapeHtml(entry.actor_name)}</span>
                    <span class="text-xs text-gray-600">${escapeHtml(when)}</span>
                </div>
                <div class="p-3 rounded-lg bg-[#06090F]/90 border border-white/5 text-gray-200 text-sm leading-relaxed github-readme-body break-words">
                    ${renderTaskMarkdown(entry.body)}
                </div>
            </div>
        </div>`;
    }

    return `
    <div class="flex gap-3 items-start">
        <span class="w-8 h-8 rounded-full bg-white/5 border border-white/10 flex items-center justify-center shrink-0">
            <i class="fas ${icon} text-xs"></i>
        </span>
        <div class="min-w-0 pt-1.5">
            <span class="text-sm text-gray-300 break-words">${escapeHtml(entry.body || entry.kind_display)}</span>
            <span class="text-xs text-gray-600 ml-2 whitespace-nowrap">${escapeHtml(entry.actor_name)} &middot; ${escapeHtml(when)}</span>
        </div>
    </div>`;
}

function taskDetailBody(task, activity, submissions = []) {
    const mine = task.my_assignment;
    const inReview = task.status === 'in_review';
    const isDone = task.status === 'done';

    const priority = taskPriority(task);

    const assigneeRows = task.assignees.length
        ? task.assignees.map(a => `
            <div class="flex justify-between items-center gap-3 py-2.5">
                <div class="flex items-center gap-3 min-w-0">
                    <span class="w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold shrink-0
                        ${a.done
                            ? 'bg-brand-green/20 border border-green-500/40 text-brand-green'
                            : 'bg-white/5 border border-white/10 text-gray-400'}">
                        ${escapeHtml((a.username || '?').charAt(0).toUpperCase())}
                    </span>
                    <div class="min-w-0">
                        <div class="text-sm text-white truncate">${escapeHtml(a.username)}</div>
                        <div class="text-xs ${a.done ? 'text-brand-green' : 'text-gray-500'}">
                            ${a.done ? 'Finished their part' : 'Still working'}
                        </div>
                    </div>
                </div>
                ${TASK_CAN_MANAGE && !isDone && (a.done || task.delivery_requirement !== 'document') ? `
                    <button type="button" class="text-xs text-brand-blue hover:text-blue-400 transition-colors shrink-0"
                        data-action="${a.done ? 'admin-undone' : 'admin-done'}"
                        data-id="${escapeHtml(task.id)}" data-user="${escapeHtml(a.id)}">
                        ${a.done ? 'Reopen their part' : 'Mark done'}
                    </button>` : ''}
            </div>`).join('')
        : '<p class="text-sm text-gray-600 italic py-2">Nobody is assigned.</p>';

    return `
    <div class="space-y-6">
        <div class="flex flex-wrap items-center gap-3 text-xs">
            ${taskStatusBadge(task)}
            <span class="font-semibold ${priority.text}">${escapeHtml(priority.label)} priority</span>
            <span class="text-gray-400">${taskDueLabel(task)}</span>
        </div>

        ${task.description
            ? `<div class="p-4 rounded-lg bg-[#06090F]/90 border border-white/5 text-gray-200 text-sm leading-relaxed github-readme-body break-words">
                ${renderTaskMarkdown(task.description)}
            </div>`
            : '<p class="text-sm text-gray-600 italic">No description.</p>'}

        ${taskProgressBar(task)}
        ${taskCommitDetails(task)}
        ${taskDeliverablesBody(task, submissions)}

        <div>
            <h4 class="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-1">Assigned to</h4>
            <div class="divide-y divide-white/5">${assigneeRows}</div>
        </div>

        <div class="flex flex-wrap gap-2 pt-2 border-t border-white/5">
            ${mine && !isDone && (mine.done || task.delivery_requirement !== 'document') ? `
                <button type="button" data-action="${mine.done ? 'uncomplete' : 'complete'}"
                    data-id="${escapeHtml(task.id)}"
                    class="${mine.done
                        ? 'border border-dark-border text-gray-300 hover:text-white'
                        : 'bg-brand-green hover:bg-green-500 text-black font-semibold'} px-4 py-2 rounded-lg text-sm transition-colors">
                    ${mine.done
                        ? '<i class="fas fa-rotate-left mr-2"></i>Reopen my part'
                        : '<i class="fas fa-check mr-2"></i>Mark my part done'}
                </button>` : ''}
            ${TASK_CAN_MANAGE && inReview ? `
                <button type="button" data-action="approve" data-id="${escapeHtml(task.id)}"
                    class="bg-green-600 hover:bg-green-500 text-white px-4 py-2 rounded-lg text-sm transition-colors">
                    <i class="fas fa-check mr-2"></i>Approve
                </button>` : ''}
            ${TASK_CAN_MANAGE && (inReview || isDone) ? `
                <button type="button" data-action="reopen" data-id="${escapeHtml(task.id)}"
                    class="border border-red-500/40 text-red-400 hover:bg-red-500/10 px-4 py-2 rounded-lg text-sm transition-colors">
                    Send back
                </button>` : ''}
            ${TASK_CAN_MANAGE ? `
                <button type="button" data-action="edit-task" data-id="${escapeHtml(task.id)}"
                    class="border border-dark-border text-gray-300 hover:text-white px-4 py-2 rounded-lg text-sm transition-colors">
                    Edit
                </button>
                <button type="button" data-action="delete-task" data-id="${escapeHtml(task.id)}"
                    class="text-red-400 hover:text-red-300 px-4 py-2 rounded-lg text-sm transition-colors">
                    Delete
                </button>` : ''}
        </div>

        <div>
            <h4 class="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-4">Activity</h4>
            <div class="space-y-4">${activity.map(taskActivityRow).join('')}</div>
        </div>

        <div class="pt-2">
            <textarea id="taskCommentBody" rows="2" placeholder="Add a comment"
                class="w-full bg-[#06090F] border border-dark-border rounded-lg px-4 py-3 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-brand-blue transition-colors resize-y"></textarea>
            <button type="button" data-action="comment" data-id="${escapeHtml(task.id)}"
                class="mt-2 px-4 py-2 text-sm rounded-lg border border-dark-border text-gray-300 hover:text-white hover:bg-white/5 transition-colors">
                Comment
            </button>
        </div>
    </div>`;
}

async function openTaskDetail(id) {
    try {
        const [task, activity, submissions] = await Promise.all([
            taskApi(`/tasks/${id}/`),
            taskApi(`/tasks/${id}/activity/`),
            taskApi(`/tasks/${id}/deliverables/`),
        ]);
        openTaskModal(task.title, taskDetailBody(task, activity, submissions));
    } catch (e) { toastApiError(e, 'The task could not be opened.'); }
}

/* ---------- create / edit form ---------- */

function taskFormBody(task) {
    const selected = new Set((task ? task.assignees : []).map(a => a.id));
    // Selectable cards rather than a bare checkbox list: assigning is the
    // decision this form exists for, and it deserves more than a column of
    // native ticks. The checkbox stays as the real control so the label,
    // keyboard and form-reading code all keep working.
    const people = TASK_PEOPLE.length
        ? TASK_PEOPLE.map(p => `
            <label class="flex items-center gap-3 p-2 rounded-lg cursor-pointer hover:bg-white/5 transition-colors">
                <input type="checkbox" class="task-assignee accent-brand-blue w-4 h-4" value="${escapeHtml(p.id)}"
                    ${selected.has(p.id) ? 'checked' : ''}>
                <span class="w-8 h-8 rounded-full bg-white/5 border border-white/10 text-gray-400
                    text-xs font-bold flex items-center justify-center shrink-0">
                    ${escapeHtml((p.username || '?').charAt(0).toUpperCase())}
                </span>
                <span class="text-sm text-gray-300 truncate">${escapeHtml(p.username)}</span>
            </label>`).join('')
        : '<p class="text-sm text-gray-600 italic p-2">No staff accounts to assign yet.</p>';

    const field = 'w-full bg-[#06090F] border border-dark-border rounded-lg px-4 py-2.5 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-brand-blue transition-colors';
    const label = 'block text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2';

    return `
    <div class="space-y-5">
        <div>
            <label class="${label}">Title</label>
            <input type="text" id="taskFormTitle" class="${field}" placeholder="What needs doing"
                value="${escapeHtml(task ? task.title : '')}">
        </div>
        <div>
            <label class="${label}">Description</label>
            <textarea id="taskFormDescription" rows="4" class="${field} resize-y"
                placeholder="Any detail the assignees will need">${escapeHtml(task ? task.description : '')}</textarea>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
                <label class="${label}">Priority</label>
                <select id="taskFormPriority" class="${field}">
                    ${[[4, 'Urgent'], [3, 'High'], [2, 'Normal'], [1, 'Low']].map(([v, l]) =>
                        `<option value="${v}" ${(task ? task.priority : 2) === v ? 'selected' : ''}>${l}</option>`
                    ).join('')}
                </select>
            </div>
            <div>
                <label class="${label}">Due date</label>
                <input type="date" id="taskFormDue" class="${field}"
                    value="${escapeHtml(task && task.due_date ? task.due_date : '')}">
            </div>
        </div>
        <div>
            <label for="taskFormDelivery" class="${label}">Delivery requirement</label>
            <select id="taskFormDelivery" class="${field}">
                ${[['standard', 'Standard (existing completion)'], ['document', 'Document required'], ['code', 'Attributed code commit required'], ['either', 'Document or attributed code']].map(([value, text]) => `<option value="${value}" ${(task ? task.delivery_requirement : 'standard') === value ? 'selected' : ''}>${text}</option>`).join('')}
            </select>
            <p class="text-xs text-gray-500 mt-1">Existing tasks keep their current workflow. Requirements cannot change after submission or completion.</p>
        </div>
        <div>
            <label class="${label}">Assign to</label>
            <div class="max-h-52 overflow-y-auto bg-[#06090F] border border-dark-border rounded-lg p-2 space-y-0.5">
                ${people}
            </div>
        </div>
        <div class="flex flex-wrap gap-2 pt-2 border-t border-white/5">
            <button type="button" data-action="save-task" data-id="${escapeHtml(task ? task.id : '')}"
                class="bg-brand-green hover:bg-green-500 text-black font-semibold px-5 py-2.5 rounded-lg text-sm transition-colors">
                ${task ? 'Save changes' : 'Create task'}
            </button>
            <button type="button" data-action="cancel-task"
                class="border border-dark-border text-gray-300 hover:text-white px-5 py-2.5 rounded-lg text-sm transition-colors">
                Cancel
            </button>
        </div>
    </div>`;
}

async function saveTask(id) {
    const assigneeIds = Array.from(document.querySelectorAll('.task-assignee'))
        .filter(box => box.checked)
        .map(box => Number(box.value));

    const due = document.getElementById('taskFormDue').value;
    const payload = {
        title: document.getElementById('taskFormTitle').value,
        description: document.getElementById('taskFormDescription').value,
        priority: Number(document.getElementById('taskFormPriority').value),
        delivery_requirement: document.getElementById('taskFormDelivery').value,
        // An empty date input reads as ''. DRF rejects that for a DateField;
        // null is how "no due date" is spelled.
        due_date: due || null,
        assignee_ids: assigneeIds,
    };

    try {
        await taskApi(id ? `/tasks/${id}/` : '/tasks/', {
            method: id ? 'PATCH' : 'POST',
            body: JSON.stringify(payload),
        });
        closeTaskModal();
        toast.success(id ? 'Task updated.' : 'Task created.');
        await loadTasks();
    } catch (e) { toastApiError(e, 'The task could not be saved.'); }
}

/* ---------- actions ---------- */

async function runTaskAction(action, id, userId) {
    if (action === 'complete' || action === 'admin-done') {
        return taskApi(`/tasks/${id}/complete/`, {
            method: 'POST',
            body: JSON.stringify(userId ? { assignee_id: Number(userId) } : {}),
        });
    }
    if (action === 'uncomplete' || action === 'admin-undone') {
        return taskApi(`/tasks/${id}/uncomplete/`, {
            method: 'POST',
            body: JSON.stringify(userId ? { assignee_id: Number(userId) } : {}),
        });
    }
    if (action === 'approve') {
        return taskApi(`/tasks/${id}/approve/`, { method: 'POST', body: '{}' });
    }
    if (action === 'reopen') {
        const reason = prompt('What still needs doing?');
        if (!reason) return null;
        return taskApi(`/tasks/${id}/reopen/`, {
            method: 'POST',
            body: JSON.stringify({ reason }),
        });
    }
    if (action === 'delete-task') {
        if (!await tkConfirm('The task and its full activity history are removed permanently.', { title: 'Delete this task?', confirmText: 'Delete', danger: true })) return null;
        return taskApi(`/tasks/${id}/`, { method: 'DELETE' });
    }
    if (action === 'comment') {
        const body = document.getElementById('taskCommentBody').value.trim();
        if (!body) return null;
        return taskApi(`/tasks/${id}/activity/`, {
            method: 'POST',
            body: JSON.stringify({ body }),
        });
    }
    return null;
}

/* ---------- wiring ---------- */

document.addEventListener('DOMContentLoaded', () => {
    const section = document.getElementById('tasks');
    const modal = document.getElementById('taskModal');
    if (!section) return;

    section.addEventListener('click', async (event) => {
        const tab = event.target.closest('.task-tab');
        if (tab) {
            TASK_TAB = tab.dataset.tab;
            document.querySelectorAll('.task-tab').forEach(button => {
                const on = button === tab;
                button.classList.toggle('bg-brand-blue/15', on);
                button.classList.toggle('text-white', on);
                button.classList.toggle('text-gray-400', !on);
                button.classList.toggle('hover:text-white', !on);
            });
            await loadTasks();
            return;
        }

        const card = event.target.closest('[data-action="open-task"]');
        if (card) { await openTaskDetail(card.dataset.id); return; }

        if (event.target.closest('#newTaskBtn')) {
            openTaskModal('New task', taskFormBody(null));
        }
    });

    document.getElementById('taskListMore').addEventListener('click', async (event) => {
        if (!TASK_NEXT) return;
        event.target.disabled = true;
        try { await loadTaskPage(TASK_NEXT, true); }
        catch (e) { toastApiError(e, 'The next page of tasks could not be loaded.'); }
        finally { event.target.disabled = false; }
    });

    // Debounced so a search does not fire a request per keystroke.
    let searchTimer = null;
    document.getElementById('taskSearch').addEventListener('input', (event) => {
        clearTimeout(searchTimer);
        const value = event.target.value.trim();
        searchTimer = setTimeout(() => {
            TASK_SEARCH = value;
            loadTasks();
        }, 300);
    });

    document.getElementById('taskModalClose').addEventListener('click', closeTaskModal);
    modal.addEventListener('click', (event) => {
        if (event.target === modal) closeTaskModal();
    });

    modal.addEventListener('click', async (event) => {
        const button = event.target.closest('[data-action]');
        if (!button) return;
        const { action, id, user } = button.dataset;
        if (action.startsWith('deliverable-')) { await taskDeliverableAction(button); return; }

        if (action === 'cancel-task') { closeTaskModal(); return; }
        if (action === 'save-task') { await saveTask(id); return; }
        if (action === 'edit-task') {
            const task = await taskApi(`/tasks/${id}/`);
            openTaskModal('Edit task', taskFormBody(task));
            return;
        }

        button.disabled = true;
        try {
            const result = await runTaskAction(action, id, user);
            if (result === null) return;
            if (action === 'delete-task') closeTaskModal();
            else await openTaskDetail(id);
            await loadTasks();
        } catch (e) {
            toastApiError(e, 'That action could not be completed.');
        } finally {
            button.disabled = false;
        }
    });

    // The badge has to be right before anyone opens the section, otherwise
    // nobody learns there is work waiting for them.
    refreshTaskSummary();
});


// Only generated GitHub URLs are navigable, even if a webhook supplied the URL.
function taskGithubLink(url, label) {
    try {
        const parsed = new URL(url);
        if (parsed.protocol === 'https:' && parsed.hostname === 'github.com' && !parsed.username && !parsed.password) {
            return `<a href="${escapeHtml(parsed.href)}" target="_blank" rel="noopener noreferrer" class="text-brand-blue hover:underline">${escapeHtml(label)}</a>`;
        }
    } catch (e) { /* Render a plain label for invalid URLs. */ }
    return escapeHtml(label);
}

function taskCommitDetails(task) {
    return `<div class="text-sm text-gray-400">
        <p>Task #${escapeHtml(task.id)}${task.repository_name ? ` · ${escapeHtml(task.repository_name)} · ${escapeHtml(task.source_display)}` : ''}</p>
        <h4 class="font-semibold text-white mt-3">Commits</h4>
        ${(task.commits || []).length ? task.commits.map(c => `<div class="py-2 border-b border-white/5">
            ${taskGithubLink(c.url, c.short_sha)} ${escapeHtml(c.title)}
            <p class="text-xs">${escapeHtml(c.author_name)} · ${c.on_default_branch ? 'On default branch' : 'Not merged yet'}${c.finishes ? ' · Submitted for review' : ''}</p>
        </div>`).join('') : '<p>No linked commits yet. Reference this task in commits using Task # followed by its number.</p>'}
    </div>`;
}


function taskBacklogRow(task) {
    const project = task.project_title || task.repository_name || 'Roadmap';
    const priority = taskPriority(task);
    return `<div class="flex flex-col sm:flex-row sm:items-center gap-4 px-5 py-4 hover:bg-white/[0.02] transition-colors">
        <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2 text-xs text-gray-500 mb-1.5">
                <span class="font-mono">#${escapeHtml(task.id)}</span><span aria-hidden="true">/</span><span>${escapeHtml(project)}</span>${task.source === 'documentation' ? '<span class="text-amber-300 bg-amber-500/10 rounded px-2 py-0.5">Documentation</span>' : '<span class="text-gray-400 bg-white/5 rounded px-2 py-0.5">Roadmap</span>'}
            </div>
            <button type="button" data-action="open-task" data-id="${escapeHtml(task.id)}" class="text-left text-sm font-semibold text-white hover:text-brand-blue break-words">${escapeHtml(task.title)}</button>
            <p class="text-xs text-gray-500 mt-1.5 truncate" title="${escapeHtml(task.roadmap_context)}">${escapeHtml(task.roadmap_context)}</p>
        </div>
        <div class="flex items-center justify-between sm:justify-end gap-5 shrink-0">
            <span class="text-xs ${priority.text}">${escapeHtml(priority.label)}</span>
            ${TASK_CAN_MANAGE ? `<button type="button" data-assign-backlog="${escapeHtml(task.id)}" class="text-sm font-medium text-brand-blue border border-brand-blue/30 hover:bg-brand-blue/10 focus-visible:outline focus-visible:outline-brand-blue px-4 py-2 rounded-lg transition-colors">Assign<span class="sr-only"> ${escapeHtml(task.title)}</span></button>` : '<span class="text-xs text-gray-500">Awaiting assignment</span>'}
        </div>
    </div>`;
}

function taskWorkspace(workspace) {
    TASK_WORKSPACE = workspace;
    TASK_ROWS = [];
    TASK_NEXT = null;
    ++TASK_REQUEST;
    const backlog = workspace === 'backlog';
    document.querySelectorAll('.task-workspace').forEach(button => {
        const active = button.dataset.workspace === workspace;
        button.setAttribute('aria-pressed', String(active));
        button.classList.toggle('border-brand-blue', active);
        button.classList.toggle('border-transparent', !active);
        button.classList.toggle('text-white', active);
        button.classList.toggle('text-gray-500', !active);
    });
    document.getElementById('taskStats').classList.toggle('hidden', backlog);
    document.getElementById('taskBoardFilters').classList.toggle('hidden', backlog);
    document.getElementById('taskBacklogIntro').classList.toggle('hidden', !backlog);
    document.getElementById('taskBacklogProjectLabel').classList.toggle('hidden', !backlog);
    document.getElementById('taskSearch').placeholder = backlog ? 'Search project tasks' : 'Search tasks';
}

async function loadTaskBacklogProjects() {
    const status = document.getElementById('taskImportStatus');
    try {
        TASK_PROJECTS = await taskApi('/backlog-projects/');
        const picker = document.getElementById('taskBacklogProject');
        picker.innerHTML = '<option value="">All projects</option>' + TASK_PROJECTS.map(p => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.title)} (${escapeHtml(p.awaiting)})</option>`).join('');
        picker.value = TASK_PROJECT;
        const checked = TASK_PROJECTS.map(p => p.last_checked_at).filter(Boolean).sort();
        const errors = TASK_PROJECTS.filter(p => p.has_error).length;
        status.textContent = !TASK_PROJECTS.length
            ? 'Roadmap work and documentation issues from synced GitHub projects appear on the next scheduled check.'
            : `${TASK_PROJECTS.length} projects · Imported automatically · ${checked.length ? 'Last checked ' + new Date(checked.at(-1)).toLocaleString() : 'Waiting for first check'}${errors ? ` · ${errors} projects could not sync; the next check will retry` : ''}`;
    } catch (e) { status.textContent = `Import status unavailable: ${e.message}`; }
}

async function openTaskAssignment(id) {
    try {
        const task = await taskApi(`/tasks/${id}/`);
        if (task.assignees.length) {
            document.getElementById('taskBacklogFeedback').textContent = 'This item has already been assigned. The backlog has been refreshed.';
            await loadTasks();
            return;
        }
        const people = await taskApi('/assignable/');
        openTaskModal('Assign backlog item', `<div class="space-y-5">
            <div><p class="text-xs text-gray-500 mb-2">${escapeHtml(task.project_title || task.repository_name)} · #${escapeHtml(task.id)}</p><h4 class="text-white font-semibold">${escapeHtml(task.title)}</h4></div>
            <fieldset><legend class="text-sm text-gray-300 mb-3">Who will take this on?</legend>
                <div class="max-h-64 overflow-y-auto divide-y divide-white/5">${people.length ? people.map(person => `<label class="flex items-center gap-3 py-3 cursor-pointer"><input type="checkbox" class="task-backlog-assignee accent-brand-blue w-4 h-4" value="${escapeHtml(person.id)}"><span class="text-sm text-white">${escapeHtml(person.username)}</span></label>`).join('') : '<p class="text-sm text-gray-500">No active staff are available. Add staff before assigning work.</p>'}</div>
            </fieldset>
            <p id="taskAssignError" role="alert" class="text-sm text-red-400"></p>
            <div class="flex justify-end gap-3 border-t border-white/5 pt-4"><button type="button" data-action="cancel-task" class="text-gray-400 text-sm px-4 py-2">Cancel</button><button type="button" id="taskAssignSave" class="bg-brand-blue hover:bg-blue-500 text-white text-sm font-semibold rounded-lg px-5 py-2.5" ${people.length ? '' : 'disabled'}>Assign task</button></div>
        </div>`);
        document.getElementById('taskAssignSave').addEventListener('click', async event => {
            const assigneeIds = Array.from(document.querySelectorAll('.task-backlog-assignee:checked')).map(input => Number(input.value));
            const error = document.getElementById('taskAssignError');
            if (!assigneeIds.length) { error.textContent = 'Choose at least one person.'; return; }
            event.target.disabled = true;
            try {
                await taskApi(`/tasks/${id}/assign/`, { method: 'POST', body: JSON.stringify({ assignee_ids: assigneeIds }) });
                closeTaskModal();
                document.getElementById('taskBacklogFeedback').textContent = `Assigned “${task.title}”. You can follow its progress in Team tasks.`;
                await loadTasks();
            } catch (e) { error.textContent = e.message; }
            finally { event.target.disabled = false; }
        });
    } catch (e) { toastApiError(e, 'Could not open assignment.'); }
}

document.addEventListener('DOMContentLoaded', () => {
    const section = document.getElementById('tasks');
    if (!section) return;
    taskWorkspace(TASK_WORKSPACE);
    section.addEventListener('click', async event => {
        const workspace = event.target.closest('[data-workspace]');
        if (workspace) {
            taskWorkspace(workspace.dataset.workspace);
            const url = new URL(window.location.href);
            url.searchParams.set('task_view', TASK_WORKSPACE);
            window.history.replaceState(null, '', url);
            await loadTasks();
        }
        const assign = event.target.closest('[data-assign-backlog]');
        if (assign) await openTaskAssignment(assign.dataset.assignBacklog);
    });
    document.getElementById('taskBacklogProject').addEventListener('change', async event => {
        TASK_PROJECT = event.target.value;
        await loadTasks();
    });
    document.getElementById('taskBacklogRefresh').addEventListener('click', async event => {
        event.currentTarget.disabled = true;
        try { await loadTasks(); }
        finally { document.getElementById('taskBacklogRefresh').disabled = false; }
    });
    document.getElementById('taskModal').addEventListener('keydown', event => {
        if (event.key === 'Escape') closeTaskModal();
        if (event.key !== 'Tab') return;
        const nodes = Array.from(document.getElementById('taskModal').querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href]'));
        const first = nodes[0], last = nodes.at(-1);
        if (event.shiftKey && document.activeElement === first) { last.focus(); event.preventDefault(); }
        else if (!event.shiftKey && document.activeElement === last) { first.focus(); event.preventDefault(); }
    });
});
