// Copia las librerías de node_modules a static/vendor (servidas por el propio panel:
// sin CDNs, funciona offline como PWA y permite una CSP estricta).
import { cpSync, mkdirSync, rmSync, readFileSync, readdirSync, writeFileSync, existsSync } from 'node:fs';

const out = 'static/vendor';
rmSync(out, { recursive: true, force: true });
const files = [
  ['node_modules/marked/marked.min.js', 'marked/marked.min.js'],
  ['node_modules/dompurify/dist/purify.min.js', 'dompurify/purify.min.js'],
  ['node_modules/katex/dist/katex.min.js', 'katex/katex.min.js'],
  ['node_modules/katex/dist/katex.min.css', 'katex/katex.min.css'],
  ['node_modules/katex/dist/contrib/auto-render.min.js', 'katex/auto-render.min.js'],
  ['node_modules/katex/dist/fonts', 'katex/fonts'],
  ['node_modules/@highlightjs/cdn-assets/highlight.min.js', 'highlight/highlight.min.js'],
  ['node_modules/@highlightjs/cdn-assets/styles/github.min.css', 'highlight/github.min.css'],
  ['node_modules/@highlightjs/cdn-assets/styles/github-dark.min.css', 'highlight/github-dark.min.css'],
  ['node_modules/vis-network/standalone/umd/vis-network.min.js', 'vis-network/vis-network.min.js'],
];
for (const [src, dst] of files) {
  const target = `${out}/${dst}`;
  mkdirSync(target.substring(0, target.lastIndexOf('/')), { recursive: true });
  cpSync(src, target, { recursive: true });
}
console.log(`Vendor copiado a ${out} (${files.length} entradas)`);

// Fuente de interfaz (Inter Variable) para equipos sin SF Pro.
mkdirSync('static/fonts', { recursive: true });
for (const f of ['inter-latin-wght-normal.woff2', 'inter-latin-ext-wght-normal.woff2']) {
  cpSync(`node_modules/@fontsource-variable/inter/files/${f}`, `static/fonts/${f}`);
}

// Sprite de iconos: Lucide (ISC), solo los que usa el panel, más los propios de assets/icons/propios (misma rejilla
// de 24, trazo 1,75 y currentColor). Uso: <svg><use href="/static/icons.svg#i-NOMBRE"/></svg>
const svgInner = (text) => text.replace(/<!--[\s\S]*?-->/g, '').replace(/^[\s\S]*?<svg[^>]*>/, '').replace(/<\/svg>\s*$/, '').trim().replace(/\s+/g, ' ');
const ICONS = readFileSync('scripts/icons.txt', 'utf8').split('\n').filter(l => !l.startsWith('#')).join(' ').match(/[a-z0-9-]+/g) || [];
const symbols = [];
const missing = [];
for (const name of [...new Set(ICONS)]) {
  const file = `node_modules/lucide-static/icons/${name}.svg`;
  if (!existsSync(file)) { missing.push(name); continue; }
  symbols.push(`<symbol id="i-${name}" viewBox="0 0 24 24">${svgInner(readFileSync(file, 'utf8'))}</symbol>`);
}
const own = readdirSync('assets/icons/propios').filter((f) => f.endsWith('.svg')).sort();
for (const f of own) {
  const name = f.slice(0, -4);
  if (ICONS.includes(name)) { console.error(`El icono propio «${name}» tapa uno de Lucide`); process.exitCode = 1; }
  symbols.push(`<symbol id="i-${name}" viewBox="0 0 24 24">${svgInner(readFileSync(`assets/icons/propios/${f}`, 'utf8'))}</symbol>`);
}
writeFileSync('static/icons.svg',
  '<svg xmlns="http://www.w3.org/2000/svg" style="display:none" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">\n' +
  symbols.join('\n') + '\n</svg>\n');
if (missing.length) { console.error('Iconos inexistentes en Lucide: ' + missing.join(', ')); process.exitCode = 1; }
console.log(`Sprite: ${symbols.length} iconos en static/icons.svg (${own.length} propios)`);

// Ilustraciones de los estados (vacío, hecho, sin resultados, error, sin conexión): rejilla de 120×96, trazo 2,
// currentColor + --ill-accent. Uso: <svg class="ill"><use href="/static/ilustraciones.svg#ill-NOMBRE"/></svg>
const ills = readdirSync('assets/ilustraciones').filter((f) => f.endsWith('.svg')).sort();
writeFileSync('static/ilustraciones.svg',
  '<svg xmlns="http://www.w3.org/2000/svg" style="display:none">\n' +
  ills.map((f) => `<symbol id="ill-${f.slice(0, -4)}" viewBox="0 0 120 96"><g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${svgInner(readFileSync(`assets/ilustraciones/${f}`, 'utf8'))}</g></symbol>`).join('\n') +
  '\n</svg>\n');
console.log(`Ilustraciones: ${ills.length} en static/ilustraciones.svg`);
