const API_BASE_URL = 'http://localhost:5001/api';

let authMode = 'signup';
let onboardingStep = 0;
let onboardingAnswers = {};
let currentUser = null;

const onboardingQuestions = [
    {
        key: 'studyLevel',
        question: 'Quel est ton niveau d’étude ?',
        placeholder: 'Ex: Licence, Master, BTS, etc.'
    },
    {
        key: 'targetDomain',
        question: 'Dans quel domaine souhaites-tu travailler ?',
        placeholder: 'Ex: Data, Tech, Marketing, RH...'
    },
    {
        key: 'currentGoal',
        question: 'Que recherches-tu aujourd’hui ?',
        placeholder: 'Ex: un stage, un premier emploi, une évolution...'
    }
];

function initLandingPage() {
    bindEvents();
    restoreSession();
}

function bindEvents() {
    document.querySelectorAll('[data-open-auth]').forEach((btn) => {
        btn.addEventListener('click', (event) => {
            event.preventDefault();
            openAuthModal();
        });
    });

    document.getElementById('closeAuthModal').addEventListener('click', closeAuthModal);
    document.querySelector('.modal-backdrop').addEventListener('click', closeAuthModal);

    document.getElementById('showSignupTab').addEventListener('click', () => switchAuthMode('signup'));
    document.getElementById('showLoginTab').addEventListener('click', () => switchAuthMode('login'));

    document.getElementById('authForm').addEventListener('submit', handleAuthSubmit);
    document.getElementById('onboardingNext').addEventListener('click', handleOnboardingNext);
    document.getElementById('goWorkspaceBtn').addEventListener('click', () => {
        window.location.href = 'workspace.html';
    });
}

function restoreSession() {
    const storedUser = localStorage.getItem('mocklyUser');
    if (storedUser) {
        try {
            currentUser = JSON.parse(storedUser);
            document.getElementById('authMessage').textContent = `Bonjour ${currentUser.email}. Tu peux reprendre l’onboarding.`;
        } catch (error) {
            console.error(error);
        }
    }
}

function openAuthModal() {
    document.getElementById('authModal').classList.remove('hidden');
    document.body.classList.add('modal-open');
}

function closeAuthModal() {
    document.getElementById('authModal').classList.add('hidden');
    document.body.classList.remove('modal-open');
}

function switchAuthMode(mode) {
    authMode = mode;
    const signupTab = document.getElementById('showSignupTab');
    const loginTab = document.getElementById('showLoginTab');
    const confirmGroup = document.getElementById('confirmPasswordGroup');
    const submitBtn = document.getElementById('authSubmitBtn');

    signupTab.classList.toggle('active', mode === 'signup');
    loginTab.classList.toggle('active', mode === 'login');
    confirmGroup.classList.toggle('hidden', mode === 'login');
    submitBtn.textContent = mode === 'signup' ? 'Créer mon compte' : 'Se connecter';
    document.getElementById('authMessage').textContent = '';
}

async function handleAuthSubmit(event) {
    event.preventDefault();

    const email = document.getElementById('authEmail').value.trim();
    const password = document.getElementById('authPassword').value;
    const confirmPassword = document.getElementById('authConfirmPassword').value;
    const messageBox = document.getElementById('authMessage');

    if (!email || !password) {
        messageBox.textContent = 'Remplis l’adresse email et le mot de passe.';
        return;
    }

    if (authMode === 'signup' && password !== confirmPassword) {
        messageBox.textContent = 'La confirmation du mot de passe ne correspond pas.';
        return;
    }

    const submitBtn = document.getElementById('authSubmitBtn');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Chargement...';

    try {
        const endpoint = authMode === 'signup' ? '/signup' : '/login';
        const response = await fetch(`${API_BASE_URL}${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                email,
                password,
                confirmPassword: authMode === 'signup' ? confirmPassword : password
            })
        });

        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Erreur d’authentification');
        }

        currentUser = data.user;
        localStorage.setItem('mocklyUser', JSON.stringify(currentUser));

        document.getElementById('authPanel').classList.add('hidden');
        document.getElementById('onboardingPanel').classList.remove('hidden');
        onboardingStep = 0;
        onboardingAnswers = {};
        renderOnboardingStep();
        messageBox.textContent = '';
    } catch (error) {
        messageBox.textContent = error.message;
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = authMode === 'signup' ? 'Créer mon compte' : 'Se connecter';
    }
}

function renderOnboardingStep() {
    const step = onboardingQuestions[onboardingStep];
    const label = document.getElementById('onboardingLabel');
    const input = document.getElementById('onboardingInput');
    const message = document.getElementById('onboardingMessage');
    const status = document.getElementById('onboardingStatus');

    if (!step) {
        return;
    }

    label.textContent = step.question;
    input.value = onboardingAnswers[step.key] || '';
    input.placeholder = step.placeholder;
    input.focus();
    message.textContent = 'Mockly le panda te guide pour définir ton profil.';
    status.textContent = '';
}

function handleOnboardingNext() {
    const step = onboardingQuestions[onboardingStep];
    if (!step) return;

    const input = document.getElementById('onboardingInput');
    const value = input.value.trim();
    if (!value) {
        document.getElementById('onboardingStatus').textContent = 'Réponds à la question pour continuer.';
        return;
    }

    onboardingAnswers[step.key] = value;
    onboardingStep += 1;

    if (onboardingStep >= onboardingQuestions.length) {
        submitOnboardingProfile();
        return;
    }

    renderOnboardingStep();
}

async function submitOnboardingProfile() {
    const btn = document.getElementById('onboardingNext');
    const status = document.getElementById('onboardingStatus');
    btn.disabled = true;
    btn.textContent = 'Enregistrement...';

    try {
        const response = await fetch(`${API_BASE_URL}/onboarding-profile`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: currentUser?.id,
                studyLevel: onboardingAnswers.studyLevel,
                targetDomain: onboardingAnswers.targetDomain,
                currentGoal: onboardingAnswers.currentGoal
            })
        });

        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Impossible d’enregistrer le profil');

        status.textContent = 'Profil enregistré. Tu peux maintenant accéder au workspace.';
        btn.textContent = 'Accéder au workspace';
        btn.disabled = false;
        btn.onclick = () => {
            window.location.href = 'workspace.html';
        };
    } catch (error) {
        status.textContent = error.message;
        btn.disabled = false;
        btn.textContent = 'Continuer';
    }
}

document.addEventListener('DOMContentLoaded', initLandingPage);
