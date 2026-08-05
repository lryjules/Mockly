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
            console.error('Clerk non configuré : CLERK_PUBLISHABLE_KEY manquant côté serveur.');
            return null;
        }
        const Clerk = await _loadClerkScript(config.clerk_publishable_key);
        await Clerk.load();
        return Clerk;
    })();
    return _clerkReadyPromise;
}

async function getToken() {
    const Clerk = await clerkReady();
    if (!Clerk || !Clerk.session) return null;
    try {
        return await Clerk.session.getToken();
    } catch (error) {
        return null;
    }
}

let _cachedMe = null;
let _pendingMePromise = null;

async function getCurrentUser(opts = {}) {
    if (opts.force) {
        _cachedMe = null;
    }
    if (_cachedMe) return _cachedMe;
    if (_pendingMePromise) return _pendingMePromise;

    _pendingMePromise = (async () => {
        const token = await getToken();
        if (!token) {
            _cachedMe = null;
            return null;
        }
        try {
            const res = await fetch(`${MOCKLY_API_BASE_URL}/me`, {
                headers: { Authorization: `Bearer ${token}` }
            });
            if (!res.ok) {
                _cachedMe = null;
                return null;
            }
            _cachedMe = await res.json(); // { user: {...}, profile: {...} }
            return _cachedMe;
        } catch (error) {
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

async function requireSignedIn(redirectTo = 'auth.html') {
    const Clerk = await clerkReady();
    if (!Clerk || !Clerk.session) {
        window.location.replace(redirectTo);
        return null;
    }
    const me = await getCurrentUser();
    if (!me) {
        window.location.replace(redirectTo);
        return null;
    }
    return me;
}

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
