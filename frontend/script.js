// API Configuration
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

// Clé historique (avant l'isolation par compte) : un seul espace de travail
// partagé par tout le navigateur, quel que soit le compte connecté.
const LEGACY_WORKSPACE_KEY = 'mocklyWorkspaceState';

// L'espace de travail est propre à chaque compte : deux utilisateurs sur le
// même navigateur ne doivent jamais voir le CV/la carte mentale de l'autre.
function getWorkspaceStorageKey() {
    const user = getCurrentUser();
    return user && user.id ? `mocklyWorkspaceState:${user.id}` : null;
}

// Reprend une éventuelle sauvegarde de l'ancien espace partagé et l'attribue
// au compte actuellement connecté (la seule attribution raisonnable possible),
// puis supprime la clé partagée pour qu'elle ne fuite plus vers d'autres comptes.
function migrateLegacyWorkspaceState() {
    const legacy = localStorage.getItem(LEGACY_WORKSPACE_KEY);
    if (!legacy) return;

    const key = getWorkspaceStorageKey();
    if (key && !localStorage.getItem(key)) {
        localStorage.setItem(key, legacy);
    }
    localStorage.removeItem(LEGACY_WORKSPACE_KEY);
}

// Persiste l'essentiel de l'état (tout ce qui est nécessaire pour reconstruire
// la carte mentale) pour que l'analyse de CV survive à un changement d'onglet
// ou un rechargement de page.
function saveWorkspaceState() {
    const key = getWorkspaceStorageKey();
    if (!key) return;

    const toSave = {
        sessionId: appState.sessionId,
        cvData: appState.cvData,
        analysisData: appState.analysisData,
        nodes: appState.nodes,
        connections: appState.connections,
        canvasOffset: appState.canvasOffset,
        canvasScale: appState.canvasScale,
    };
    try {
        localStorage.setItem(key, JSON.stringify(toSave));
    } catch (error) {
        console.warn('Impossible de sauvegarder l\'espace de travail :', error);
    }
}

function loadWorkspaceState() {
    const key = getWorkspaceStorageKey();
    if (!key) return null;

    const stored = localStorage.getItem(key);
    if (!stored) return null;
    try {
        return JSON.parse(stored);
    } catch (error) {
        return null;
    }
}

function clearWorkspace() {
    if (!confirm('Vider l\'espace de travail ? Le CV analysé, la carte mentale et tes réponses seront supprimés (uniquement de cet écran, pas de ton historique).')) {
        return;
    }

    const key = getWorkspaceStorageKey();
    if (key) localStorage.removeItem(key);

    appState.sessionId = null;
    appState.cvData = null;
    appState.analysisData = null;
    appState.nodes = [];
    appState.connections = [];
    appState.canvasOffset = { x: 0, y: 0 };
    appState.canvasScale = 1;

    document.getElementById('canvas').innerHTML = '';
    document.getElementById('connectionsSvg').innerHTML = '';
    updateCanvasTransform();
    updateZoomIndicator();

    document.getElementById('infoSection').classList.add('hidden');
    document.getElementById('contextSection').classList.add('hidden');
    document.getElementById('sectorInput').value = '';
    document.getElementById('companyInput').value = '';
    document.getElementById('roleInput').value = '';

    const generateBtn = document.getElementById('generateBtn');
    generateBtn.disabled = false;
    generateBtn.innerHTML = 'Générer la carte mentale';

    document.getElementById('uploadZone').innerHTML = `
        <div class="upload-icon">📄</div>
        <div class="upload-text">Glissez votre CV ici</div>
        <div class="upload-hint">PDF ou DOCX</div>
    `;
    document.getElementById('cvFile').value = '';

    document.getElementById('chatPanel').classList.remove('open');
    document.getElementById('chatMessages').innerHTML = `
        <div style="text-align: center; padding: 2rem; color: var(--vscode-text-muted); font-size: 0.875rem;">
            Cliquez sur un nœud "Coach" pour démarrer la conversation
        </div>
    `;
    document.getElementById('chatInput').disabled = true;
    document.getElementById('chatSend').disabled = true;
}

// Reconstruit la carte mentale (nœuds + connexions) à partir de l'état sauvegardé,
// pour que l'analyse de CV soit toujours là après un rechargement de page.
function restoreWorkspaceState() {
    migrateLegacyWorkspaceState();

    const saved = loadWorkspaceState();
    if (!saved || !saved.cvData) return;

    appState.sessionId = saved.sessionId;
    appState.cvData = saved.cvData;
    appState.analysisData = saved.analysisData;
    appState.nodes = [];
    appState.connections = saved.connections || [];
    appState.canvasOffset = saved.canvasOffset || { x: 0, y: 0 };
    appState.canvasScale = saved.canvasScale || 1;

    document.getElementById('cvInfo').innerHTML = `
        <div><strong>Nom:</strong> ${saved.cvData.nom || 'Non trouvé'}</div>
        <div><strong>Email:</strong> ${saved.cvData.email || 'Non trouvé'}</div>
        <div><strong>Compétences:</strong> ${saved.cvData.competences?.slice(0, 3).join(', ') || 'Aucune'}</div>
    `;
    document.getElementById('infoSection').classList.remove('hidden');
    document.getElementById('contextSection').classList.remove('hidden');
    document.getElementById('uploadZone').innerHTML = `
        <div class="upload-icon">✅</div>
        <div class="upload-text">CV analysé avec succès</div>
        <div class="upload-hint">Cliquez pour changer</div>
    `;

    (saved.nodes || []).forEach((node) => {
        appState.nodes.push(node);
        if (node.type === 'response') {
            renderResponseNode(node);
        } else {
            renderNode(node);
        }
    });

    updateCanvasTransform();
    updateZoomIndicator();
    drawConnections();
}

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    initializeCanvas();
    restoreWorkspaceState();
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

    // Clear workspace
    document.getElementById('clearWorkspaceBtn').addEventListener('click', clearWorkspace);
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
            if (appState.cvData) saveWorkspaceState();
        }
    });

    // Zoom avec la molette : proportionnel à l'ampleur du scroll (pas un pas
    // fixe) pour un ressenti naturel, aussi bien à la molette qu'au trackpad.
    canvasContainer.addEventListener('wheel', (e) => {
        e.preventDefault();

        const zoomIntensity = 0.0018;
        const factor = Math.exp(-e.deltaY * zoomIntensity);
        const newScale = Math.max(0.3, Math.min(3, appState.canvasScale * factor));

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

        saveWorkspaceState();

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
        saveWorkspaceState();

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

// Fait apparaître un nœud en fondu + léger zoom plutôt qu'un pop-in brutal.
// Double rAF nécessaire pour garantir que l'état initial (opacity:0, scale
// réduite) soit bien peint avant de déclencher la transition vers l'état final.
function playNodeAppearAnimation(nodeEl) {
    nodeEl.classList.add('node-appear');
    requestAnimationFrame(() => {
        requestAnimationFrame(() => nodeEl.classList.remove('node-appear'));
    });
}

function renderNode(node) {
    const canvas = document.getElementById('canvas');

    const nodeEl = document.createElement('div');
    nodeEl.className = `node ${node.type === 'cv' ? 'root' : ''}`;
    nodeEl.id = `node-${node.id}`;
    nodeEl.style.left = node.x + 'px';
    nodeEl.style.top = node.y + 'px';
    applyStoredNodeSize(nodeEl, node);

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
    makeNodeResizable(nodeEl, node);

    canvas.appendChild(nodeEl);
    playNodeAppearAnimation(nodeEl);

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
        // Ne pas drag si on clique sur un bouton, un tag ou une poignée de redimensionnement
        if (e.target.classList.contains('node-expand') ||
            e.target.classList.contains('node-tag') ||
            e.target.classList.contains('node-delete') ||
            e.target.classList.contains('node-resize-handle')) {
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

        // Redessiner les connexions en temps réel (regroupé par frame)
        scheduleDrawConnections();
    });

    document.addEventListener('pointerup', () => {
        if (isDragging) {
            isDragging = false;
            nodeEl.style.cursor = 'pointer';
            nodeEl.style.zIndex = '10';
            saveWorkspaceState();
        }
    });
}

const NODE_MIN_WIDTH = 180;
const NODE_MAX_WIDTH = 900;
const NODE_MIN_HEIGHT = 90;
const NODE_MAX_HEIGHT = 700;

// Applique une taille précédemment choisie par l'utilisateur (stockée sur le
// nœud) : utilisé aussi bien à la création qu'à la restauration depuis
// l'état sauvegardé, pour que le redimensionnement survive à un rechargement.
function applyStoredNodeSize(nodeEl, node) {
    if (node.width) {
        nodeEl.style.width = node.width + 'px';
        nodeEl.style.maxWidth = 'none';
    }
    if (node.height) {
        nodeEl.style.height = node.height + 'px';
    }
}

// Ajoute des poignées sur les bords droit/bas et le coin d'une carte pour
// permettre de modifier sa largeur et/ou sa hauteur en cliquant-glissant.
function makeNodeResizable(nodeEl, node) {
    const rightHandle = document.createElement('div');
    rightHandle.className = 'node-resize-handle right';
    const bottomHandle = document.createElement('div');
    bottomHandle.className = 'node-resize-handle bottom';
    const cornerHandle = document.createElement('div');
    cornerHandle.className = 'node-resize-handle corner';
    nodeEl.appendChild(rightHandle);
    nodeEl.appendChild(bottomHandle);
    nodeEl.appendChild(cornerHandle);

    function startResize(handleEl, resizeWidth, resizeHeight) {
        return (e) => {
            e.stopPropagation();
            e.preventDefault();

            const startX = e.clientX;
            const startY = e.clientY;
            const rect = nodeEl.getBoundingClientRect();
            const startWidth = rect.width;
            const startHeight = rect.height;

            nodeEl.classList.add('resizing');
            handleEl.classList.add('active');

            function onMove(ev) {
                if (resizeWidth) {
                    const newWidth = Math.max(NODE_MIN_WIDTH, Math.min(NODE_MAX_WIDTH, startWidth + (ev.clientX - startX)));
                    node.width = newWidth;
                    nodeEl.style.width = newWidth + 'px';
                    nodeEl.style.maxWidth = 'none';
                }
                if (resizeHeight) {
                    const newHeight = Math.max(NODE_MIN_HEIGHT, Math.min(NODE_MAX_HEIGHT, startHeight + (ev.clientY - startY)));
                    node.height = newHeight;
                    nodeEl.style.height = newHeight + 'px';
                }
                scheduleDrawConnections();
            }

            function onUp() {
                document.removeEventListener('pointermove', onMove);
                document.removeEventListener('pointerup', onUp);
                nodeEl.classList.remove('resizing');
                handleEl.classList.remove('active');
                saveWorkspaceState();
            }

            document.addEventListener('pointermove', onMove);
            document.addEventListener('pointerup', onUp);
        };
    }

    rightHandle.addEventListener('pointerdown', startResize(rightHandle, true, false));
    bottomHandle.addEventListener('pointerdown', startResize(bottomHandle, false, true));
    cornerHandle.addEventListener('pointerdown', startResize(cornerHandle, true, true));
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

// Pendant un drag ou un pan, pointermove peut se déclencher bien plus souvent
// qu'une frame d'affichage : on regroupe les appels avec requestAnimationFrame
// pour éviter de recalculer les connexions (et de forcer un reflow) plusieurs
// fois par frame, ce qui saccadait le déplacement des nœuds.
let connectionsRafId = null;
function scheduleDrawConnections() {
    if (connectionsRafId) return;
    connectionsRafId = requestAnimationFrame(() => {
        connectionsRafId = null;
        drawConnections();
    });
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
    // Supprimer le nœud du DOM (fondu de sortie plutôt qu'une disparition brutale)
    const nodeEl = document.getElementById(`node-${nodeId}`);
    if (nodeEl) {
        nodeEl.classList.add('node-exit');
        setTimeout(() => nodeEl.remove(), 220);
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
    saveWorkspaceState();
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

// Anime canvasOffset/canvasScale vers une cible avec un easing, au lieu de
// sauter instantanément — utilisé par les boutons (zoom, reset, fit) où un
// changement de vue net rend l'expérience plus heurtée. Le drag et le zoom
// à la molette restent instantanés (1:1 avec le geste), volontairement non animés.
let viewAnimationId = null;
function animateViewTo(targetOffset, targetScale, duration = 320) {
    if (viewAnimationId) cancelAnimationFrame(viewAnimationId);

    const startOffset = { ...appState.canvasOffset };
    const startScale = appState.canvasScale;
    const startTime = performance.now();
    const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);

    function tick(now) {
        const t = Math.min(1, (now - startTime) / duration);
        const eased = easeOutCubic(t);

        appState.canvasOffset.x = startOffset.x + (targetOffset.x - startOffset.x) * eased;
        appState.canvasOffset.y = startOffset.y + (targetOffset.y - startOffset.y) * eased;
        appState.canvasScale = startScale + (targetScale - startScale) * eased;

        updateCanvasTransform();
        updateZoomIndicator();

        if (t < 1) {
            viewAnimationId = requestAnimationFrame(tick);
        } else {
            viewAnimationId = null;
            if (appState.cvData) saveWorkspaceState();
        }
    }

    viewAnimationId = requestAnimationFrame(tick);
}

function zoomIn() {
    const newScale = Math.min(3, appState.canvasScale + 0.2);
    animateViewTo(appState.canvasOffset, newScale);
}

function zoomOut() {
    const newScale = Math.max(0.3, appState.canvasScale - 0.2);
    animateViewTo(appState.canvasOffset, newScale);
}

function resetView() {
    animateViewTo({ x: 0, y: 0 }, 1);
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

    animateViewTo({
        x: containerWidth / 2 - centerX * newScale,
        y: containerHeight / 2 - centerY * newScale,
    }, newScale);
}

function updateCanvasTransform() {
    const canvas = document.getElementById('canvas');
    canvas.style.transform = `translate(${appState.canvasOffset.x}px, ${appState.canvasOffset.y}px) scale(${appState.canvasScale})`;
    scheduleDrawConnections();
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
        interactive: false,
        userResponse: null,
        evaluation: null
    };

    appState.nodes.push(responseNode);
    appState.connections.push({ from: parentNode.id, to: responseId });

    const nodeEl = renderResponseNode(responseNode);
    drawConnections();
    saveWorkspaceState();

    // Focus sur le textarea (nouveau nœud = toujours en attente de réponse)
    const textarea = nodeEl.querySelector('.response-textarea');
    if (textarea) setTimeout(() => textarea.focus(), 100);
}

// Construit et insère l'élément DOM d'un nœud "réponse", que ce soit à la
// création (en attente de réponse) ou à la restauration depuis l'état
// sauvegardé (où l'évaluation peut déjà exister).
function renderResponseNode(node) {
    const canvas = document.getElementById('canvas');
    const nodeEl = document.createElement('div');
    nodeEl.className = 'node response-node';
    nodeEl.id = `node-${node.id}`;
    nodeEl.style.left = node.x + 'px';
    nodeEl.style.top = node.y + 'px';
    applyStoredNodeSize(nodeEl, node);
    canvas.appendChild(nodeEl);
    playNodeAppearAnimation(nodeEl);

    if (node.evaluation) {
        renderEvaluationContent(node, nodeEl);
    } else {
        renderPendingResponseContent(node, nodeEl);
    }

    makeNodeDraggable(nodeEl, node);
    makeNodeResizable(nodeEl, node);
    return nodeEl;
}

function renderPendingResponseContent(node, nodeEl) {
    nodeEl.innerHTML = `
        <div class="node-header">
            <div class="node-icon response">📝</div>
            <div class="node-title">Votre Réponse</div>
        </div>
        <div class="node-content" style="font-size: 0.7rem; color: var(--vscode-text-muted); margin-bottom: 0.5rem;">
            ${escapeHtml(node.questionText)}
        </div>
        <div class="response-input-area">
            <textarea class="response-textarea" placeholder="Tapez votre réponse ici...">${escapeHtml(node.userResponse || '')}</textarea>
            <button class="response-submit">Valider</button>
        </div>
    `;

    const submitBtn = nodeEl.querySelector('.response-submit');
    const textarea = nodeEl.querySelector('.response-textarea');

    submitBtn.addEventListener('click', async () => {
        const userResponse = textarea.value.trim();
        if (!userResponse) {
            alert('Veuillez entrer une réponse');
            return;
        }

        await submitResponse(node, userResponse, nodeEl);
    });
}

async function submitResponse(responseNode, userResponse, nodeEl) {
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
                question: responseNode.questionText,
                response: userResponse
            })
        });

        if (!response.ok) {
            throw new Error('Erreur lors de l\'évaluation');
        }

        const evaluation = await response.json();

        // Persister le résultat sur le nœud pour qu'il survive à un rechargement
        responseNode.userResponse = userResponse;
        responseNode.evaluation = evaluation;
        saveWorkspaceState();

        renderEvaluationContent(responseNode, nodeEl);
        makeNodeDraggable(nodeEl, responseNode);
        makeNodeResizable(nodeEl, responseNode);

    } catch (error) {
        console.error('Erreur:', error);
        submitBtn.disabled = false;
        submitBtn.textContent = 'Valider';
        textarea.disabled = false;
        alert('Erreur lors de l\'évaluation: ' + error.message);
    }
}

function renderEvaluationContent(responseNode, nodeEl) {
    const evaluation = responseNode.evaluation;
    const userResponse = responseNode.userResponse || '';

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
}


// Redraw connections on window resize
window.addEventListener('resize', () => {
    if (appState.connections.length > 0) {
        drawConnections();
    }
});
