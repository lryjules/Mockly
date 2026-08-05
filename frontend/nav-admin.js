// Affiche le lien "Admin" (ou "École") dans la nav selon le type de compte.
// La vraie protection est côté serveur (is_admin / is_school_admin vérifié en
// base sur chaque appel /api/admin/* ou /api/school/*) — ceci n'est qu'un
// confort d'affichage. Nécessite clerk-auth.js chargé avant ce script.
(async function () {
    try {
        if (!window.MocklyAuth) return;
        const me = await window.MocklyAuth.getCurrentUser();
        const user = me && me.user;
        if (user && user.is_admin) {
            document.querySelectorAll('.admin-nav-link').forEach((el) => el.classList.remove('hidden'));
        }
        if (user && user.is_school_admin) {
            document.querySelectorAll('.school-nav-link').forEach((el) => el.classList.remove('hidden'));
        }
    } catch (error) {
        // ignore
    }
})();
