const API_BASE_URL = '/api';

async function loadProfile() {
    const status = document.getElementById('configStatus');
    try {
        const response = await window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/informations-pro`);
        if (response.status === 404) return; // Pas encore d'informations enregistrées
        if (!response.ok) throw new Error('Impossible de charger tes informations');

        const data = await response.json();
        const profile = data.profile || {};
        document.getElementById('studyLevelInput').value = profile.study_level || '';
        document.getElementById('targetDomainInput').value = profile.target_domain || '';
        document.getElementById('currentGoalInput').value = profile.current_goal || '';
    } catch (error) {
        status.textContent = error.message;
    }
}

async function handleSave(event) {
    event.preventDefault();

    const btn = document.getElementById('configSaveBtn');
    const status = document.getElementById('configStatus');
    btn.disabled = true;
    btn.textContent = 'Enregistrement...';

    try {
        const response = await window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/informations-pro`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                studyLevel: document.getElementById('studyLevelInput').value.trim(),
                targetDomain: document.getElementById('targetDomainInput').value.trim(),
                currentGoal: document.getElementById('currentGoalInput').value.trim()
            })
        });

        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Impossible d’enregistrer tes informations');

        status.textContent = 'Informations enregistrées.';
    } catch (error) {
        status.textContent = error.message;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Enregistrer';
    }
}

async function initConfigurationPage() {
    const me = await window.MocklyAuth.getCurrentUser();
    const locked = document.getElementById('configLocked');
    const form = document.getElementById('configForm');

    if (!me) {
        locked.classList.remove('hidden');
        form.classList.add('hidden');
        return;
    }

    locked.classList.add('hidden');
    form.classList.remove('hidden');
    form.addEventListener('submit', handleSave);
    loadProfile();
}

document.addEventListener('DOMContentLoaded', initConfigurationPage);
