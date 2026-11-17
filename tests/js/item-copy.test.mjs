// T-2: formato al copiar varias tareas (static/js/item-copy.js, ItemCopy.format), sin navegador.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { cargar } from './cargar.mjs';

const { ItemCopy } = cargar('static/js/item-copy.js');

const ENTRADAS = [
  {
    text: 'Preparar el examen\nrepasar temas 3 y 4', done: false, details: 'Lunes en la biblioteca',
    children: [{ text: 'Hacer resúmenes', done: true }, { text: 'Ejercicios', done: false, details: 'Hoja 2\nHoja 3' }],
  },
  { text: 'Llamar al banco', done: true },
];

test('Markdown: casillas, sangría de dos espacios por nivel y segunda línea bajo la tarea', () => {
  assert.equal(ItemCopy.format(ENTRADAS), [
    '- [ ] Preparar el examen',
    '  repasar temas 3 y 4',
    '  - [x] Hacer resúmenes',
    '  - [ ] Ejercicios',
    '- [x] Llamar al banco',
  ].join('\n'));
});

test('Markdown con notas: van citadas bajo su tarea, línea a línea', () => {
  const md = ItemCopy.format(ENTRADAS, { notes: true }).split('\n');
  assert.ok(md.includes('  > Lunes en la biblioteca'));
  assert.ok(md.includes('    > Hoja 2') && md.includes('    > Hoja 3'));
});

test('Texto plano: una línea por tarea, pasos con guion y «(hecha)»', () => {
  assert.equal(ItemCopy.format(ENTRADAS, { format: 'text' }), [
    'Preparar el examen',
    '  repasar temas 3 y 4',
    '  - Hacer resúmenes (hecha)',
    '  - Ejercicios',
    'Llamar al banco (hecha)',
  ].join('\n'));
});

test('Casos límite: lista vacía, texto vacío y líneas en blanco que no se copian', () => {
  assert.equal(ItemCopy.format([]), '');
  assert.equal(ItemCopy.format([{ text: '', done: false }]), '- [ ] ');
  assert.equal(ItemCopy.format([{ text: 'Uno\n\n   \nDos', done: false }]), '- [ ] Uno\n  Dos');
});
