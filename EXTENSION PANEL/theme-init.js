/* Aplica el tema elegido en las opciones antes de pintar (localStorage es síncrono y lo comparten el popup y las
   opciones). Por defecto, Catppuccin Mocha. La lista de temas sale de lib/themes.js (generado). */
try {
  var t = localStorage.getItem('theme');
  var ok = (self.PANEL_THEMES || []).some(function (x) { return x.key === t; });
  document.documentElement.setAttribute('data-theme', ok ? t : 'mocha');
} catch (e) {
  document.documentElement.setAttribute('data-theme', 'mocha');
}
