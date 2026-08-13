const API_BASE_URL = '/api';

function el(id) {
    return document.getElementById(id);
}

function escHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str).replace(/[&<>"']/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[m]));
}

function fmtPct(x) {
    return x === null || x === undefined ? '—' : `${Math.round(x * 1000) / 10}%`;
}
function fmtNum(x, decimals = 0) {
    return x === null || x === undefined ? '—' : Number(x).toFixed(decimals);
}
function fmtScore10(x) {
    return x === null || x === undefined ? '—' : `${Number(x).toFixed(1)}/10`;
}
function fmtScore100(x) {
    return x === null || x === undefined ? '—' : `${Number(x).toFixed(1)}/100`;
}

function tile(label, value, cls = 'accent', meta = '') {
    return `
        <div class="kpi-tile">
            <div class="kpi-tile-label">${escHtml(label)}</div>
            <div class="kpi-tile-value ${cls}">${escHtml(value)}</div>
            ${meta ? `<div class="kpi-tile-meta">${escHtml(meta)}</div>` : ''}
        </div>
    `;
}

function renderKpis(k) {
    el('kpiSubtitle').textContent = `"Actif" = a créé une session CV ou un entretien dans les ${k.active_window_days} derniers jours.`;
    el('kpiGrid').innerHTML = [
        tile('Élèves', fmtNum(k.nb_students)),
        tile('Élèves actifs', fmtNum(k.active_students)),
        tile('Entretiens démarrés', fmtNum(k.interviews_started)),
        tile('Entretiens terminés', fmtNum(k.interviews_completed)),
        tile('Taux de complétion', fmtPct(k.completion_rate)),
        tile('Score moyen', fmtScore10(k.average_score)),
        tile('Tokens utilisés aujourd\'hui', fmtNum(k.tokens_used_today)),
        tile('Pool bonus restant ce mois', fmtNum(k.monthly_bonus_tokens_remaining), 'accent', `sur ${fmtNum(k.monthly_bonus_token_pool)} tokens`),
    ].join('');
}

function renderWeakest(weakest) {
    if (!weakest.by_name || weakest.by_name.length === 0) {
        el('weakestTableBody').innerHTML = '<tr><td colspan="3">Aucune compétence évaluée pour l\'instant sur ce pool.</td></tr>';
        return;
    }
    el('weakestTableBody').innerHTML = weakest.by_name.map((c) => `
        <tr>
            <td><div class="weak-name">${escHtml(c.name)}</div><div class="weak-category">${escHtml(c.category)}</div></td>
            <td>${fmtScore100(c.average_score)}</td>
            <td>${c.nb_students}</td>
        </tr>
    `).join('');
}

function renderTokenBonusEditor(studentId, bonus) {
    return `
        <div class="token-bonus-editor" data-student="${studentId}">
            <input type="number" class="token-bonus-input" min="0" step="1000" value="${bonus}">
            <button type="button" class="token-bonus-save">${mIcon('check')}</button>
        </div>
    `;
}

function renderStudentsTable(students) {
    el('studentsTableBody').innerHTML = students.map((s) => {
        const nearLimit = s.tokens_used_today >= s.daily_token_limit;
        return `
        <tr>
            <td>${escHtml(s.email)}</td>
            <td>${escHtml((s.created_at || '').slice(0, 10))}</td>
            <td>${s.nb_sessions}</td>
            <td>${s.nb_interviews}</td>
            <td>${fmtScore10(s.average_score)}</td>
            <td class="${nearLimit ? 'token-usage-full' : ''}">${fmtNum(s.tokens_used_today)} / ${fmtNum(s.daily_token_limit)}</td>
            <td>${renderTokenBonusEditor(s.id, s.bonus_daily_token_limit)}</td>
        </tr>
    `;
    }).join('');

    el('studentsTableBody').querySelectorAll('.token-bonus-editor').forEach((editor) => {
        const studentId = editor.dataset.student;
        editor.querySelector('.token-bonus-save').addEventListener('click', () => saveTokenBonus(studentId, editor));
    });
}

async function saveTokenBonus(studentId, editorEl) {
    const input = editorEl.querySelector('.token-bonus-input');
    const value = Math.max(0, parseInt(input.value, 10) || 0);
    editorEl.querySelectorAll('button, input').forEach((el2) => { el2.disabled = true; });

    try {
        const response = await window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/school/students/${studentId}/token-bonus`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bonus_daily_token_limit: value }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Erreur');
        input.value = data.bonus_daily_token_limit;
    } catch (error) {
        alert(error.message);
    } finally {
        editorEl.querySelectorAll('button, input').forEach((el2) => { el2.disabled = false; });
    }
}

async function submitBulkCredits(event) {
    event.preventDefault();
    const status = el('bulkSaveStatus');
    const formData = new FormData(event.target);

    const raw = formData.get('bonus_daily_token_limit_delta');
    if (raw === '' || raw === null) {
        status.textContent = 'Renseigne un delta de tokens.';
        return;
    }

    status.textContent = 'Application...';
    try {
        const response = await window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/school/token-bonus/bulk`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bonus_daily_token_limit_delta: parseInt(raw, 10) }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Erreur');

        status.innerHTML = `Appliqué à ${data.nb_students} élève(s) ${mIcon('check-circle')}`;
        event.target.reset();
        loadDashboard({ silent: true });
    } catch (error) {
        status.textContent = error.message;
    }
}

async function loadDashboard(opts = {}) {
    const me = await window.MocklyAuth.getCurrentUser();
    if (!me || !me.user.is_school_admin) {
        el('schoolLocked').classList.remove('hidden');
        el('schoolContent').classList.add('hidden');
        return;
    }

    el('schoolLocked').classList.add('hidden');
    el('schoolContent').classList.remove('hidden');

    if (!opts.silent) {
        el('refreshBtn').disabled = true;
        el('refreshBtn').innerHTML = `${mIcon('refresh-cw', 'icon-spin')} Chargement...`;
    }

    try {
        const response = await window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/school/dashboard`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Impossible de charger le tableau de bord');

        el('schoolName').textContent = `${data.school.name} — ${data.kpis.nb_students} élève(s)`;
        renderKpis(data.kpis);
        renderWeakest(data.weakest_competencies);
        renderStudentsTable(data.students);
    } catch (error) {
        el('schoolContent').innerHTML = `<div class="school-locked">${mIcon('alert-triangle')} ${escHtml(error.message)}</div>`;
    } finally {
        el('refreshBtn').disabled = false;
        el('refreshBtn').innerHTML = `${mIcon('refresh-cw')} Rafraîchir`;
    }
}

function initSchoolPage() {
    el('refreshBtn').addEventListener('click', () => loadDashboard());
    el('bulkCreditForm').addEventListener('submit', submitBulkCredits);
    loadDashboard();
}

document.addEventListener('DOMContentLoaded', initSchoolPage);
