// API Configuration
const API_BASE_URL = 'http://mockly-avje.onrender.com//api';

function getCurrentUser() {
    const stored = localStorage.getItem('mocklyUser');
    if (!stored) return null;
    try {
        return JSON.parse(stored);
    } catch (error) {
        return null;
    }
}

// State management
let appState = {
    sessionId: null,
    cvData: null,
    analysisData: null,
    nodes: [],
    connections: [],
    canvasOffset: { x: 0, y: 0 },
    canvasScale: 1,
    isDragging: false,
    dragStart: { x: 0, y: 0 },
    activeNode: null
};

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    initializeCanvas();
});

function setupEventListeners() {
    // Upload
    const uploadZone = document.getElementById('uploadZone');
    const cvFile = document.getElementById('cvFile');

    uploadZone.addEventListener('click', () => cvFile.click());
    cvFile.addEventListener('change', handleFileUpload);

    uploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadZone.style.borderColor = 'var(--vscode-blue)';
    });

    uploadZone.addEventListener('dragleave', () => {
        uploadZone.style.borderColor = 'var(--vscode-border)';
    });

    uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadZone.style.borderColor = 'var(--vscode-border)';
        if (e.dataTransfer.files.length) {
            cvFile.files = e.dataTransfer.files;
            handleFileUpload({ target: cvFile });
        }
    });

    // Generate button
    document.getElementById('generateBtn').addEventListener('click', generateMindMap);

    // Canvas controls
    document.getElementById('zoomInBtn').addEventListener('click', () => zoomIn());
    document.getElementById('zoomOutBtn').addEventListener('click', () => zoomOut());
    document.getElementById('resetViewBtn').addEventListener('click', resetView);
    document.getElementById('fitViewBtn').addEventListener('click', fitView);
    document.getElementById('openChatBtn').addEventListener('click', () => {
        openChat({});
    });

    // Chat
    document.getElementById('chatClose').addEventListener('click', () => {
        document.getElementById('chatPanel').classList.remove('open');
    });

    document.getElementById('chatSend').addEventListener('click', sendChatMessage);
    document.getElementById('chatInput').addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendChatMessage();
        }
    });
}

function initializeCanvas() {
    const canvas = document.getElementById('canvas');
    const canvasContainer = document.querySelector('.canvas-container');
    let isDragging = false;
    let startX, startY;

    // Pan à la souris ou au doigt (sur le canvas ou le container)
    canvasContainer.addEventListener('pointerdown', (e) => {
        // Ne pas pan si on clique sur un nœud
        if (e.target.closest('.node')) return;

        isDragging = true;
        startX = e.clientX - appState.canvasOffset.x;
        startY = e.clientY - appState.canvasOffset.y;
        canvasContainer.style.cursor = 'grabbing';
    });

    document.addEventListener('pointermove', (e) => {
        if (isDragging) {
            appState.canvasOffset.x = e.clientX - startX;
            appState.canvasOffset.y = e.clientY - startY;
            updateCanvasTransform();
        }
    });

    document.addEventListener('pointerup', () => {
        if (isDragging) {
            isDragging = false;
            canvasContainer.style.cursor = 'grab';
        }
    });

    // Zoom avec la molette (sensibilité très réduite)
    canvasContainer.addEventListener('wheel', (e) => {
        e.preventDefault();

        // Sensibilité très réduite : 0.02 pour un contrôle précis
        const delta = e.deltaY > 0 ? -0.02 : 0.02;
        const newScale = Math.max(0.3, Math.min(3, appState.canvasScale + delta));

        // Zoom centré sur la souris
        const rect = canvasContainer.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;

        const scaleChange = newScale / appState.canvasScale;

        appState.canvasOffset.x = mouseX - (mouseX - appState.canvasOffset.x) * scaleChange;
        appState.canvasOffset.y = mouseY - (mouseY - appState.canvasOffset.y) * scaleChange;
        appState.canvasScale = newScale;

        updateCanvasTransform();
        updateZoomIndicator();
    }, { passive: false });

    // Curseur par défaut
    canvasContainer.style.cursor = 'grab';
}

function updateZoomIndicator() {
    const zoomPercent = Math.round(appState.canvasScale * 100);
    const indicator = document.querySelector('.zoom-indicator');
    if (indicator) {
        indicator.textContent = `${zoomPercent}%`;
    }
}


async function handleFileUpload(e) {
    const file = e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);
    const currentUser = getCurrentUser();
    if (currentUser) {
        formData.append('user_id', currentUser.id);
    }

    const uploadZone = document.getElementById('uploadZone');
    uploadZone.innerHTML = '<div class="loading"><div class="spinner"></div><span>Analyse en cours...</span></div>';

    try {
        const response = await fetch(`${API_BASE_URL}/upload-cv`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Erreur lors de l\'upload');
        }

        const data = await response.json();
        appState.sessionId = data.session_id;
        appState.cvData = data.cv_data;
        appState.analysisData = data.analysis;

        // Show CV info
        document.getElementById('cvInfo').innerHTML = `
            <div><strong>Nom:</strong> ${data.cv_data.nom || 'Non trouvé'}</div>
            <div><strong>Email:</strong> ${data.cv_data.email || 'Non trouvé'}</div>
            <div><strong>Compétences:</strong> ${data.cv_data.competences?.slice(0, 3).join(', ') || 'Aucune'}</div>
        `;
        document.getElementById('infoSection').classList.remove('hidden');
        document.getElementById('contextSection').classList.remove('hidden');

        // Reset upload zone
        uploadZone.innerHTML = `
            <div class="upload-icon">✅</div>
            <div class="upload-text">CV analysé avec succès</div>
            <div class="upload-hint">Cliquez pour changer</div>
        `;

        // Create root node
        createRootNode();

        // Créer les nuages d'analyse autour du CV
        createInitialClouds();

    } catch (error) {
        uploadZone.innerHTML = `
            <div class="upload-icon">❌</div>
            <div class="upload-text">Erreur: ${error.message}</div>
            <div class="upload-hint">Cliquez pour réessayer</div>
        `;
    }
}

function createRootNode() {
    const canvas = document.getElementById('canvas');
    const canvasRect = canvas.getBoundingClientRect();

    const rootNode = {
        id: 'root',
        type: 'cv',
        title: 'CV - ' + (appState.cvData.nom || 'Votre CV'),
        content: `${appState.cvData.competences?.length || 0} compétences identifiées`,
        x: canvasRect.width / 2 - 100,
        y: 100,
        children: []
    };

    appState.nodes.push(rootNode);
    renderNode(rootNode);
}

function createInitialClouds() {
    const rootNode = appState.nodes.find(n => n.id === 'root');
    if (!rootNode) return;

    // Conseils CV - Position en haut à gauche
    const conseilsNode = {
        id: 'conseils',
        type: 'conseil',
        title: '💡 Conseils CV',
        content: 'Conseils personnalisés basés sur votre profil',
        tags: appState.analysisData.conseils_cv.slice(0, 3),
        x: rootNode.x - 300,
        y: rootNode.y - 100,
        parent: 'root',
        expandable: true,
        fullContent: appState.analysisData.conseils_cv
    };

    // Questions - Position en haut à droite
    const questionsNode = {
        id: 'questions',
        type: 'question',
        title: '❓ Questions de préparation',
        content: 'Questions clés pour votre entretien',
        tags: appState.analysisData.questions_preparation.slice(0, 3),
        x: rootNode.x + 300,
        y: rootNode.y - 100,
        parent: 'root',
        expandable: true,
        fullContent: appState.analysisData.questions_preparation
    };

    // Secteurs - Position en bas à gauche
    const secteursNode = {
        id: 'secteurs',
        type: 'secteur',
        title: '🎯 Secteurs pertinents',
        content: 'Secteurs adaptés à votre profil',
        tags: appState.analysisData.sujets_entretien.secteurs.slice(0, 3),
        x: rootNode.x - 300,
        y: rootNode.y + 250,
        parent: 'root',
        expandable: true,
        fullContent: appState.analysisData.sujets_entretien.secteurs
    };

    // Compétences clés - Position en bas à droite
    const competencesNode = {
        id: 'competences',
        type: 'secteur',
        title: '⭐ Compétences clés',
        content: 'Compétences à valoriser',
        tags: appState.analysisData.sujets_entretien.competences_clés.slice(0, 3),
        x: rootNode.x + 300,
        y: rootNode.y + 250,
        parent: 'root',
        expandable: true,
        fullContent: appState.analysisData.sujets_entretien.competences_clés
    };

    const newNodes = [conseilsNode, questionsNode, secteursNode, competencesNode];

    newNodes.forEach(node => {
        appState.nodes.push(node);
        renderNode(node);
        appState.connections.push({ from: 'root', to: node.id });
    });

    drawConnections();
}


async function generateMindMap() {
    const sector = document.getElementById('sectorInput').value;
    const company = document.getElementById('companyInput').value;
    const role = document.getElementById('roleInput').value;

    if (!sector) {
        alert('Veuillez entrer un secteur');
        return;
    }

    const btn = document.getElementById('generateBtn');
    btn.disabled = true;
    btn.innerHTML = '<div class="loading"><div class="spinner"></div><span>Génération...</span></div>';

    try {
        // Generate interview topics
        const response = await fetch(`${API_BASE_URL}/generate-interview-topics`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: appState.sessionId,
                sector,
                company: company || null,
                role: role || null
            })
        });

        if (!response.ok) throw new Error('Erreur lors de la génération');

        const topics = await response.json();

        // Create child nodes
        createChildNodes(topics, sector, company, role);

        btn.innerHTML = 'Carte générée ✅';

    } catch (error) {
        alert('Erreur: ' + error.message);
        btn.disabled = false;
        btn.innerHTML = 'Générer la carte mentale';
    }
}

function createChildNodes(topics, sector, company, role) {
    const rootNode = appState.nodes.find(n => n.id === 'root');
    if (!rootNode) return;

    const canvas = document.getElementById('canvas');
    const canvasRect = canvas.getBoundingClientRect();

    // Conseils CV (en haut à gauche)
    const conseilsNode = {
        id: 'conseils',
        type: 'conseil',
        title: '💡 Conseils CV',
        content: appState.analysisData.conseils_cv.join(' • '),
        tags: appState.analysisData.conseils_cv.slice(0, 5),
        x: rootNode.x - 300,
        y: rootNode.y - 150,
        parent: 'root'
    };

    // Secteurs pertinents (en bas à gauche)
    const secteursNode = {
        id: 'secteurs',
        type: 'secteur',
        title: '🎯 Secteurs Pertinents',
        content: appState.analysisData.sujets_entretien.secteurs.join(' • '),
        tags: appState.analysisData.sujets_entretien.secteurs,
        x: rootNode.x - 300,
        y: rootNode.y + 150,
        parent: 'root'
    };

    // Combiner toutes les questions d'entretien en un seul nuage (à droite)
    const allQuestions = [
        ...(topics.topics.questions_culture_entreprise || []),
        ...(topics.topics.questions_job_specifiques || []),
        ...(topics.topics.brain_teasers || [])
    ];

    const questionsNode = {
        id: 'questions-entretien',
        type: 'question',
        title: `🎯 Questions d'Entretien - ${company || sector}`,
        content: `Culture Entreprise • Missions du Poste • Brain Teasers`,
        tags: allQuestions.slice(0, 9),
        x: rootNode.x + 350,
        y: rootNode.y,
        parent: 'root'
    };

    const newNodes = [conseilsNode, secteursNode, questionsNode];

    newNodes.forEach(node => {
        appState.nodes.push(node);
        renderNode(node);
        appState.connections.push({ from: 'root', to: node.id });
    });

    drawConnections();
}

function renderNode(node) {
    const canvas = document.getElementById('canvas');

    const nodeEl = document.createElement('div');
    nodeEl.className = `node ${node.type === 'cv' ? 'root' : ''}`;
    nodeEl.id = `node-${node.id}`;
    nodeEl.style.left = node.x + 'px';
    nodeEl.style.top = node.y + 'px';

    nodeEl.innerHTML = `
        <div class="node-header">
            <div class="node-icon ${node.type}">${getNodeIcon(node.type)}</div>
            <div class="node-title">${node.title}</div>
            ${node.type !== 'cv' ? '<button class="node-delete" title="Supprimer">×</button>' : ''}
        </div>
        <div class="node-content">${node.content}</div>
        ${node.tags ? `
            <div class="node-tags">
                ${node.tags.map(tag => `<div class="node-tag">${tag}</div>`).join('')}
            </div>
        ` : ''}
        ${node.interactive ? '<div class="node-expand">Ouvrir le chat →</div>' : ''}
        ${node.expandable ? '<div class="node-expand">Voir tout →</div>' : ''}
    `;

    if (node.interactive) {
        nodeEl.addEventListener('click', () => openChat(node));
    }

    // NOUVEAU: Drag & Drop sur chaque nœud
    makeNodeDraggable(nodeEl, node);

    canvas.appendChild(nodeEl);

    // Bouton de suppression
    if (node.type !== 'cv') {
        const deleteBtn = nodeEl.querySelector('.node-delete');
        if (deleteBtn) {
            deleteBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                deleteNode(node.id);
            });
        }
    }

    // NOUVEAU: Event listeners sur les tags de questions
    if (node.tags && (node.type === 'question' || node.type === 'conseil')) {
        const tagElements = nodeEl.querySelectorAll('.node-tag');
        tagElements.forEach((tagEl, index) => {
            tagEl.addEventListener('click', (e) => {
                e.stopPropagation();
                const questionText = node.tags[index];
                createResponseNode(questionText, node);
            });
        });
    }
}


function makeNodeDraggable(nodeEl, node) {
    let isDragging = false;
    let startX, startY;
    let initialX, initialY;

    nodeEl.addEventListener('pointerdown', (e) => {
        // Ne pas drag si on clique sur un bouton ou tag
        if (e.target.classList.contains('node-expand') ||
            e.target.classList.contains('node-tag') ||
            e.target.classList.contains('node-delete')) {
            return;
        }

        isDragging = true;
        startX = e.clientX;
        startY = e.clientY;
        initialX = node.x;
        initialY = node.y;

        nodeEl.style.cursor = 'grabbing';
        nodeEl.style.zIndex = '1000';

        e.stopPropagation(); // Empêcher le drag du canvas
    });

    document.addEventListener('pointermove', (e) => {
        if (!isDragging) return;

        const dx = e.clientX - startX;
        const dy = e.clientY - startY;

        node.x = initialX + dx;
        node.y = initialY + dy;

        nodeEl.style.left = node.x + 'px';
        nodeEl.style.top = node.y + 'px';

        // Redessiner les connexions en temps réel
        drawConnections();
    });

    document.addEventListener('pointerup', () => {
        if (isDragging) {
            isDragging = false;
            nodeEl.style.cursor = 'pointer';
            nodeEl.style.zIndex = '10';
        }
    });
}


function getNodeIcon(type) {
    const icons = {
        cv: '📄',
        conseil: '💡',
        question: '❓',
        secteur: '🎯',
        chat: '💬'
    };
    return icons[type] || '•';
}

function drawConnections() {
    const svg = document.getElementById('connectionsSvg');
    svg.innerHTML = '';

    appState.connections.forEach(conn => {
        const fromNode = document.getElementById(`node-${conn.from}`);
        const toNode = document.getElementById(`node-${conn.to}`);

        if (!fromNode || !toNode) return;

        const fromRect = fromNode.getBoundingClientRect();
        const toRect = toNode.getBoundingClientRect();
        const svgRect = svg.getBoundingClientRect();

        const x1 = fromRect.left + fromRect.width / 2 - svgRect.left;
        const y1 = fromRect.top + fromRect.height / 2 - svgRect.top;
        const x2 = toRect.left + toRect.width / 2 - svgRect.left;
        const y2 = toRect.top + toRect.height / 2 - svgRect.top;

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        const d = `M ${x1} ${y1} Q ${(x1 + x2) / 2} ${(y1 + y2) / 2} ${x2} ${y2}`;
        path.setAttribute('d', d);
        path.setAttribute('class', 'connection-line');

        svg.appendChild(path);
    });
}

function deleteNode(nodeId) {
    // Supprimer le nœud du DOM
    const nodeEl = document.getElementById(`node-${nodeId}`);
    if (nodeEl) {
        nodeEl.remove();
    }

    // Supprimer le nœud de l'état
    const nodeIndex = appState.nodes.findIndex(n => n.id === nodeId);
    if (nodeIndex !== -1) {
        appState.nodes.splice(nodeIndex, 1);
    }

    // Supprimer toutes les connexions liées à ce nœud
    appState.connections = appState.connections.filter(
        conn => conn.from !== nodeId && conn.to !== nodeId
    );

    // Supprimer récursivement tous les nœuds enfants
    const childNodes = appState.nodes.filter(n => n.parent === nodeId);
    childNodes.forEach(child => {
        deleteNode(child.id);
    });

    // Redessiner les connexions
    drawConnections();
}

async function openChat(node) {
    const chatPanel = document.getElementById('chatPanel');
    chatPanel.classList.add('open');

    const chatInput = document.getElementById('chatInput');
    const chatSend = document.getElementById('chatSend');

    chatInput.disabled = false;
    chatSend.disabled = false;

    // Initialize chat
    try {
        const response = await fetch(`${API_BASE_URL}/start-chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: appState.sessionId })
        });

        if (!response.ok) throw new Error('Erreur');

        const data = await response.json();
        addMessage('assistant', data.message);

    } catch (error) {
        addMessage('assistant', 'Erreur lors du démarrage du chat');
    }
}

async function sendChatMessage() {
    const input = document.getElementById('chatInput');
    const message = input.value.trim();

    if (!message) return;

    addMessage('user', message);
    input.value = '';

    const sendBtn = document.getElementById('chatSend');
    sendBtn.disabled = true;

    try {
        const response = await fetch(`${API_BASE_URL}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: appState.sessionId,
                message
            })
        });

        if (!response.ok) throw new Error('Erreur');

        const data = await response.json();
        addMessage('assistant', data.message);

    } catch (error) {
        addMessage('assistant', 'Erreur: ' + error.message);
    } finally {
        sendBtn.disabled = false;
    }
}

function addMessage(role, content) {
    const messagesContainer = document.getElementById('chatMessages');

    // Remove empty state
    if (messagesContainer.children.length === 1 && messagesContainer.children[0].textContent.includes('Cliquez')) {
        messagesContainer.innerHTML = '';
    }

    const messageEl = document.createElement('div');
    messageEl.className = `message ${role}`;
    messageEl.innerHTML = `<div class="message-bubble">${escapeHtml(content)}</div>`;

    messagesContainer.appendChild(messageEl);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function zoomIn() {
    const newScale = Math.min(3, appState.canvasScale + 0.2);
    appState.canvasScale = newScale;
    updateCanvasTransform();
    updateZoomIndicator();
}

function zoomOut() {
    const newScale = Math.max(0.3, appState.canvasScale - 0.2);
    appState.canvasScale = newScale;
    updateCanvasTransform();
    updateZoomIndicator();
}

function resetView() {
    appState.canvasOffset = { x: 0, y: 0 };
    appState.canvasScale = 1;
    updateCanvasTransform();
    updateZoomIndicator();
}

function fitView() {
    if (appState.nodes.length === 0) return;

    // Calculer les limites de tous les nœuds
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

    appState.nodes.forEach(node => {
        minX = Math.min(minX, node.x);
        minY = Math.min(minY, node.y);
        maxX = Math.max(maxX, node.x + 250); // Largeur approximative du nœud
        maxY = Math.max(maxY, node.y + 150); // Hauteur approximative
    });

    const canvasContainer = document.querySelector('.canvas-container');
    const containerWidth = canvasContainer.clientWidth;
    const containerHeight = canvasContainer.clientHeight;

    const contentWidth = maxX - minX;
    const contentHeight = maxY - minY;

    // Calculer le scale pour tout afficher avec un peu de marge
    const scaleX = (containerWidth * 0.8) / contentWidth;
    const scaleY = (containerHeight * 0.8) / contentHeight;
    const newScale = Math.min(scaleX, scaleY, 1.5); // Max 1.5x

    // Centrer le contenu
    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;

    appState.canvasScale = newScale;
    appState.canvasOffset.x = containerWidth / 2 - centerX * newScale;
    appState.canvasOffset.y = containerHeight / 2 - centerY * newScale;

    updateCanvasTransform();
    updateZoomIndicator();
}

function updateCanvasTransform() {
    const canvas = document.getElementById('canvas');
    canvas.style.transform = `translate(${appState.canvasOffset.x}px, ${appState.canvasOffset.y}px) scale(${appState.canvasScale})`;
    drawConnections();
}


function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

// ==================== SYSTÈME DE QUESTIONS INTERACTIVES ====================

let responseNodeCounter = 0;

function createResponseNode(questionText, parentNode) {
    const responseId = `response-${Date.now()}-${responseNodeCounter++}`;

    // Calculer la position à droite du nœud parent
    const responseNode = {
        id: responseId,
        type: 'response',
        title: '📝 Votre Réponse',
        content: `Question: "${questionText}"`,
        x: parentNode.x + 350,
        y: parentNode.y + (responseNodeCounter * 50),
        parent: parentNode.id,
        questionText: questionText,
        interactive: false
    };

    appState.nodes.push(responseNode);

    // Créer l'élément DOM du nuage de réponse
    const canvas = document.getElementById('canvas');
    const nodeEl = document.createElement('div');
    nodeEl.className = 'node response-node';
    nodeEl.id = `node-${responseId}`;
    nodeEl.style.left = responseNode.x + 'px';
    nodeEl.style.top = responseNode.y + 'px';

    nodeEl.innerHTML = `
        <div class="node-header">
            <div class="node-icon response">📝</div>
            <div class="node-title">Votre Réponse</div>
        </div>
        <div class="node-content" style="font-size: 0.7rem; color: var(--vscode-text-muted); margin-bottom: 0.5rem;">
            ${escapeHtml(questionText)}
        </div>
        <div class="response-input-area">
            <textarea class="response-textarea" placeholder="Tapez votre réponse ici..."></textarea>
            <button class="response-submit">Valider</button>
        </div>
    `;

    // Event listener sur le bouton de soumission
    const submitBtn = nodeEl.querySelector('.response-submit');
    const textarea = nodeEl.querySelector('.response-textarea');

    submitBtn.addEventListener('click', async () => {
        const userResponse = textarea.value.trim();
        if (!userResponse) {
            alert('Veuillez entrer une réponse');
            return;
        }

        await submitResponse(responseNode, questionText, userResponse, nodeEl);
    });

    // Drag & drop
    makeNodeDraggable(nodeEl, responseNode);

    canvas.appendChild(nodeEl);

    // Ajouter connexion
    appState.connections.push({ from: parentNode.id, to: responseId });
    drawConnections();

    // Focus sur le textarea
    setTimeout(() => textarea.focus(), 100);
}

async function submitResponse(responseNode, questionText, userResponse, nodeEl) {
    const submitBtn = nodeEl.querySelector('.response-submit');
    const textarea = nodeEl.querySelector('.response-textarea');

    // Désactiver pendant le chargement
    submitBtn.disabled = true;
    submitBtn.textContent = 'Évaluation en cours...';
    textarea.disabled = true;

    try {
        const response = await fetch(`${API_BASE_URL}/evaluate-response`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: appState.sessionId,
                question: questionText,
                response: userResponse
            })
        });

        if (!response.ok) {
            throw new Error('Erreur lors de l\'évaluation');
        }

        const evaluation = await response.json();

        // Afficher l'évaluation
        displayEvaluation(responseNode, evaluation, userResponse, nodeEl);

    } catch (error) {
        console.error('Erreur:', error);
        submitBtn.disabled = false;
        submitBtn.textContent = 'Valider';
        textarea.disabled = false;
        alert('Erreur lors de l\'évaluation: ' + error.message);
    }
}

function displayEvaluation(responseNode, evaluation, userResponse, nodeEl) {
    // Remplacer le contenu du nuage avec l'évaluation
    nodeEl.innerHTML = `
        <div class="node-header">
            <div class="node-icon response">✅</div>
            <div class="node-title">Évaluation IA</div>
        </div>
        <div class="node-content" style="font-size: 0.7rem; margin-bottom: 0.5rem;">
            <strong>Question:</strong> ${escapeHtml(responseNode.questionText)}
        </div>
        <div class="node-content" style="font-size: 0.7rem; margin-bottom: 0.5rem; font-style: italic;">
            <strong>Votre réponse:</strong> ${escapeHtml(userResponse.substring(0, 100))}${userResponse.length > 100 ? '...' : ''}
        </div>
        <div class="ai-evaluation">
            <div class="ai-evaluation-title">Score: ${evaluation.score}/10</div>
            <div style="margin-bottom: 0.5rem;">${escapeHtml(evaluation.evaluation)}</div>
            
            <div style="margin-top: 0.5rem;">
                <strong style="color: var(--vscode-green);">✓ Points forts:</strong>
                <ul style="margin: 0.25rem 0; padding-left: 1.25rem; font-size: 0.7rem;">
                    ${evaluation.points_forts.map(p => `<li>${escapeHtml(p)}</li>`).join('')}
                </ul>
            </div>
            
            <div style="margin-top: 0.5rem;">
                <strong style="color: var(--vscode-orange);">→ Améliorations:</strong>
                <ul style="margin: 0.25rem 0; padding-left: 1.25rem; font-size: 0.7rem;">
                    ${evaluation.ameliorations.map(a => `<li>${escapeHtml(a)}</li>`).join('')}
                </ul>
            </div>
            
            ${evaluation.exemple_ameliore ? `
                <div style="margin-top: 0.5rem;">
                    <strong style="color: var(--vscode-blue);">💡 Exemple amélioré:</strong>
                    <div style="margin-top: 0.25rem; padding: 0.5rem; background: rgba(86, 156, 214, 0.1); border-radius: 4px; font-size: 0.7rem; font-style: italic;">
                        "${escapeHtml(evaluation.exemple_ameliore)}"
                    </div>
                </div>
            ` : ''}
        </div>
        
        ${evaluation.questions_suivantes && evaluation.questions_suivantes.length > 0 ? `
            <div class="suggested-questions">
                <div class="suggested-questions-title">Questions de suivi:</div>
                ${evaluation.questions_suivantes.map((q, i) =>
        `<div class="suggested-question-item" data-question="${escapeHtml(q)}">${escapeHtml(q)}</div>`
    ).join('')}
            </div>
        ` : ''}
    `;

    // Event listeners sur les questions suggérées
    if (evaluation.questions_suivantes && evaluation.questions_suivantes.length > 0) {
        const suggestedItems = nodeEl.querySelectorAll('.suggested-question-item');
        suggestedItems.forEach((item, index) => {
            item.addEventListener('click', (e) => {
                e.stopPropagation();
                const newQuestion = evaluation.questions_suivantes[index];
                createResponseNode(newQuestion, responseNode);
            });
        });
    }

    // Réactiver le drag & drop
    makeNodeDraggable(nodeEl, responseNode);
}


// Redraw connections on window resize
window.addEventListener('resize', () => {
    if (appState.connections.length > 0) {
        drawConnections();
    }
});
