const API_BASE_URL = '/api';

const CATEGORY_LABELS = {
    technique: `${mIcon('monitor')} Technique`,
    métier: `${mIcon('compass')} Métier`,
    soft_skill: `${mIcon('handshake')} Soft skills`,
    autre: `${mIcon('sparkle')} Autre`,
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
        ? `<span class="competency-rank-badge" title="Ton rang parmi les élèves de ton école évalués sur cette compétence">${mIcon('award')} #${comp.school_rank}/${comp.school_rank_total} de l'école</span>`
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

function renderPrioritySkills(data) {
    const container = document.getElementById('prioritySkills');
    if (!data || !data.matched_occupation || !data.skills || data.skills.length === 0) {
        container.classList.add('hidden');
        container.innerHTML = '';
        return;
    }

    container.classList.remove('hidden');
    container.innerHTML = `
        <div class="priority-skills-title">${mIcon('target')} Compétences clés pour "${escHtml(data.matched_occupation)}"</div>
        <div class="priority-skills-subtitle">D'après les compétences essentielles de ce métier (référentiel ESCO), voici où concentrer tes efforts en priorité.</div>
        <div class="priority-skills-list">
            ${data.skills.map((skill) => `
                <div class="priority-skill-row">
                    <span class="priority-skill-icon">${mIcon('zap')}</span>
                    <div>
                        <div class="priority-skill-name">${escHtml(skill.name)}</div>
                        <div class="priority-skill-reason">${escHtml(skill.reason)}</div>
                    </div>
                </div>
            `).join('')}
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
        const [treeResponse, priorityResponse] = await Promise.all([
            window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/profile/competencies`),
            window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/profile/priority-skills`),
        ]);
        renderTree(await treeResponse.json());
        renderPrioritySkills(await priorityResponse.json());
    } catch (error) {
        document.getElementById('profileTree').innerHTML = `
            <div class="profile-empty">${mIcon('alert-triangle')} Erreur de connexion. Vérifie que le serveur est lancé.</div>`;
    }
}

document.addEventListener('DOMContentLoaded', loadProfile);
