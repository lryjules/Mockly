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
function fmtUsdSmall(x) {
    return x === null || x === undefined ? '—' : `$${Number(x).toFixed(4)}`;
}
function fmtUsdLarge(x) {
    return x === null || x === undefined ? '—' : `$${Number(x).toLocaleString('fr-FR', { maximumFractionDigits: 2 })}`;
}
function fmtMinutes(x) {
    return x === null || x === undefined ? '—' : `${Number(x).toFixed(1)} min`;
}
function fmtMs(x) {
    return x === null || x === undefined ? '—' : `${Math.round(x)} ms`;
}
function fmtDelta(x) {
    if (x === null || x === undefined) return '—';
    const rounded = Math.round(x * 10) / 10;
    return `${rounded >= 0 ? '+' : ''}${rounded}`;
}
function fmtScore(x) {
    return x === null || x === undefined ? '—' : `${Number(x).toFixed(1)}/100`;
}

function statusClassGoodHigh(x, warnBelow, badBelow) {
    if (x === null || x === undefined) return '';
    if (x < badBelow) return 'bad';
    if (x < warnBelow) return 'warn';
    return 'good';
}
function statusClassGoodLow(x, warnAbove, badAbove) {
    if (x === null || x === undefined) return '';
    if (x > badAbove) return 'bad';
    if (x > warnAbove) return 'warn';
    return 'good';
}

function tile(label, value, cls = 'accent', meta = '', opts = {}) {
    const clickableClass = opts.clickable ? ' clickable' : '';
    const idAttr = opts.id ? ` id="${opts.id}"` : '';
    return `
        <div class="kpi-tile${clickableClass}"${idAttr}>
            <div class="kpi-tile-label">${escHtml(label)}</div>
            <div class="kpi-tile-value ${cls}">${escHtml(value)}</div>
            ${meta ? `<div class="kpi-tile-meta">${escHtml(meta)}</div>` : ''}
        </div>
    `;
}

function renderProduct(p) {
    el('productSubtitle').textContent = `"Actif" = a créé une session CV ou un entretien dans les ${p.active_window_days} derniers jours.`;
    el('productGrid').innerHTML = [
        tile('Registered users', fmtNum(p.registered_users), 'accent', 'Voir le détail →', { id: 'registeredUsersTile', clickable: true }),
        tile('Active users', fmtNum(p.active_users)),
        tile('Interviews started', fmtNum(p.interviews_started)),
        tile('Interviews completed', fmtNum(p.interviews_completed)),
        tile('Completion rate', fmtPct(p.completion_rate), statusClassGoodHigh(p.completion_rate, 0.4, 0.2) || 'accent'),
        tile('Interviews / active student', fmtNum(p.interviews_per_active_student, 2)),
        tile('Repeat usage', fmtPct(p.repeat_usage_rate)),
        tile('Average score', p.average_score === null ? '—' : fmtScore(p.average_score)),
        tile('Score progression', fmtDelta(p.score_progression), p.score_progression > 0 ? 'good' : (p.score_progression < 0 ? 'bad' : 'accent')),
        tile('Average session duration', fmtMinutes(p.average_session_duration_minutes), 'accent', "Proxy : durée d'entretien (création → fin)"),
    ].join('');
}

function renderAi(ai) {
    el('aiGrid').innerHTML = [
        tile('Cost / interview', fmtUsdSmall(ai.cost_per_interview)),
        tile('Input tokens / interview', fmtNum(ai.input_tokens_per_interview, 0)),
        tile('Output tokens / interview', fmtNum(ai.output_tokens_per_interview, 0)),
        tile('Average latency', fmtMs(ai.average_latency_ms)),
        tile('Error rate', fmtPct(ai.error_rate), statusClassGoodLow(ai.error_rate, 0.05, 0.15) || 'good'),
        tile('Total AI calls logged', fmtNum(ai.total_calls)),
    ].join('');

    const container = el('modelDistribution');
    if (!ai.model_distribution || ai.model_distribution.length === 0) {
        container.innerHTML = '<div class="kpi-section-subtitle">Aucun appel IA journalisé pour l\'instant.</div>';
        return;
    }
    container.innerHTML = `<div class="kpi-tile-label" style="margin-bottom:0.5rem">Model distribution</div>` +
        ai.model_distribution.map((m) => `
            <div class="model-dist-row">
                <div class="model-dist-name">${escHtml(m.model)}</div>
                <div class="model-dist-track"><div class="model-dist-fill" style="width:${Math.round(m.share * 100)}%"></div></div>
                <div class="model-dist-count">${m.count} (${Math.round(m.share * 1000) / 10}%)</div>
            </div>
        `).join('');
}

function renderPilot(pilot) {
    el('pilotGrid').innerHTML = [
        tile('Student activation', fmtPct(pilot.student_activation_rate)),
        tile('Student completion', fmtPct(pilot.student_completion_rate)),
        tile('Repeat practice', fmtPct(pilot.repeat_practice_rate)),
        tile('Satisfaction', pilot.satisfaction === null ? '—' : fmtNum(pilot.satisfaction, 1)),
        tile('Career Center satisfaction', pilot.career_center_satisfaction === null ? '—' : fmtNum(pilot.career_center_satisfaction, 1)),
        tile('Cost / active student', fmtUsdSmall(pilot.cost_per_active_student)),
        tile('Cost / completed interview', fmtUsdSmall(pilot.cost_per_completed_interview)),
    ].join('');
}

const BUSINESS_FIELDS = [
    { key: 'schools_contacted', label: 'Schools contacted', step: '1' },
    { key: 'meetings', label: 'Meetings', step: '1' },
    { key: 'demos', label: 'Demos', step: '1' },
    { key: 'pilot_proposals', label: 'Pilot proposals', step: '1' },
    { key: 'pilots_signed', label: 'Pilots signed', step: '1' },
    { key: 'annual_contract_value', label: 'Annual contract value ($)', step: '0.01' },
    { key: 'customer_acquisition_cost', label: 'Customer acquisition cost ($)', step: '0.01' },
    { key: 'gross_margin_pct', label: 'Gross margin (%)', step: '0.1' },
    { key: 'satisfaction', label: 'Satisfaction (/10)', step: '0.1' },
    { key: 'career_center_satisfaction', label: 'Career Center satisfaction (/10)', step: '0.1' },
];

function renderBusinessForm(business) {
    const form = el('businessForm');
    form.innerHTML = BUSINESS_FIELDS.map((f) => `
        <label>
            ${escHtml(f.label)}
            <input type="number" step="${f.step}" name="${f.key}" value="${business[f.key] ?? ''}">
        </label>
    `).join('') + `
        <div class="business-form-actions">
            <button type="submit" class="primary-btn">Enregistrer</button>
            <span class="business-save-status" id="businessSaveStatus"></span>
            <span class="kpi-tile-meta">Pilot conversion rate : ${fmtPct(business.pilot_conversion_rate)}</span>
        </div>
    `;
}

async function saveBusinessMetrics(event) {
    event.preventDefault();
    const status = el('businessSaveStatus');
    const formData = new FormData(event.target);
    const metrics = {};
    BUSINESS_FIELDS.forEach((f) => {
        const raw = formData.get(f.key);
        metrics[f.key] = raw === '' ? null : raw;
    });

    status.textContent = 'Enregistrement...';
    try {
        const response = await window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/admin/business-metrics`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ metrics }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Erreur');

        status.innerHTML = `Enregistré ${mIcon('check-circle')}`;
        renderBusinessForm(data.business);
        el('businessForm').addEventListener('submit', saveBusinessMetrics);
        // Le reste du dashboard dépend aussi de business (ex: satisfaction, coûts) : on recharge tout.
        loadKpis({ silent: true });
    } catch (error) {
        status.textContent = error.message;
    }
}

async function loadKpis(opts = {}) {
    const me = await window.MocklyAuth.getCurrentUser();
    if (!me || !me.user.is_admin) {
        el('adminLocked').classList.remove('hidden');
        el('adminContent').classList.add('hidden');
        return;
    }

    el('adminLocked').classList.add('hidden');
    el('adminContent').classList.remove('hidden');

    if (!opts.silent) {
        el('refreshBtn').disabled = true;
        el('refreshBtn').innerHTML = `${mIcon('refresh-cw', 'icon-spin')} Chargement...`;
    }

    try {
        const response = await window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/admin/kpis`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Impossible de charger les indicateurs');

        renderProduct(data.product);
        renderAi(data.ai);
        renderPilot(data.pilot);
        renderBusinessForm(data.business);
        el('businessForm').addEventListener('submit', saveBusinessMetrics);
    } catch (error) {
        el('adminContent').innerHTML = `<div class="admin-locked">${mIcon('alert-triangle')} ${escHtml(error.message)}</div>`;
    } finally {
        el('refreshBtn').disabled = false;
        el('refreshBtn').innerHTML = `${mIcon('refresh-cw')} Rafraîchir`;
    }
}

function renderTokenBonusEditor(userId, bonus) {
    return `
        <div class="token-bonus-editor" data-user="${userId}">
            <input type="number" class="token-bonus-input" min="0" step="1000" value="${bonus}">
            <button type="button" class="token-bonus-save">${mIcon('check')}</button>
        </div>
    `;
}

function renderUsersTable(users) {
    el('usersTableBody').innerHTML = users.map((u) => {
        const nearLimit = u.tokens_used_today >= u.daily_token_limit;
        return `
        <tr>
            <td>${escHtml(u.email)}${u.is_admin ? '<span class="admin-badge">admin</span>' : ''}${u.is_school_admin ? '<span class="admin-badge">école</span>' : ''}</td>
            <td>${escHtml(u.school_name || '—')}</td>
            <td>${escHtml((u.created_at || '').slice(0, 10))}</td>
            <td>${u.nb_sessions}</td>
            <td>${u.nb_interviews}</td>
            <td class="${nearLimit ? 'token-usage-full' : ''}">${fmtNum(u.tokens_used_today)} / ${fmtNum(u.daily_token_limit)}</td>
            <td>${renderTokenBonusEditor(u.id, u.bonus_daily_token_limit)}</td>
        </tr>
    `;
    }).join('');

    el('usersTableBody').querySelectorAll('.token-bonus-editor').forEach((editor) => {
        const userId = editor.dataset.user;
        editor.querySelector('.token-bonus-save').addEventListener('click', () => saveTokenBonus(userId, editor));
    });
}

async function saveTokenBonus(userId, editorEl) {
    const input = editorEl.querySelector('.token-bonus-input');
    const value = Math.max(0, parseInt(input.value, 10) || 0);
    editorEl.querySelectorAll('button, input').forEach((el2) => { el2.disabled = true; });

    try {
        const response = await window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/admin/users/${userId}/token-bonus`, {
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

async function openUsersModal() {
    el('usersModalBackdrop').classList.remove('hidden');
    el('usersTableBody').innerHTML = '<tr><td colspan="7">Chargement...</td></tr>';

    try {
        const response = await window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/admin/users`);
        const users = await response.json();
        if (!response.ok) throw new Error(users.error || 'Erreur');
        renderUsersTable(users);
    } catch (error) {
        el('usersTableBody').innerHTML = `<tr><td colspan="7">${mIcon('alert-triangle')} ${escHtml(error.message)}</td></tr>`;
    }
}

function renderSchoolsTable(schools) {
    if (schools.length === 0) {
        el('schoolsTableBody').innerHTML = '<tr><td colspan="6">Aucune école créée pour l\'instant.</td></tr>';
        return;
    }
    el('schoolsTableBody').innerHTML = schools.map((s) => `
        <tr>
            <td>${escHtml(s.name)}</td>
            <td>${escHtml(s.admin_email || s.pending_admin_email || '—')}${!s.admin_email && s.pending_admin_email ? ' <span class="admin-badge">en attente</span>' : ''}</td>
            <td>${s.nb_students}</td>
            <td>${escHtml((s.created_at || '').slice(0, 10))}</td>
            <td>
                <div class="token-bonus-editor" data-school="${s.id}">
                    <input type="number" class="token-bonus-input" min="0" step="10000" value="${s.monthly_bonus_token_pool}">
                    <button type="button" class="token-bonus-save">${mIcon('check')}</button>
                </div>
                <div class="kpi-tile-meta">${fmtNum(s.monthly_bonus_tokens_used)} utilisés ce mois</div>
            </td>
            <td>
                <button type="button" class="payment-link-btn" data-school="${s.id}" data-school-name="${escHtml(s.name)}">Lien de paiement</button>
                <button type="button" class="school-delete-btn" data-school="${s.id}" ${s.nb_students > 0 ? 'disabled title="Retire d\'abord les élèves de cette école"' : ''}>Supprimer</button>
            </td>
        </tr>
    `).join('');

    el('schoolsTableBody').querySelectorAll('.payment-link-btn').forEach((btn) => {
        btn.addEventListener('click', () => openPaymentLinkModal(btn.dataset.school, btn.dataset.schoolName));
    });
    el('schoolsTableBody').querySelectorAll('.school-delete-btn').forEach((btn) => {
        btn.addEventListener('click', () => deleteSchool(btn.dataset.school));
    });
    el('schoolsTableBody').querySelectorAll('.token-bonus-editor').forEach((editor) => {
        const schoolId = editor.dataset.school;
        editor.querySelector('.token-bonus-save').addEventListener('click', () => saveSchoolTokenPool(schoolId, editor));
    });
}

async function saveSchoolTokenPool(schoolId, editorEl) {
    const input = editorEl.querySelector('.token-bonus-input');
    const value = Math.max(0, parseInt(input.value, 10) || 0);
    editorEl.querySelectorAll('button, input').forEach((el2) => { el2.disabled = true; });

    try {
        const response = await window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/admin/schools/${schoolId}/token-pool`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ monthly_bonus_token_pool: value }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Erreur');
        input.value = data.monthly_bonus_token_pool;
    } catch (error) {
        alert(error.message);
    } finally {
        editorEl.querySelectorAll('button, input').forEach((el2) => { el2.disabled = false; });
    }
}

async function loadSchools() {
    const me = await window.MocklyAuth.getCurrentUser();
    if (!me || !me.user.is_admin) return;
    try {
        const response = await window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/admin/schools`);
        const schools = await response.json();
        if (!response.ok) throw new Error(schools.error || 'Erreur');
        renderSchoolsTable(schools);
    } catch (error) {
        el('schoolsTableBody').innerHTML = `<tr><td colspan="5">${mIcon('alert-triangle')} ${escHtml(error.message)}</td></tr>`;
    }
}

async function createSchool(event) {
    event.preventDefault();
    const status = el('schoolCreateStatus');
    const formData = new FormData(event.target);

    status.textContent = 'Création...';
    try {
        const response = await window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/admin/schools`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: formData.get('name'),
                admin_email: formData.get('admin_email'),
            }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Erreur');

        status.innerHTML = data.admin_invite?.status === 'pending'
            ? `École créée ${mIcon('check-circle')} — ${escHtml(data.admin_invite.email)} recevra le rôle "profil école" dès sa première connexion.`
            : `École créée ${mIcon('check-circle')}`;
        event.target.reset();
        loadSchools();
    } catch (error) {
        status.textContent = error.message;
    }
}

async function deleteSchool(schoolId) {
    if (!confirm('Supprimer cette école ?')) return;
    try {
        const response = await window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/admin/schools/${schoolId}`, {
            method: 'DELETE',
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Erreur');
        loadSchools();
    } catch (error) {
        alert(error.message);
    }
}

function closeUsersModal() {
    el('usersModalBackdrop').classList.add('hidden');
}

let paymentLinkSchoolId = null;

async function openPaymentLinkModal(schoolId, schoolName) {
    paymentLinkSchoolId = schoolId;
    el('paymentLinkModalTitle').textContent = `Lien de paiement — ${schoolName}`;
    el('paymentLinkStatus').textContent = '';
    el('paymentLinkResult').classList.add('hidden');
    el('paymentLinkForm').reset();

    const select = el('paymentLinkPriceSelect');
    select.innerHTML = '<option>Chargement des plans...</option>';
    select.disabled = true;
    el('paymentLinkModalBackdrop').classList.remove('hidden');

    try {
        const response = await window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/admin/stripe/prices`);
        const prices = await response.json();
        if (!response.ok) throw new Error(prices.error || 'Erreur');
        if (prices.length === 0) {
            select.innerHTML = '<option value="">Aucun plan actif trouvé dans Stripe</option>';
            return;
        }
        select.innerHTML = prices.map((p) => {
            const amount = p.unit_amount !== null && p.unit_amount !== undefined ? (p.unit_amount / 100).toFixed(2) : '?';
            const label = `${p.product_name}${p.nickname ? ` (${p.nickname})` : ''} — ${amount} ${(p.currency || '').toUpperCase()}${p.interval ? `/${p.interval}` : ''}`;
            return `<option value="${escHtml(p.id)}">${escHtml(label)}</option>`;
        }).join('');
    } catch (error) {
        select.innerHTML = `<option value="">${escHtml(error.message)}</option>`;
    } finally {
        select.disabled = false;
    }
}

function closePaymentLinkModal() {
    el('paymentLinkModalBackdrop').classList.add('hidden');
    paymentLinkSchoolId = null;
}

async function submitPaymentLinkForm(event) {
    event.preventDefault();
    const status = el('paymentLinkStatus');
    const formData = new FormData(event.target);
    const priceId = formData.get('price_id');
    const quantity = formData.get('quantity');

    if (!priceId) {
        status.textContent = 'Sélectionne un plan.';
        return;
    }

    status.textContent = 'Génération...';
    el('paymentLinkResult').classList.add('hidden');
    try {
        const response = await window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/admin/schools/${paymentLinkSchoolId}/payment-link`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ price_id: priceId, quantity: parseInt(quantity, 10) }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Erreur');

        status.innerHTML = `Lien généré ${mIcon('check-circle')} — à envoyer manuellement à l'école.`;
        el('paymentLinkUrl').value = data.url;
        el('paymentLinkResult').classList.remove('hidden');
    } catch (error) {
        status.textContent = error.message;
    }
}

function copyPaymentLinkUrl() {
    const input = el('paymentLinkUrl');
    input.select();
    navigator.clipboard?.writeText(input.value);
}

function initAdminPage() {
    el('refreshBtn').addEventListener('click', () => loadKpis());
    el('closeUsersModal').addEventListener('click', closeUsersModal);
    el('usersModalBackdrop').addEventListener('click', (e) => {
        if (e.target === el('usersModalBackdrop')) closeUsersModal();
    });
    document.addEventListener('click', (e) => {
        if (e.target.closest('#registeredUsersTile')) openUsersModal();
    });
    el('schoolCreateForm').addEventListener('submit', createSchool);

    el('closePaymentLinkModal').addEventListener('click', closePaymentLinkModal);
    el('paymentLinkModalBackdrop').addEventListener('click', (e) => {
        if (e.target === el('paymentLinkModalBackdrop')) closePaymentLinkModal();
    });
    el('paymentLinkForm').addEventListener('submit', submitPaymentLinkForm);
    el('paymentLinkCopyBtn').addEventListener('click', copyPaymentLinkUrl);

    loadKpis();
    loadSchools();
}

document.addEventListener('DOMContentLoaded', initAdminPage);
