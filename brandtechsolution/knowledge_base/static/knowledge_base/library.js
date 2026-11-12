/* Progressive enhancement only: native links, forms and validation still work. */
(() => {
    'use strict';
    const MAX_BYTES = 25 * 1024 * 1024;
    const EXTENSIONS = new Set(['pdf', 'docx', 'txt', 'md', 'png', 'jpg', 'jpeg']);

    function bindUpload(form) {
        if (!form || form.dataset.bound) return;
        form.dataset.bound = 'true';
        const input = form.querySelector('input[type="file"]');
        const dropzone = form.querySelector('[data-dropzone]');
        const feedback = form.querySelector('[data-file-feedback]');
        const progressArea = form.querySelector('[data-upload-progress]');
        const progress = progressArea.querySelector('progress');
        const status = form.querySelector('[data-upload-status]');
        const submit = form.querySelector('button[type="submit"]');
        let busy = false;
        let lockedControls = [];

        function describeFile() {
            const file = input.files[0];
            input.setCustomValidity('');
            feedback.classList.remove('is-error');
            if (!file) { feedback.textContent = ''; return; }
            const extension = file.name.split('.').pop().toLowerCase();
            let error = '';
            if (!EXTENSIONS.has(extension)) error = 'Choose a PDF, DOCX, TXT, Markdown, PNG or JPEG document.';
            else if (!file.size || file.size > MAX_BYTES) error = 'Choose a document between 1 byte and 25 MB.';
            if (error) {
                input.setCustomValidity(error);
                feedback.textContent = error;
                feedback.classList.add('is-error');
            } else {
                const size = file.size < 1024 * 1024 ? `${Math.max(1, Math.round(file.size / 1024))} KB` : `${(file.size / 1024 / 1024).toFixed(1)} MB`;
                feedback.textContent = `${file.name} · ${size} · ready to upload`;
            }
        }
        input.addEventListener('change', describeFile);
        for (const eventName of ['dragenter', 'dragover']) {
            dropzone.addEventListener(eventName, event => {
                event.preventDefault();
                if (!busy) dropzone.classList.add('is-dragging');
            });
        }
        for (const eventName of ['dragleave', 'drop']) {
            dropzone.addEventListener(eventName, event => {
                event.preventDefault();
                dropzone.classList.remove('is-dragging');
            });
        }
        dropzone.addEventListener('drop', event => {
            if (busy || !event.dataTransfer.files.length) return;
            if (event.dataTransfer.files.length !== 1) {
                input.value = '';
                feedback.textContent = 'Please add one document at a time.';
                feedback.classList.add('is-error');
                return;
            }
            input.files = event.dataTransfer.files;
            describeFile();
        });

        function reset(message) {
            busy = false;
            lockedControls.forEach(control => { control.disabled = false; });
            lockedControls = [];
            submit.disabled = false;
            form.removeAttribute('aria-busy');
            status.textContent = message;
            progress.hidden = true;
        }
        form.addEventListener('submit', event => {
            if (!window.XMLHttpRequest || !window.FormData) return;
            event.preventDefault();
            if (busy) return;
            describeFile();
            if (!form.reportValidity()) return;
            const payload = new FormData(form);
            busy = true;
            form.setAttribute('aria-busy', 'true');
            lockedControls = Array.from(form.elements).filter(control => !control.disabled);
            lockedControls.forEach(control => { control.disabled = true; });
            progressArea.hidden = false;
            status.textContent = 'Uploading your document…';
            progress.hidden = false;
            progress.value = 0;
            const xhr = new XMLHttpRequest();
            xhr.open('POST', form.action || window.location.href);
            xhr.timeout = 120000;
            xhr.upload.addEventListener('progress', event => {
                if (!event.lengthComputable) { progress.removeAttribute('value'); return; }
                const percent = Math.round(event.loaded / event.total * 100);
                progress.value = percent;
                status.textContent = percent === 100 ? 'Upload received. Waiting for server validation…' : `Uploading… ${percent}%`;
            });
            xhr.addEventListener('load', () => {
                const target = new URL(xhr.responseURL || window.location.href);
                if (xhr.status >= 200 && xhr.status < 300 && target.origin === window.location.origin && /\/library\/\d+\/$/.test(target.pathname)) {
                    status.textContent = 'Document saved privately. Opening document…';
                    window.location.assign(target.href);
                    return;
                }
                if (xhr.status === 200) {
                    const page = new DOMParser().parseFromString(xhr.responseText, 'text/html');
                    const replacement = page.querySelector('[data-library-upload]');
                    if (replacement) {
                        form.replaceWith(replacement);
                        bindUpload(replacement);
                        const error = replacement.querySelector('.errorlist');
                        if (error) { error.setAttribute('tabindex', '-1'); error.focus(); }
                        return;
                    }
                }
                reset(xhr.status === 403 ? 'Your session or security token expired. Reload this page before uploading again.' : 'The server did not confirm a saved document. Check your library before retrying.');
            });
            xhr.addEventListener('error', () => reset('Connection lost. Check your library before retrying; upload success was not confirmed.'));
            xhr.addEventListener('timeout', () => reset('The upload timed out. Check your library before retrying; upload success was not confirmed.'));
            // Payload was captured before controls were locked, including file and CSRF.
            xhr.send(payload);
        });
    }
    bindUpload(document.querySelector('[data-library-upload]'));
    document.querySelectorAll('[data-open-sharing]').forEach(link => {
        link.addEventListener('click', () => {
            const section = document.getElementById('sharing');
            if (section) section.open = true;
        });
    });
})();
