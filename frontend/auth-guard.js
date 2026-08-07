// Empêche l'accès aux pages qui l'incluent tant que Clerk n'a pas confirmé
// une session active — remplace l'ancien contrôle synchrone sur
// localStorage.mocklyUser. La vérification Clerk est forcément asynchrone
// (chargement du SDK + appel réseau), donc on masque la page immédiatement
// (avant même le premier paint, ce script est chargé bloquant dans <head>)
// et on ne la révèle qu'une fois la session confirmée ; sinon redirection.
// Nécessite que clerk-auth.js soit chargé juste avant ce script.
(function () {
    document.documentElement.style.visibility = 'hidden';

    function reveal() {
        document.documentElement.style.visibility = '';
    }

    window.addEventListener('DOMContentLoaded', async () => {
        if (!window.MocklyAuth) {
            // clerk-auth.js pas chargé avant ce script : on ne peut rien vérifier,
            // mieux vaut renvoyer vers l'auth que de laisser une page bloquée invisible.
            console.error('[AuthGuard] clerk-auth.js absent, redirection auth.html');
            window.location.replace('auth.html');
            return;
        }
        console.log('[AuthGuard] vérification de la session...');
        const me = await window.MocklyAuth.requireSignedIn('auth.html');
        console.log('[AuthGuard] requireSignedIn() →', me);
        if (me) reveal();
    });
})();
