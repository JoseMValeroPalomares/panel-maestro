/* Se carga en <head> (bloqueante y diminuto) para aplicar el tema antes del primer pintado. */
// Tema guardado (por defecto Catppuccin Mocha); se aplica antes de pintar para que no parpadee
try {
  var th = localStorage.getItem('theme');
  // Cualquier nombre con forma válida: un tema que no exista cae en Mocha (es el de :root en themes.css)
  document.documentElement.setAttribute('data-theme', /^[a-z0-9-]{2,24}$/.test(th || '') ? th : 'mocha');
} catch (e) { document.documentElement.setAttribute('data-theme', 'mocha'); }
// Navegación lateral plegada a iconos: la preferencia guardada manda; sin ella, plegada por debajo de 1024 px
try {
  var n = localStorage.getItem('nav');
  if (n === 'collapsed' || (n !== 'expanded' && window.innerWidth < 1024)) document.documentElement.classList.add('nav-collapsed');
} catch (e) {}
