const API_BASE_URL = '/api';
let authMode = 'signup';
let onboardingStep = 0;
let onboardingAnswers = {};
let clerkMounted = false;

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

function escHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str).replace(/[&<>"']/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[m]));
}

async function initAuthPage() {
    bindEvents();
    initChatScrollBehavior();

    const Clerk = await window.MocklyAuth.clerkReady();
    if (!Clerk) {
        document.getElementById('authMessage')?.remove();
        const panel = document.getElementById('authPanel');
        panel.innerHTML = '<p class="auth-message">Authentification indisponible pour le moment. Réessaie plus tard.</p>';
        return;
    }

    if (Clerk.user) {
        // Ne PAS monter SignUp/SignIn ici : Clerk refuse de les afficher pour
        // un utilisateur déjà connecté (single-session) et se redirige alors
        // lui-même vers son "Home URL" (la racine) — c'était la cause exacte
        // du rebond vers la landing page. On gère nous-mêmes la suite.
        await routeSignedInUser();
        return;
    }

    mountClerkWidgets(Clerk);
}

function mountClerkWidgets(Clerk) {
    if (clerkMounted) return;
    clerkMounted = true;

    const redirectUrl = window.location.href.split('#')[0].split('?')[0];

    // On veut TOUJOURS revenir sur cette page après auth (jamais sur les
    // "default redirect URLs" du dashboard Clerk, qui pointent sur "/" par
    // défaut) pour laisser routeSignedInUser() gérer la suite (choix d'école,
    // onboarding, puis redirection finale). Le nom de cette option a changé
    // entre les versions de clerk-js (v4: afterSignUpUrl/afterSignInUrl,
    // v5: forceRedirectUrl) — on passe les deux jeux de props, celui que
    // cette instance ne reconnaît pas est simplement ignoré.
    const redirectProps = {
        forceRedirectUrl: redirectUrl,
        afterSignUpUrl: redirectUrl,
        afterSignInUrl: redirectUrl,
    };
    Clerk.mountSignUp(document.getElementById('clerkSignUp'), {
        ...redirectProps,
        signInUrl: redirectUrl,
    });
    Clerk.mountSignIn(document.getElementById('clerkSignIn'), {
        ...redirectProps,
        signUpUrl: redirectUrl,
    });
}

function bindEvents() {
    document.getElementById('showSignupTab').addEventListener('click', () => switchAuthMode('signup'));
    document.getElementById('showLoginTab').addEventListener('click', () => switchAuthMode('login'));
    document.getElementById('schoolForm').addEventListener('submit', handleSchoolSubmit);
    document.getElementById('onboardingNext').addEventListener('click', handleOnboardingNext);
    document.getElementById('goWorkspaceBtn').addEventListener('click', () => {
        window.location.href = 'workspace.html';
    });
}

function switchAuthMode(mode) {
    authMode = mode;
    document.getElementById('showSignupTab').classList.toggle('active', mode === 'signup');
    document.getElementById('showLoginTab').classList.toggle('active', mode === 'login');
    document.getElementById('clerkSignUpWrap').classList.toggle('hidden', mode !== 'signup');
    document.getElementById('clerkSignInWrap').classList.toggle('hidden', mode !== 'login');
}

async function routeSignedInUser() {
    const me = await window.MocklyAuth.getCurrentUser({ force: true });
    if (!me || !me.user) return;

    if (me.user.is_school_admin) {
        window.location.href = '/school';
        return;
    }

    if (!me.user.school_id) {
        // Compte fraîchement créé (ou jamais complété) : Clerk ne connaît pas
        // notre notion d'école, il faut la demander avant d'aller plus loin.
        document.getElementById('authPanel').classList.add('hidden');
        document.getElementById('schoolPanel').classList.remove('hidden');
        loadSchoolsIntoSelect();
        return;
    }

    window.location.href = 'workspace.html';
}

async function loadSchoolsIntoSelect() {
    const select = document.getElementById('onboardingSchool');
    try {
        const response = await fetch(`${API_BASE_URL}/schools`);
        const schools = await response.json();
        if (!response.ok) throw new Error(schools.error || 'Erreur');

        if (schools.length === 0) {
            select.innerHTML = '<option value="">Aucune école disponible pour l’instant</option>';
            return;
        }
        select.innerHTML = '<option value="">Sélectionne ton école</option>' +
            schools.map((s) => `<option value="${escHtml(s.id)}">${escHtml(s.name)}</option>`).join('');
    } catch (error) {
        select.innerHTML = '<option value="">Impossible de charger les écoles</option>';
    }
}

async function handleSchoolSubmit(event) {
    event.preventDefault();
    const schoolId = document.getElementById('onboardingSchool').value;
    const message = document.getElementById('schoolMessage');
    const btn = document.getElementById('schoolSubmitBtn');

    if (!schoolId) {
        message.textContent = 'Sélectionne ton école.';
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Enregistrement...';
    try {
        const response = await window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/me/school`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ school_id: schoolId })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Erreur');

        window.MocklyAuth.invalidateUserCache();
        document.getElementById('schoolPanel').classList.add('hidden');
        document.getElementById('onboardingPanel').classList.remove('hidden');
        onboardingStep = 0;
        onboardingAnswers = {};
        renderOnboardingStep();
    } catch (error) {
        message.textContent = error.message;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Continuer';
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
            <p>${escHtml(step.question)}</p>
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
            <p>${escHtml(value)}</p>
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
        const response = await window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/informations-pro`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
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
