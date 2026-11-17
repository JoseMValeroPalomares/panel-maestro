/* sonido.js — efectos cortos y discretos (Fase 5): completar, aviso y error.
   Sintetizados con Web Audio (sin archivos), APAGADOS por defecto y a volumen bajo. La preferencia es de este
   dispositivo (localStorage «panel.sonido»): en el móvil puede querer silencio y en el portátil no.
   El navegador no deja sonar nada hasta que la página recibe un gesto del usuario: el contexto se crea en el primer
   uso (que siempre viene de un clic o una tecla) y, si aun así está suspendido, se calla sin dar error. */
(function () {
  'use strict';
  const KEY = 'panel.sonido';
  const VOLUMEN = 0.07;
  let ctx = null;
  let ultimo = 0;

  const activo = () => { try { return localStorage.getItem(KEY) === '1'; } catch { return false; } };
  function setActivo(on) {
    try { localStorage.setItem(KEY, on ? '1' : '0'); } catch { /* sin almacenamiento: se queda como estaba */ }
    if (on) play('hecho', true);  // así se oye cómo suena al encenderlo
  }

  // Cada efecto: notas [frecuencia Hz, inicio s, duración s] con una envolvente suave (sin chasquidos)
  const EFECTOS = {
    hecho: { tipo: 'sine', notas: [[660, 0, 0.09], [990, 0.07, 0.14]] },
    aviso: { tipo: 'triangle', notas: [[880, 0, 0.12], [880, 0.18, 0.12]] },
    error: { tipo: 'sine', notas: [[330, 0, 0.12], [247, 0.1, 0.18]] },
  };

  function play(nombre, forzar = false) {
    if (!forzar && !activo()) return;
    const ef = EFECTOS[nombre];
    if (!ef) return;
    const ahora = performance.now();
    if (ahora - ultimo < 120) return;  // varios a la vez (completar en lote) suenan como uno
    ultimo = ahora;
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      ctx ||= new AC();
      if (ctx.state === 'suspended') ctx.resume().catch(() => {});
      const t0 = ctx.currentTime + 0.01;
      for (const [f, ini, dur] of ef.notas) {
        const osc = ctx.createOscillator();
        const g = ctx.createGain();
        osc.type = ef.tipo;
        osc.frequency.value = f;
        g.gain.setValueAtTime(0.0001, t0 + ini);
        g.gain.exponentialRampToValueAtTime(VOLUMEN, t0 + ini + 0.015);
        g.gain.exponentialRampToValueAtTime(0.0001, t0 + ini + dur);
        osc.connect(g).connect(ctx.destination);
        osc.start(t0 + ini);
        osc.stop(t0 + ini + dur + 0.02);
      }
    } catch { /* sin audio: el panel sigue igual */ }
  }

  // Interruptor de Ajustes
  function wire() {
    const sw = document.getElementById('soundSwitch');
    if (!sw) return;
    sw.checked = activo();
    sw.addEventListener('change', () => setActivo(sw.checked));
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wire);
  else wire();

  window.Sonido = { play, activo, setActivo };
})();
