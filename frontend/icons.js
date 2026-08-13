// Petit helper partagé pour insérer une icône (assets/icons.svg) dans du HTML
// généré en JS, sans jamais recourir à un emoji. Usage : `${mIcon('star')}`.
function mIcon(name, extraClass) {
    const cls = extraClass ? `icon ${extraClass}` : 'icon';
    return `<svg class="${cls}" aria-hidden="true"><use href="assets/icons.svg#${name}"></use></svg>`;
}
