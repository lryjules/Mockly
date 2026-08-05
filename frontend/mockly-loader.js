// Logo Mockly animé, réutilisé partout où l'app affiche un état de chargement
// (remplace l'ancien <div class="spinner"></div>). Le logo réel (assets/logo.png)
// est découpé en 4 bandes (arc + 3 vagues) empilées en position absolue, pour
// pouvoir animer chaque trait indépendamment tout en gardant le rendu exact.
const MOCKLY_LOADER_PIECES = [
    { name: 'arc', top: 0.0, height: 29.2 },
    { name: 'wave1', top: 37.5, height: 20.2 },
    { name: 'wave2', top: 61.3, height: 18.6 },
    { name: 'wave3', top: 82.2, height: 17.4 },
];

function mocklyLoader(size = '') {
    const sizeClass = size === 'lg' ? ' mockly-loader-lg' : '';
    const pieces = MOCKLY_LOADER_PIECES.map((p) => `
        <img src="assets/logo-${p.name}.png" alt="" class="mockly-logo-${p.name}"
             style="position:absolute;left:0;top:${p.top}%;width:100%;height:${p.height}%;">
    `).join('');
    return `<span class="mockly-loader${sizeClass}" aria-hidden="true" style="position:relative;display:inline-block;">${pieces}</span>`;
}
