// Carga un script clásico del front (IIFE que cuelga su API de window/self) en un contexto aislado, sin navegador.
// Solo vale para módulos sin DOM al cargar: el contexto trae lo justo (URL, consola) y nada de document.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const RAIZ = fileURLToPath(new URL('../../', import.meta.url));

export function cargar(ruta, extra = {}) {
  const ctx = { URL, console, ...extra };
  ctx.window = ctx;
  ctx.self = ctx;
  vm.createContext(ctx);
  vm.runInContext(readFileSync(RAIZ + ruta, 'utf8'), ctx, { filename: ruta });
  return ctx;
}
