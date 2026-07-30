// Affiche le lien "Admin" dans la nav uniquement pour le compte admin.
// La vraie protection est côté serveur (is_admin vérifié en base sur
// chaque appel /api/admin/*) — ceci n'est qu'un confort d'affichage.
(function () {
    try {
        const stored = localStorage.getItem('mocklyUser');
        const user = stored ? JSON.parse(stored) : null;
        if (user && user.is_admin) {
            document.querySelectorAll('.admin-nav-link').forEach((el) => el.classList.remove('hidden'));
        }
    } catch (error) {
        // ignore
    }
})();
