// Copia las librerías de node_modules a static/vendor (servidas por el propio panel:
// sin CDNs, funciona offline como PWA y permite una CSP estricta).
import { cpSync, mkdirSync, rmSync, readFileSync, writeFileSync, existsSync } from 'node:fs';

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
  ['node_modules/fabric/dist/fabric.min.js', 'fabric/fabric.min.js'],
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

// Sprite de iconos Lucide (ISC): solo los que usa el panel. <svg><use href="/static/icons.svg#i-NOMBRE"/></svg>
const ICONS = readFileSync('scripts/icons.txt', 'utf8').split('\n').filter(l => !l.startsWith('#')).join(' ').match(/[a-z0-9-]+/g) || [];
const symbols = [];
const missing = [];
for (const name of [...new Set(ICONS)]) {
  const file = `node_modules/lucide-static/icons/${name}.svg`;
  if (!existsSync(file)) { missing.push(name); continue; }
  const inner = readFileSync(file, 'utf8').replace(/<!--[\s\S]*?-->/g, '').replace(/^[\s\S]*?<svg[^>]*>/, '').replace(/<\/svg>\s*$/, '').trim();
  symbols.push(`<symbol id="i-${name}" viewBox="0 0 24 24">${inner.replace(/\s+/g, ' ')}</symbol>`);
}
writeFileSync('static/icons.svg',
  '<svg xmlns="http://www.w3.org/2000/svg" style="display:none" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">\n' +
  symbols.join('\n') + '\n</svg>\n');
if (missing.length) { console.error('Iconos inexistentes en Lucide: ' + missing.join(', ')); process.exitCode = 1; }
console.log(`Sprite: ${symbols.length} iconos en static/icons.svg`);
