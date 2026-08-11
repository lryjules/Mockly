const API_BASE_URL = '/api';

const CATEGORY_LABELS = {
    technique: '💻 Technique',
    métier: '🧭 Métier',
    soft_skill: '🤝 Soft skills',
    autre: '✨ Autre',
};

const CATEGORY_ORDER = ['technique', 'métier', 'soft_skill', 'autre'];

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

    // Classement anonyme au sein de l'école, uniquement sur les hard skills
    // (technique/métier) et seulement si l'échantillon est assez grand côté
    // backend (profile_engine.MIN_STUDENTS_FOR_RANKING) — jamais de nom d'élève.
    const rankBadge = comp.school_rank
        ? `<span class="competency-rank-badge" title="Ton rang parmi les élèves de ton école évalués sur cette compétence">🏆 #${comp.school_rank}/${comp.school_rank_total} de l'école</span>`
        : '';

    return `
        <div class="competency-row ${confirmed ? '' : 'unconfirmed'}">
            <div class="competency-row-header">
                <span class="competency-name">${escHtml(comp.name)}</span>
                <span class="competency-score-label">${scoreLabel}</span>
            </div>
            <div class="competency-bar-track">
                <div class="competency-bar-fill" style="width:${barWidth}%"></div>
            </div>
            <div class="competency-meta">${meta}${rankBadge}</div>
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
    const me = await window.MocklyAuth.getCurrentUser();
    if (!me) {
        document.getElementById('profileLocked').classList.remove('hidden');
        return;
    }

    try {
        const response = await window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/profile/competencies`);
        const tree = await response.json();
        renderTree(tree);
    } catch (error) {
        document.getElementById('profileTree').innerHTML = `
            <div class="profile-empty">⚠️ Erreur de connexion. Vérifie que le serveur est lancé.</div>`;
    }
}

document.addEventListener('DOMContentLoaded', loadProfile);
