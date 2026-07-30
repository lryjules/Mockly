const API_BASE_URL = '/api';

function getCurrentUser() {
    const stored = localStorage.getItem('mocklyUser');
    if (!stored) return null;
    try {
        return JSON.parse(stored);
    } catch (error) {
        return null;
    }
}

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

function tile(label, value, cls = 'accent', meta = '') {
    return `
        <div class="kpi-tile">
            <div class="kpi-tile-label">${escHtml(label)}</div>
            <div class="kpi-tile-value ${cls}">${escHtml(value)}</div>
            ${meta ? `<div class="kpi-tile-meta">${escHtml(meta)}</div>` : ''}
        </div>
    `;
}

function renderProduct(p) {
    el('productSubtitle').textContent = `"Actif" = a créé une session CV ou un entretien dans les ${p.active_window_days} derniers jours.`;
    el('productGrid').innerHTML = [
        tile('Registered users', fmtNum(p.registered_users)),
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
    const user = getCurrentUser();
    const status = el('businessSaveStatus');
    const formData = new FormData(event.target);
    const metrics = {};
    BUSINESS_FIELDS.forEach((f) => {
        const raw = formData.get(f.key);
        metrics[f.key] = raw === '' ? null : raw;
    });

    status.textContent = 'Enregistrement...';
    try {
        const response = await fetch(`${API_BASE_URL}/admin/business-metrics`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: user.id, metrics }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Erreur');

        status.textContent = 'Enregistré ✅';
        renderBusinessForm(data.business);
        el('businessForm').addEventListener('submit', saveBusinessMetrics);
        // Le reste du dashboard dépend aussi de business (ex: satisfaction, coûts) : on recharge tout.
        loadKpis({ silent: true });
    } catch (error) {
        status.textContent = error.message;
    }
}

async function loadKpis(opts = {}) {
    const user = getCurrentUser();
    if (!user || !user.is_admin) {
        el('adminLocked').classList.remove('hidden');
        el('adminContent').classList.add('hidden');
        return;
    }

    el('adminLocked').classList.add('hidden');
    el('adminContent').classList.remove('hidden');

    if (!opts.silent) {
        el('refreshBtn').disabled = true;
        el('refreshBtn').textContent = '↻ Chargement...';
    }

    try {
        const response = await fetch(`${API_BASE_URL}/admin/kpis?user_id=${encodeURIComponent(user.id)}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Impossible de charger les indicateurs');

        renderProduct(data.product);
        renderAi(data.ai);
        renderPilot(data.pilot);
        renderBusinessForm(data.business);
        el('businessForm').addEventListener('submit', saveBusinessMetrics);
    } catch (error) {
        el('adminContent').innerHTML = `<div class="admin-locked">⚠️ ${escHtml(error.message)}</div>`;
    } finally {
        el('refreshBtn').disabled = false;
        el('refreshBtn').textContent = '↻ Rafraîchir';
    }
}

function initAdminPage() {
    el('refreshBtn').addEventListener('click', () => loadKpis());
    loadKpis();
}

document.addEventListener('DOMContentLoaded', initAdminPage);
