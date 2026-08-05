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
        tile('Crédits Interview restants', fmtNum(k.total_interview_credits)),
        tile('Crédits Coach restants', fmtNum(k.total_coach_credits)),
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

function renderCreditStepper(studentId, kind, value) {
    const zeroClass = value <= 0 ? ' zero' : '';
    return `
        <div class="credit-stepper${zeroClass}" data-student="${studentId}" data-kind="${kind}">
            <button type="button" class="credit-minus" ${value <= 0 ? 'disabled' : ''}>−</button>
            <span class="credit-value">${value}</span>
            <button type="button" class="credit-plus">+</button>
        </div>
    `;
}

function renderStudentsTable(students) {
    el('studentsTableBody').innerHTML = students.map((s) => `
        <tr>
            <td>${escHtml(s.email)}</td>
            <td>${escHtml((s.created_at || '').slice(0, 10))}</td>
            <td>${s.nb_sessions}</td>
            <td>${s.nb_interviews}</td>
            <td>${fmtScore10(s.average_score)}</td>
            <td>${renderCreditStepper(s.id, 'interview_credits', s.interview_credits)}</td>
            <td>${renderCreditStepper(s.id, 'coach_credits', s.coach_credits)}</td>
        </tr>
    `).join('');

    el('studentsTableBody').querySelectorAll('.credit-stepper').forEach((stepper) => {
        const studentId = stepper.dataset.student;
        const kind = stepper.dataset.kind;
        stepper.querySelector('.credit-minus').addEventListener('click', () => adjustCredit(studentId, kind, stepper, -1));
        stepper.querySelector('.credit-plus').addEventListener('click', () => adjustCredit(studentId, kind, stepper, 1));
    });
}

async function adjustCredit(studentId, kind, stepperEl, delta) {
    const currentValue = parseInt(stepperEl.querySelector('.credit-value').textContent, 10);
    const newValue = Math.max(0, currentValue + delta);

    stepperEl.querySelectorAll('button').forEach((b) => { b.disabled = true; });

    try {
        const response = await window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/school/students/${studentId}/credits`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ [kind]: newValue }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Erreur');

        const updated = data[kind];
        stepperEl.querySelector('.credit-value').textContent = updated;
        stepperEl.classList.toggle('zero', updated <= 0);
        stepperEl.querySelector('.credit-minus').disabled = updated <= 0;
    } catch (error) {
        alert(error.message);
    } finally {
        stepperEl.querySelectorAll('button').forEach((b) => { b.disabled = false; });
        stepperEl.querySelector('.credit-minus').disabled = parseInt(stepperEl.querySelector('.credit-value').textContent, 10) <= 0;
    }
}

async function submitBulkCredits(event) {
    event.preventDefault();
    const status = el('bulkSaveStatus');
    const formData = new FormData(event.target);

    const payload = {};
    let hasValue = false;
    ['interview_credits', 'coach_credits'].forEach((key) => {
        const raw = formData.get(key);
        if (raw !== '' && raw !== null) {
            payload[key] = parseInt(raw, 10);
            hasValue = true;
        }
    });

    if (!hasValue) {
        status.textContent = 'Renseigne au moins un des deux champs.';
        return;
    }

    status.textContent = 'Application...';
    try {
        const response = await window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/school/credits/bulk`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Erreur');

        status.textContent = `Appliqué à ${data.nb_students} élève(s) ✅`;
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
        el('refreshBtn').textContent = '↻ Chargement...';
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
        el('schoolContent').innerHTML = `<div class="school-locked">⚠️ ${escHtml(error.message)}</div>`;
    } finally {
        el('refreshBtn').disabled = false;
        el('refreshBtn').textContent = '↻ Rafraîchir';
    }
}

function initSchoolPage() {
    el('refreshBtn').addEventListener('click', () => loadDashboard());
    el('bulkCreditForm').addEventListener('submit', submitBulkCredits);
    loadDashboard();
}

document.addEventListener('DOMContentLoaded', initSchoolPage);
