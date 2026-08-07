// Bootstrap Clerk (authentification) et expose window.MocklyAuth, utilisé par
// toutes les pages à la place de l'ancien localStorage.mocklyUser :
//   - clerkReady()        : charge le SDK Clerk (clé récupérée via /api/config)
//   - getToken()           : JWT de session courant, ou null si déconnecté
//   - getCurrentUser()     : appelle /api/me (mis en cache), renvoie {user, profile}
//   - fetchAuthed(url, o)  : wrapper fetch qui ajoute Authorization: Bearer <token>
//   - requireSignedIn()    : redirige vers auth.html si personne n'est connecté
//   - signOut()            : déconnexion Clerk + redirection
//
// Le token n'est jamais stocké nous-mêmes : Clerk gère sa persistance/rotation
// en interne, on ne fait que lui demander un token frais à chaque appel.

const MOCKLY_API_BASE_URL = '/api';

// Reprend la palette sombre de l'app (styles.css --vscode-*) pour que les
// composants Clerk (SignIn/SignUp) ne détonnent pas avec un encart blanc.
const MOCKLY_CLERK_APPEARANCE = {
    variables: {
        colorPrimary: '#569cd6',
        colorBackground: '#252526',
        colorInputBackground: '#1e1e1e',
        colorInputText: '#d4d4d4',
        colorText: '#d4d4d4',
        colorTextSecondary: '#858585',
        colorNeutral: '#d4d4d4',
        colorDanger: '#ff6b6b',
        colorSuccess: '#6a9955',
        borderRadius: '0.6rem',
        fontFamily: 'inherit',
    },
    elements: {
        card: { boxShadow: 'none', border: '1px solid #3e3e42' },
        rootBox: { width: '100%' },
    },
};

function _frontendApiFromPublishableKey(pk) {
    const b64 = pk.replace(/^pk_(test|live)_/, '');
    const decoded = atob(b64);
    return decoded.replace(/\$$/, '');
}

function _loadClerkScript(publishableKey) {
    return new Promise((resolve, reject) => {
        if (window.Clerk) {
            resolve(window.Clerk);
            return;
        }
        const frontendApi = _frontendApiFromPublishableKey(publishableKey);
        const script = document.createElement('script');
        script.async = true;
        script.crossOrigin = 'anonymous';
        script.setAttribute('data-clerk-publishable-key', publishableKey);
        script.src = `https://${frontendApi}/npm/@clerk/clerk-js@latest/dist/clerk.browser.js`;
        script.addEventListener('load', () => resolve(window.Clerk));
        script.addEventListener('error', () => reject(new Error('Impossible de charger Clerk')));
        document.head.appendChild(script);
    });
}

let _clerkReadyPromise = null;

function clerkReady() {
    if (_clerkReadyPromise) return _clerkReadyPromise;
    _clerkReadyPromise = (async () => {
        const configRes = await fetch(`${MOCKLY_API_BASE_URL}/config`);
        const config = await configRes.json();
        if (!config.clerk_publishable_key) {
            console.error('[MocklyAuth] Clerk non configuré : CLERK_PUBLISHABLE_KEY manquant côté serveur.');
            return null;
        }
        const Clerk = await _loadClerkScript(config.clerk_publishable_key);
        await Clerk.load({ appearance: MOCKLY_CLERK_APPEARANCE });
        console.log('[MocklyAuth] Clerk.load() résolu — user:', Clerk.user ? Clerk.user.id : null,
            '| session:', Clerk.session ? Clerk.session.id : null,
            '| status session:', Clerk.session ? Clerk.session.status : 'n/a');
        return Clerk;
    })();
    return _clerkReadyPromise;
}

async function getToken() {
    const Clerk = await clerkReady();
    if (!Clerk || !Clerk.session) {
        console.log('[MocklyAuth] getToken() : pas de session Clerk active.');
        return null;
    }
    try {
        const token = await Clerk.session.getToken();
        console.log('[MocklyAuth] getToken() : token', token ? 'obtenu' : 'vide (null)');
        return token;
    } catch (error) {
        console.error('[MocklyAuth] getToken() a levé une erreur :', error);
        return null;
    }
}

let _cachedMe = null;
let _pendingMePromise = null;

async function getCurrentUser(opts = {}) {
    if (opts.force) {
        // Ignore aussi une éventuelle promesse déjà réglée (bfcache : le
        // navigateur peut restaurer l'état JS d'une page précédente au lieu
        // d'en réexécuter une neuve, laissant _pendingMePromise pointer sur
        // une réponse obsolète déjà résolue — un simple null sur _cachedMe ne
        // suffit pas à contourner ça).
        _cachedMe = null;
        _pendingMePromise = null;
    }
    if (_cachedMe) return _cachedMe;
    if (_pendingMePromise) return _pendingMePromise;

    _pendingMePromise = (async () => {
        const token = await getToken();
        if (!token) {
            console.warn('[MocklyAuth] getCurrentUser() : pas de token, /api/me non appelé.');
            _cachedMe = null;
            return null;
        }
        try {
            console.log('[MocklyAuth] getCurrentUser() : appel /api/me...');
            const res = await fetch(`${MOCKLY_API_BASE_URL}/me`, {
                headers: { Authorization: `Bearer ${token}` }
            });
            const body = await res.text();
            console.log('[MocklyAuth] /api/me →', res.status, body);
            if (!res.ok) {
                _cachedMe = null;
                return null;
            }
            _cachedMe = JSON.parse(body); // { user: {...}, profile: {...} }
            return _cachedMe;
        } catch (error) {
            console.error('[MocklyAuth] /api/me a levé une erreur réseau :', error);
            _cachedMe = null;
            return null;
        }
    })();

    const result = await _pendingMePromise;
    _pendingMePromise = null;
    return result;
}

function invalidateUserCache() {
    _cachedMe = null;
    _pendingMePromise = null;
}

async function fetchAuthed(url, options = {}) {
    const token = await getToken();
    const headers = Object.assign({}, options.headers || {});
    if (token) headers['Authorization'] = `Bearer ${token}`;
    return fetch(url, Object.assign({}, options, { headers }));
}

function _wait(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

async function requireSignedIn(redirectTo = 'auth.html') {
    const Clerk = await clerkReady();
    if (!Clerk) {
        window.location.replace(redirectTo);
        return null;
    }

    // Sur un rechargement complet de page, Clerk.load() peut se résoudre une
    // fraction de seconde avant que Clerk.session ne soit pleinement rattaché
    // (observé en prod : Clerk.load() annonce une session active, mais
    // Clerk.session est encore vide juste après) — on retente une fois après
    // un court délai avant d'abandonner et de rediriger, pour éviter de
    // renvoyer vers auth.html un utilisateur pourtant bien connecté.
    if (!Clerk.session) {
        console.warn('[MocklyAuth] requireSignedIn() : pas de session au premier essai, nouvelle tentative dans 400ms...');
        await _wait(400);
    }
    if (!Clerk.session) {
        console.warn('[MocklyAuth] requireSignedIn() : toujours pas de session après la tentative, redirection', redirectTo);
        window.location.replace(redirectTo);
        return null;
    }

    // Appel /api/me totalement autonome, SANS passer par getCurrentUser()/
    // son cache partagé (_cachedMe, _pendingMePromise) : sur une page comme
    // workspace.html, script.js et nav-admin.js appellent aussi
    // getCurrentUser() en parallèle, et malgré le force:true testé
    // précédemment, ce contrôle d'accès — le plus critique de toute l'app —
    // continuait à échouer de façon inexplicable sans même logguer sa propre
    // tentative réseau. Plutôt que de continuer à deviner l'interaction
    // exacte avec les autres appelants, on élimine le risque : ce chemin ne
    // touche plus aucun état partagé.
    let token;
    try {
        token = await Clerk.session.getToken();
    } catch (error) {
        console.error('[MocklyAuth] requireSignedIn() : Clerk.session.getToken() a levé une erreur :', error);
        window.location.replace(redirectTo);
        return null;
    }
    if (!token) {
        console.warn('[MocklyAuth] requireSignedIn() : getToken() a renvoyé vide, redirection', redirectTo);
        window.location.replace(redirectTo);
        return null;
    }

    let res;
    try {
        res = await fetch(`${MOCKLY_API_BASE_URL}/me`, { headers: { Authorization: `Bearer ${token}` } });
    } catch (error) {
        console.error('[MocklyAuth] requireSignedIn() : fetch /api/me a levé une erreur réseau :', error);
        window.location.replace(redirectTo);
        return null;
    }
    console.log('[MocklyAuth] requireSignedIn() : /api/me →', res.status);
    if (!res.ok) {
        window.location.replace(redirectTo);
        return null;
    }

    const me = await res.json();
    _cachedMe = me; // évite un appel /api/me redondant si getCurrentUser() est rappelé juste après sur cette page
    return me;
}

// Filet de sécurité supplémentaire : si le navigateur restaure cette page
// depuis le bfcache (retour arrière/avant) plutôt que de la recharger à
// neuf, tout l'état JS ci-dessus (y compris une éventuelle réponse /api/me
// mise en cache) peut être obsolète — on le jette pour forcer une
// revérification propre au prochain appel.
window.addEventListener('pageshow', (event) => {
    if (event.persisted) {
        // On ne touche pas à _clerkReadyPromise : window.Clerk (préservé par
        // le bfcache) reste valide et rappeler Clerk.load() dessus n'est pas
        // garanti sans risque. Seule la réponse /api/me mise en cache doit
        // être considérée obsolète.
        console.log('[MocklyAuth] Page restaurée depuis le bfcache : invalidation du cache /api/me.');
        invalidateUserCache();
    }
});

async function signOut(redirectTo = 'auth.html') {
    const Clerk = await clerkReady();
    invalidateUserCache();
    if (Clerk) {
        await Clerk.signOut();
    }
    window.location.href = redirectTo;
}

window.MocklyAuth = {
    clerkReady,
    getToken,
    getCurrentUser,
    invalidateUserCache,
    fetchAuthed,
    requireSignedIn,
    signOut,
};
