const API_BASE_URL = '/api';

const state = {
    interviewId: null,
    turnIndex: null,
    totalCompetencies: 0,
    answeredCount: 0,
    isRecording: false,
    mediaRecorder: null,
    audioChunks: [],
    currentAudio: null,
};

function el(id) {
    return document.getElementById(id);
}

function playQuestionAudio(base64) {
    if (state.currentAudio) {
        state.currentAudio.pause();
    }
    const audio = new Audio(`data:audio/mpeg;base64,${base64}`);
    state.currentAudio = audio;
    audio.play().catch(() => {
        // L'autoplay peut être bloqué par le navigateur : le bouton "réécouter" prend le relais.
    });
    return audio;
}

function addAssistantMessage(question, audioBase64) {
    const thread = el('interviewThread');
    const message = document.createElement('div');
    message.className = 'interview-message assistant';
    message.innerHTML = `
        <div class="interview-avatar">🐼</div>
        <div>
            <div class="interview-bubble">${escHtml(question)}</div>
            <button class="replay-btn" type="button">🔊 Réécouter</button>
        </div>
    `;
    message.querySelector('.replay-btn').addEventListener('click', () => playQuestionAudio(audioBase64));
    thread.appendChild(message);
    thread.scrollTop = thread.scrollHeight;
    if (audioBase64) playQuestionAudio(audioBase64);
}

function addUserMessage(transcript) {
    const thread = el('interviewThread');
    const message = document.createElement('div');
    message.className = 'interview-message user';
    message.innerHTML = `<div class="interview-bubble">${escHtml(transcript || '(réponse non transcrite)')}</div>`;
    thread.appendChild(message);
    thread.scrollTop = thread.scrollHeight;
}

function updateProgress(competency) {
    el('progressLabel').textContent = `Question ${state.answeredCount + 1}`;
    el('competencyLabel').textContent = competency || '';
    const pct = state.totalCompetencies
        ? Math.round((state.answeredCount / state.totalCompetencies) * 100)
        : 0;
    el('progressBarFill').style.width = `${pct}%`;
}

async function startInterview(event) {
    event.preventDefault();
    const jobDescription = el('jobDescriptionInput').value.trim();
    const errorBox = el('jobFormError');
    errorBox.textContent = '';

    if (!jobDescription) {
        errorBox.textContent = 'Colle une fiche de poste pour démarrer.';
        return;
    }

    const btn = el('startInterviewBtn');
    btn.disabled = true;
    btn.textContent = 'Préparation de l\'entretien...';

    try {
        const response = await window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/interview/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                job_description: jobDescription,
            }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Impossible de démarrer l\'entretien');

        state.interviewId = data.interview_id;
        state.turnIndex = data.turn_index;
        state.totalCompetencies = data.total_competencies;
        state.answeredCount = 0;

        el('jobForm').classList.add('hidden');
        el('interviewScreen').classList.remove('hidden');
        el('interviewThread').innerHTML = '';

        updateProgress(data.competency);
        addAssistantMessage(data.question, data.audio_base64);
    } catch (error) {
        errorBox.textContent = error.message;
    } finally {
        btn.disabled = false;
        btn.textContent = "🎙️ Démarrer l'entretien";
    }
}

async function startRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const recorder = new MediaRecorder(stream);
        state.mediaRecorder = recorder;
        state.audioChunks = [];

        recorder.ondataavailable = (e) => {
            if (e.data.size > 0) state.audioChunks.push(e.data);
        };
        recorder.onstop = () => {
            stream.getTracks().forEach((track) => track.stop());
            const blob = new Blob(state.audioChunks, { type: recorder.mimeType || 'audio/webm' });
            submitAnswer(blob);
        };

        recorder.start();
        state.isRecording = true;
        el('micBtn').classList.add('recording');
        el('micBtn').textContent = '⏹️';
        el('recorderHint').textContent = 'Enregistrement en cours... clique pour arrêter';
    } catch (error) {
        el('recorderHint').textContent = "Micro indisponible : autorise l'accès au microphone pour répondre.";
    }
}

function stopRecording() {
    if (state.mediaRecorder && state.isRecording) {
        state.mediaRecorder.stop();
        state.isRecording = false;
    }
}

async function submitAnswer(audioBlob) {
    const micBtn = el('micBtn');
    micBtn.classList.remove('recording');
    micBtn.disabled = true;
    micBtn.textContent = '⏳';
    el('recorderHint').textContent = 'Transcription de ta réponse...';

    try {
        const formData = new FormData();
        formData.append('interview_id', state.interviewId);
        formData.append('turn_index', state.turnIndex);
        formData.append('audio', audioBlob, 'answer.webm');

        const response = await window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/interview/respond`, {
            method: 'POST',
            body: formData,
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Erreur lors de la transcription');

        addUserMessage(data.transcript);
        state.answeredCount += 1;

        if (data.finished) {
            updateProgress('');
            el('progressLabel').textContent = 'Entretien terminé';
            el('progressBarFill').style.width = '100%';
            await finishInterview();
            return;
        }

        state.turnIndex = data.turn_index;
        updateProgress(data.next_competency);
        addAssistantMessage(data.question, data.audio_base64);

        micBtn.disabled = false;
        micBtn.textContent = '🎤';
        el('recorderHint').textContent = 'Clique pour répondre à l\'oral';
    } catch (error) {
        el('recorderHint').textContent = error.message;
        micBtn.disabled = false;
        micBtn.textContent = '🎤';
    }
}

async function finishInterview() {
    el('interviewScreen').classList.add('hidden');

    try {
        const response = await window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/interview/finish`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ interview_id: state.interviewId }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Impossible de générer l'évaluation");

        renderReport(data.evaluation);
        el('reportScreen').classList.remove('hidden');
    } catch (error) {
        el('jobFormError').textContent = error.message;
        el('jobForm').classList.remove('hidden');
    }
}

function renderReport(evaluation) {
    el('reportScoreGlobal').textContent = evaluation.score_global ?? '–';
    el('reportResume').textContent = evaluation.resume || '';
    el('reportConseil').textContent = evaluation.conseil_final || '';

    const pointsFortsList = el('reportPointsForts');
    pointsFortsList.innerHTML = (evaluation.points_forts || [])
        .map((p) => `<li>${escHtml(p)}</li>`).join('') || '<li>Aucun point noté.</li>';

    const ameliorationsList = el('reportAmeliorations');
    ameliorationsList.innerHTML = (evaluation.ameliorations || [])
        .map((a) => `<li>${escHtml(a)}</li>`).join('') || '<li>Aucun axe noté.</li>';

    const competenciesBox = el('reportCompetencies');
    competenciesBox.innerHTML = (evaluation.par_competence || []).map((c) => `
        <div class="competency-card">
            <div class="competency-card-header">
                <span class="competency-name">${escHtml(c.competence || '')}</span>
                <span class="competency-score">${c.score ?? '–'}/10</span>
            </div>
            <div class="competency-comment">${escHtml(c.commentaire || '')}</div>
        </div>
    `).join('');
}

async function checkReadiness() {
    const jobDescription = el('jobDescriptionInput').value.trim();
    const errorBox = el('jobFormError');
    const resultBox = el('readinessResult');
    errorBox.textContent = '';

    if (!jobDescription) {
        errorBox.textContent = 'Colle une fiche de poste pour estimer ta préparation.';
        return;
    }

    const me = await window.MocklyAuth.getCurrentUser();
    if (!me) {
        resultBox.classList.remove('hidden');
        resultBox.innerHTML = `Connecte-toi pour estimer ta préparation à partir de tes précédents entretiens. <a href="auth.html">Se connecter</a>`;
        return;
    }

    const btn = el('readinessCheckBtn');
    btn.disabled = true;
    btn.textContent = 'Analyse en cours...';

    try {
        const response = await window.MocklyAuth.fetchAuthed(`${API_BASE_URL}/profile/readiness-check`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_description: jobDescription }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Impossible d'estimer ta préparation");

        const pct = Math.round(data.readiness_score || 0);
        const coveragePct = Math.round((data.coverage || 0) * 100);
        resultBox.classList.remove('hidden');
        resultBox.innerHTML = `
            <div class="readiness-score-row">
                <span class="readiness-score-value">${pct}%</span>
                <span class="readiness-coverage">de préparation estimée pour « ${escHtml(data.job_title)} » — ${coveragePct}% des compétences déjà testées par tes précédents entretiens</span>
            </div>
            <div class="readiness-competencies">
                ${(data.competencies || []).map((c) => `<span class="readiness-chip">${escHtml(c.name)}</span>`).join('')}
            </div>
        `;
    } catch (error) {
        errorBox.textContent = error.message;
    } finally {
        btn.disabled = false;
        btn.textContent = '🔍 Estimer ma préparation';
    }
}

function resetToSetup() {
    state.interviewId = null;
    state.turnIndex = null;
    state.totalCompetencies = 0;
    state.answeredCount = 0;

    el('jobDescriptionInput').value = '';
    el('jobFormError').textContent = '';
    el('readinessResult').classList.add('hidden');
    el('reportScreen').classList.add('hidden');
    el('jobForm').classList.remove('hidden');
}

function escHtml(str) {
    if (!str) return '';
    return String(str).replace(/[&<>"']/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[m]));
}

function initInterviewPage() {
    el('jobForm').addEventListener('submit', startInterview);
    el('readinessCheckBtn').addEventListener('click', checkReadiness);
    el('micBtn').addEventListener('click', () => {
        if (state.isRecording) {
            stopRecording();
        } else {
            startRecording();
        }
    });
    el('restartInterviewBtn').addEventListener('click', resetToSetup);
}

document.addEventListener('DOMContentLoaded', initInterviewPage);
