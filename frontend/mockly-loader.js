// Logo Mockly animé, réutilisé partout où l'app affiche un état de chargement
// (remplace l'ancien <div class="spinner"></div>). Reprend en CSS pur la forme
// du nouveau logo (3 barres verticales arrondies, tailles inégales) plutôt que
// de découper une image — plus net à toute taille, et anime naturellement
// comme un égaliseur audio.
const MOCKLY_LOADER_BARS = ['left', 'center', 'right'];

function mocklyLoader(size = '') {
    const sizeClass = size === 'lg' ? ' mockly-loader-lg' : '';
    const bars = MOCKLY_LOADER_BARS.map((name) => `<span class="mockly-loader-bar mockly-loader-bar-${name}"></span>`).join('');
    return `<span class="mockly-loader${sizeClass}" aria-hidden="true">${bars}</span>`;
}
