// Affiche le lien "Admin" (ou "École") dans la nav selon le type de compte.
// La vraie protection est côté serveur (is_admin / is_school_admin vérifié en
// base sur chaque appel /api/admin/* ou /api/school/*) — ceci n'est qu'un
// confort d'affichage.
(function () {
    try {
        const stored = localStorage.getItem('mocklyUser');
        const user = stored ? JSON.parse(stored) : null;
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
