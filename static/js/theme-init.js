/* Se carga en <head> (bloqueante y diminuto) para aplicar el tema antes del primer pintado. */
// Tema guardado (por defecto Catppuccin Mocha); se aplica antes de pintar para que no parpadee
try {
  var th = localStorage.getItem('theme');
  // Cualquier nombre con forma válida: un tema que no exista cae en Mocha (es el de :root en themes.css)
  document.documentElement.setAttribute('data-theme', /^[a-z0-9-]{2,24}$/.test(th || '') ? th : 'mocha');
} catch (e) { document.documentElement.setAttribute('data-theme', 'mocha'); }
// Paleta propia (P-5, tema-propio.js): su CSS ya hecho, guardado en este navegador, antes de pintar
try {
  var pc = localStorage.getItem('theme-propia-css');
  if (pc) { var st = document.createElement('style'); st.id = 'themePropia'; st.textContent = pc; document.head.appendChild(st); }
} catch (e) {}
// Navegación lateral plegada a iconos: la preferencia guardada manda; sin ella, plegada por debajo de 1024 px
try {
  var n = localStorage.getItem('nav');
  if (n === 'collapsed' || (n !== 'expanded' && window.innerWidth < 1024)) document.documentElement.classList.add('nav-collapsed');
} catch (e) {}
// Transición entre secciones donde el navegador no la tiene entre páginas (Firefox): si se llegó desde un enlace del
// panel hace un momento (ui.js lo apunta al pulsarlo), la página entra animada desde el primer pintado (ds.css)
try {
  var va = Number(sessionStorage.getItem('panel.nav-anim') || 0);
  sessionStorage.removeItem('panel.nav-anim');
  if (va && Date.now() - va < 4000 && !('CSSViewTransitionRule' in window)) document.documentElement.classList.add('nav-entrando');
} catch (e) {}
