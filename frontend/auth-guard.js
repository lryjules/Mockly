// Empêche l'accès aux pages qui l'incluent si personne n'est connecté —
// notamment après une déconnexion (le lien "Déconnexion" vide déjà
// localStorage.mocklyUser). Placé en <head>, chargé de façon bloquante
// (pas de defer/async), pour rediriger avant que la page ne s'affiche.
(function () {
    let user = null;
    try {
        user = JSON.parse(localStorage.getItem('mocklyUser') || 'null');
    } catch (error) {
        user = null;
    }
    if (!user || !user.id) {
        window.location.replace('auth.html');
    }
})();
