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

function initAuthPage() {
    bindEvents();
    initChatScrollBehavior();
    restoreSession();
}

function bindEvents() {
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
            document.getElementById('authMessage').textContent = `Bienvenue ${currentUser.email}, connecte-toi pour accéder à ton workspace.`;
        } catch (error) {
            console.error(error);
        }
    }
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

        if (authMode === 'login') {
            // L'échange avec Mockly n'a lieu qu'une fois, à la création du compte.
            // Une connexion classique va donc directement au workspace.
            window.location.href = 'workspace.html';
            return;
        }

        document.getElementById('authPanel').classList.add('hidden');
        document.getElementById('onboardingPanel').classList.remove('hidden');
        onboardingStep = 0;
        onboardingAnswers = {};
        renderOnboardingStep();
    } catch (error) {
        messageBox.textContent = error.message;
    } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = authMode === 'signup' ? 'Créer mon compte' : 'Se connecter';
    }
}

function initChatScrollBehavior() {
    const thread = document.getElementById('chatThread');
    const button = document.getElementById('scrollToBottomBtn');

    if (!thread || !button) {
        return;
    }

    const isNearBottom = () => {
        const distanceToBottom = thread.scrollHeight - thread.clientHeight - thread.scrollTop;
        return distanceToBottom <= 180;
    };

    const updateScrollButton = () => {
        button.classList.toggle('hidden', isNearBottom());
    };

    const scrollToBottom = (smooth = false) => {
        thread.scrollTo({
            top: thread.scrollHeight,
            behavior: smooth ? 'smooth' : 'auto'
        });
        updateScrollButton();
    };

    button.addEventListener('click', () => scrollToBottom(true));
    thread.addEventListener('scroll', updateScrollButton, { passive: true });
    window.addEventListener('resize', () => {
        if (isNearBottom()) {
            scrollToBottom(false);
        }
        updateScrollButton();
    });

    requestAnimationFrame(() => scrollToBottom(false));
}

function scrollConversationToBottom(smooth = false) {
    const thread = document.getElementById('chatThread');
    const button = document.getElementById('scrollToBottomBtn');

    if (!thread || !button) {
        return;
    }

    const isNearBottom = thread.scrollHeight - thread.clientHeight - thread.scrollTop <= 180;
    if (!isNearBottom) {
        button.classList.remove('hidden');
        return;
    }

    thread.scrollTo({
        top: thread.scrollHeight,
        behavior: smooth ? 'smooth' : 'auto'
    });
    button.classList.add('hidden');
}

function renderOnboardingStep() {
    const step = onboardingQuestions[onboardingStep];
    const label = document.getElementById('onboardingLabel');
    const input = document.getElementById('onboardingInput');
    const status = document.getElementById('onboardingStatus');
    const thread = document.getElementById('chatThread');

    if (!step) return;

    label.textContent = step.question;
    input.value = onboardingAnswers[step.key] || '';
    input.placeholder = step.placeholder;
    input.focus();
    status.textContent = '';

    const bubble = document.createElement('div');
    bubble.className = 'message assistant typing';
    bubble.innerHTML = `
        <div class="avatar assistant-avatar">🐼</div>
        <div class="bubble assistant-bubble">
            <strong>Mockly</strong>
            <p>${step.question}</p>
        </div>
    `;
    thread.appendChild(bubble);
    scrollConversationToBottom(true);
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

    const thread = document.getElementById('chatThread');
    const userBubble = document.createElement('div');
    userBubble.className = 'message user';
    userBubble.innerHTML = `
        <div class="bubble user-bubble">
            <p>${value}</p>
        </div>
    `;
    thread.appendChild(userBubble);
    scrollConversationToBottom(true);

    onboardingStep += 1;

    if (onboardingStep >= onboardingQuestions.length) {
        setTimeout(() => submitOnboardingProfile(), 400);
        return;
    }

    setTimeout(() => renderOnboardingStep(), 300);
}

async function submitOnboardingProfile() {
    const btn = document.getElementById('onboardingNext');
    const status = document.getElementById('onboardingStatus');
    btn.disabled = true;
    btn.textContent = 'Enregistrement...';

    try {
        const response = await fetch(`${API_BASE_URL}/informations-pro`, {
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

        const thread = document.getElementById('chatThread');
        const successBubble = document.createElement('div');
        successBubble.className = 'message assistant';
        successBubble.innerHTML = `
            <div class="avatar assistant-avatar">🐼</div>
            <div class="bubble assistant-bubble">
                <strong>Mockly</strong>
                <p>Parfait, ton profil est prêt. Tu peux maintenant accéder au workspace.</p>
            </div>
        `;
        thread.appendChild(successBubble);
        scrollConversationToBottom(true);

        status.textContent = 'Profil enregistré. Tu peux maintenant accéder au workspace.';
        document.getElementById('goWorkspaceBtn').classList.remove('hidden');
        btn.classList.add('hidden');
    } catch (error) {
        status.textContent = error.message;
        btn.disabled = false;
        btn.textContent = 'Continuer';
    }
}

document.addEventListener('DOMContentLoaded', initAuthPage);
