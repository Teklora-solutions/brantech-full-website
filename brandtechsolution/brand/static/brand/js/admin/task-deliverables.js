// Private assignment evidence. All server/user text is escaped; no inline handlers.
function taskDeliverablesBody(task, submissions) {
    const field = 'w-full bg-dark-bg border border-dark-border rounded-lg px-3 py-2 text-sm text-white';
    const button = 'px-3 py-2 rounded-lg border border-dark-border text-sm hover:bg-white/5';
    const latest = submissions.find(s => s.mine && s.current);
    const history = submissions.map(s => `<article class="border border-dark-border rounded-lg p-3 space-y-2">
        <h5 class="font-semibold text-sm">${escapeHtml(s.submitter)} · revision ${escapeHtml(s.revision)}
            <span class="text-xs text-gray-400">${s.current ? escapeHtml(s.state.replaceAll('_', ' ')) : 'Previous submission'} · ${escapeHtml(new Date(s.created_at).toLocaleString())}</span></h5>
        <p class="text-sm whitespace-pre-wrap break-words">${escapeHtml(s.note)}</p>
        <ul class="text-sm space-y-1">${s.attachments.map(a => `<li>${a.available
            ? `<a class="text-brand-blue underline" href="${escapeHtml(a.download_url)}">${escapeHtml(a.filename)} · version ${escapeHtml(a.version_number)}</a>`
            : '<span class="text-red-400">Evidence unavailable — a replacement submission is required</span>'}</li>`).join('')}</ul>
        ${s.reviews.map(r => `<div class="text-sm border-l-2 border-brand-blue pl-3"><strong>${escapeHtml(r.decision.replaceAll('_', ' '))}</strong> · ${escapeHtml(r.reviewer)}<p class="whitespace-pre-wrap break-words">${escapeHtml(r.feedback)}</p></div>`).join('')}
        ${TASK_CAN_MANAGE && task.status !== 'done' && s.current && s.state !== 'changes_requested' ? `
            <label for="task-deliverable-feedback-${escapeHtml(s.id)}" class="block text-xs">Review feedback (required when requesting changes)</label>
            <textarea id="task-deliverable-feedback-${escapeHtml(s.id)}" maxlength="5000" rows="2" class="${field}"></textarea>
            <div class="flex flex-wrap gap-2"><button type="button" class="${button}" data-action="deliverable-accept" data-id="${task.id}" data-submission="${s.id}">Accept submission</button>
            <button type="button" class="${button}" data-action="deliverable-changes" data-id="${task.id}" data-submission="${s.id}">Request changes</button></div>` : ''}
    </article>`).join('');
    return `<section class="space-y-3 border-t border-dark-border pt-4" aria-labelledby="task-deliverables-heading">
        <h4 id="task-deliverables-heading" class="font-semibold">Deliverables</h4>
        <p class="text-sm text-gray-400">Delivery: ${escapeHtml(task.delivery_requirement || 'standard')}. Documents are private to their submitter and active task managers. Submission does not authorize AI processing or public use.</p>
        ${history || '<p class="text-sm text-gray-400">No submissions visible to you. Other assignees’ private documents are not shown.</p>'}
        ${task.my_assignment && task.status !== 'done' ? `<div id="task-deliverable-form" class="space-y-3" data-expected="${latest ? latest.id : ''}" data-request="${crypto.randomUUID()}">
            <h5 class="text-sm font-semibold">${latest ? 'Submit a revision' : 'Submit document work'}</h5>
            <div class="border border-dark-border rounded-lg p-3 space-y-2">
                <label for="task-evidence-title" class="block text-xs">Document title</label><input id="task-evidence-title" maxlength="300" class="${field}">
                <label for="task-evidence-file" class="block text-xs">Upload document · maximum 25 MB · PDF, DOCX, TXT, Markdown, PNG/JPEG</label>
                <input id="task-evidence-file" type="file" accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg" class="block w-full text-sm">
                <label class="flex items-start gap-2 text-sm"><input id="task-evidence-authority" type="checkbox" class="mt-1">I confirm authority to upload this document.</label>
                <button type="button" class="${button}" data-action="deliverable-upload" data-id="${task.id}">Upload privately and attach</button>
                <progress id="task-evidence-progress" max="100" value="0" class="hidden w-full" aria-label="Document upload progress"></progress>
                <p class="text-xs text-gray-400">Upload alone does not complete the task. A successful upload remains in your library if submission fails.</p>
            </div>
            <div class="flex flex-wrap gap-2"><label for="task-evidence-search" class="sr-only">Search your shareable library documents</label>
                <input id="task-evidence-search" class="${field}" placeholder="Search shareable library documents">
                <button type="button" class="${button}" data-action="deliverable-search" data-id="${task.id}">Choose from library</button></div>
            <div id="task-evidence-results" class="space-y-2"></div>
            <fieldset class="space-y-2"><legend class="text-sm font-semibold">Selected attachments (up to 10)</legend><div id="task-evidence-selected" class="space-y-2"></div></fieldset>
            <label for="task-evidence-note" class="block text-xs">Submission note</label><textarea id="task-evidence-note" maxlength="5000" rows="3" class="${field}"></textarea>
            <label class="flex items-start gap-2 text-sm"><input id="task-evidence-share" type="checkbox" class="mt-1">I agree to share these exact document versions with active task managers for private review.</label>
            <button type="button" class="${button} bg-brand-blue text-white" data-action="deliverable-submit" data-id="${task.id}">${latest ? 'Submit revision' : 'Submit work'} and mark my part complete</button>
        </div>` : ''}
        <p id="task-deliverable-status" class="text-sm whitespace-pre-wrap" role="status" aria-live="polite"></p>
    </section>`;
}

function taskEvidenceSelect(version, title, number) {
    if (document.querySelector(`.task-evidence-version[value="${Number(version)}"]`)) return;
    const selected = document.getElementById('task-evidence-selected');
    selected.insertAdjacentHTML('beforeend', `<label class="flex items-start gap-2 text-sm break-words"><input type="checkbox" checked class="task-evidence-version mt-1" value="${Number(version)}"><span>${escapeHtml(title)} · version ${escapeHtml(number)}</span></label>`);
}

function taskEvidenceUpload(id, form) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', `${TASK_API}/tasks/${id}/deliverable-upload/`);
        xhr.setRequestHeader('X-CSRFToken', CSRF_TOKEN);
        xhr.upload.onprogress = event => {
            const progress = document.getElementById('task-evidence-progress');
            if (progress && event.lengthComputable) { progress.classList.remove('hidden'); progress.value = event.loaded / event.total * 100; }
        };
        xhr.onerror = () => reject(new Error('Upload connection failed. Your selected file is preserved; retry the upload.'));
        xhr.onload = () => {
            let data;
            try { data = JSON.parse(xhr.responseText); } catch (_) { reject(new Error('Upload returned an unexpected response.')); return; }
            if (xhr.status >= 200 && xhr.status < 300) resolve(data);
            else reject(new Error(data.detail || Object.values(data).flat().join(' ') || 'Upload failed.'));
        };
        xhr.send(form);
    });
}

async function taskDeliverableAction(button) {
    const {action, id, submission} = button.dataset;
    const status = document.getElementById('task-deliverable-status');
    button.disabled = true;
    try {
        status.textContent = 'Working…';
        if (action === 'deliverable-upload') {
            const file = document.getElementById('task-evidence-file').files[0];
            if (!file || file.size > 25 * 1024 * 1024 || file.size === 0) throw new Error('Choose a document between 1 byte and 25 MB.');
            if (!document.getElementById('task-evidence-authority').checked) throw new Error('Confirm upload authority first.');
            const title = document.getElementById('task-evidence-title').value.trim();
            if (!title) throw new Error('Enter a document title.');
            const form = new FormData();
            form.append('original', file); form.append('title', title); form.append('authority', 'true');
            const data = await taskEvidenceUpload(id, form);
            taskEvidenceSelect(data.version_id, data.title, data.version_number);
            status.textContent = 'Uploaded privately and selected. Use Submit work to finish your submission.';
        } else if (action === 'deliverable-search' || action === 'deliverable-more') {
            const query = document.getElementById('task-evidence-search').value;
            const page = action === 'deliverable-more' ? Number(button.dataset.page) : 1;
            const data = await taskApi(`/tasks/${id}/deliverable-documents/?q=${encodeURIComponent(query)}&page=${page}`);
            const results = document.getElementById('task-evidence-results');
            if (page === 1) results.replaceChildren();
            else button.remove();
            for (const item of data.results) {
                const choice = document.createElement('button'); choice.type = 'button';
                choice.className = 'block text-left text-sm text-brand-blue underline py-1';
                choice.textContent = `Attach ${item.title} · version ${item.version_number}`;
                choice.addEventListener('click', () => taskEvidenceSelect(item.version_id, item.title, item.version_number));
                results.append(choice);
            }
            if (data.next_page) results.insertAdjacentHTML('beforeend', `<button type="button" data-action="deliverable-more" data-id="${Number(id)}" data-page="${Number(data.next_page)}">More documents</button>`);
            status.textContent = data.results.length ? 'Choose a document to attach.' : 'No shareable documents match your search.';
        } else if (action === 'deliverable-submit') {
            const form = document.getElementById('task-deliverable-form');
            const ids = Array.from(document.querySelectorAll('.task-evidence-version:checked')).map(e => Number(e.value));
            if (!ids.length || ids.length > 10) throw new Error('Select between 1 and 10 documents.');
            if (!document.getElementById('task-evidence-share').checked) throw new Error('Confirm sharing the selected versions with task managers.');
            await taskApi(`/tasks/${id}/deliverables/`, {method:'POST', body:JSON.stringify({
                version_ids:ids, note:document.getElementById('task-evidence-note').value,
                expected_submission_id:form.dataset.expected ? Number(form.dataset.expected) : null,
                request_id:form.dataset.request, share_confirmation:true,
            })});
            await openTaskDetail(id); await loadTasks();
            document.getElementById('task-deliverable-status').textContent = 'Work submitted for private review. Your assignment is complete; task approval is separate.';
        } else if (action === 'deliverable-accept' || action === 'deliverable-changes') {
            const feedback = document.getElementById(`task-deliverable-feedback-${submission}`).value;
            await taskApi(`/tasks/${id}/review-deliverable/`, {method:'POST', body:JSON.stringify({
                submission_id:Number(submission), decision:action === 'deliverable-accept' ? 'accepted' : 'changes_requested', feedback,
            })});
            await openTaskDetail(id); await loadTasks();
            document.getElementById('task-deliverable-status').textContent = 'Review saved. Task approval remains a separate action.';
        }
    } catch (error) {
        if (status.isConnected) status.textContent = error.message;
        else toastApiError(error, 'Deliverable action failed.');
    } finally { button.disabled = false; }
}
