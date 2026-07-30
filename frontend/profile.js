const API_BASE_URL = '/api';

const CATEGORY_LABELS = {
    technique: '💻 Technique',
    métier: '🧭 Métier',
    soft_skill: '🤝 Soft skills',
    autre: '✨ Autre',
};

const CATEGORY_ORDER = ['technique', 'métier', 'soft_skill', 'autre'];

function getCurrentUser() {
    const stored = localStorage.getItem('mocklyUser');
    if (!stored) return null;
    try {
        return JSON.parse(stored);
    } catch (error) {
        return null;
    }
}

function escHtml(str) {
    if (!str) return '';
    return String(str).replace(/[&<>"']/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[m]));
}

function renderCompetencyRow(comp) {
    const confirmed = comp.confirmed;
    const scoreLabel = confirmed ? `${Math.round(comp.current_score)}/100` : 'Non évalué';
    const barWidth = confirmed ? Math.max(4, Math.round(comp.current_score)) : 100;
    const meta = confirmed
        ? `${comp.evaluation_count} évaluation${comp.evaluation_count > 1 ? 's' : ''}`
        : 'Mentionnée sur ton CV, jamais testée à l\'oral';

    return `
        <div class="competency-row ${confirmed ? '' : 'unconfirmed'}">
            <div class="competency-row-header">
                <span class="competency-name">${escHtml(comp.name)}</span>
                <span class="competency-score-label">${scoreLabel}</span>
            </div>
            <div class="competency-bar-track">
                <div class="competency-bar-fill" style="width:${barWidth}%"></div>
            </div>
            <div class="competency-meta">${meta}</div>
        </div>
    `;
}

function renderTree(tree) {
    const container = document.getElementById('profileTree');
    const hasAny = CATEGORY_ORDER.some((cat) => (tree[cat] || []).length > 0);

    if (!hasAny) {
        document.getElementById('profileEmpty').classList.remove('hidden');
        container.innerHTML = '';
        return;
    }

    document.getElementById('profileEmpty').classList.add('hidden');
    container.innerHTML = CATEGORY_ORDER
        .filter((cat) => (tree[cat] || []).length > 0)
        .map((cat) => `
            <div class="profile-category">
                <div class="profile-category-title">${CATEGORY_LABELS[cat] || cat}</div>
                ${tree[cat].map(renderCompetencyRow).join('')}
            </div>
        `).join('');
}

async function loadProfile() {
    const user = getCurrentUser();
    if (!user) {
        document.getElementById('profileLocked').classList.remove('hidden');
        return;
    }

    try {
        const response = await fetch(`${API_BASE_URL}/profile/competencies/${encodeURIComponent(user.id)}`);
        const tree = await response.json();
        renderTree(tree);
    } catch (error) {
        document.getElementById('profileTree').innerHTML = `
            <div class="profile-empty">⚠️ Erreur de connexion. Vérifie que le serveur est lancé.</div>`;
    }
}

document.addEventListener('DOMContentLoaded', loadProfile);
