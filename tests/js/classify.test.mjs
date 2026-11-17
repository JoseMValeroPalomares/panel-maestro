// T-2: clasificación de enlaces del Baúl en la extensión (EXTENSION PANEL/lib/classify.js), sin navegador.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { cargar } from './cargar.mjs';

const { Classify } = cargar('EXTENSION PANEL/lib/classify.js');
const ID = 'dQw4w9WgXcQ';

test('youtubeId reconoce todas las formas de un vídeo', () => {
  for (const url of [
    `https://www.youtube.com/watch?v=${ID}`,
    `https://youtube.com/watch?v=${ID}&list=PL123&t=42s`,
    `https://m.youtube.com/watch/?v=${ID}`,
    `https://youtu.be/${ID}?si=abc`,
    `https://www.youtube.com/shorts/${ID}`,
    `https://www.youtube.com/live/${ID}/`,
    `https://www.youtube-nocookie.com/embed/${ID}`,
    `https://music.youtube.com/watch?v=${ID}`,
    `  https://www.youtube.com/watch?v=${ID}  `,
  ]) assert.equal(Classify.youtubeId(url), ID, url);
});

test('youtubeId rechaza lo que no es un vídeo', () => {
  for (const url of [
    'https://www.youtube.com/',
    'https://www.youtube.com/@canal',
    'https://www.youtube.com/watch?v=corto',
    `https://evil.example/watch?v=${ID}`,
    `https://youtube.com.evil.example/watch?v=${ID}`,
    'no es una url',
    '',
    null,
  ]) assert.equal(Classify.youtubeId(url), null, String(url));
});

test('isChannel: @usuario, channel, c y user; un vídeo no lo es', () => {
  for (const p of ['/@MiCanal', '/@MiCanal/videos', '/channel/UC123', '/c/algo', '/user/alguien']) {
    assert.equal(Classify.isChannel(`https://www.youtube.com${p}`), true, p);
  }
  assert.equal(Classify.isChannel(`https://www.youtube.com/watch?v=${ID}`), false);
  assert.equal(Classify.isChannel('https://example.com/@MiCanal'), false);
});

test('detect: web normal, canal, vídeo visto, nuevo y sin conexión', () => {
  const v = `https://youtu.be/${ID}`;
  assert.equal(Classify.detect({ url: 'https://example.com/articulo' }).state, 'normal');
  assert.equal(Classify.detect({ url: 'https://www.youtube.com/@canal' }).state, 'channel');

  const ya = Classify.detect({ url: v, exists: true });
  assert.deepEqual([ya.state, ya.save, ya.certain], ['seen', 'seen', true]);

  const nuevo = Classify.detect({ url: v, exists: false });
  assert.deepEqual([nuevo.state, nuevo.save, nuevo.certain], ['later', 'later', true]);

  const sinRed = Classify.detect({ url: v, exists: null });
  assert.deepEqual([sinRed.state, sinRed.certain], ['later', false]);  // se puede cambiar con un clic

  const raro = Classify.detect({ url: 'https://www.youtube.com/feed/history' });
  assert.deepEqual([raro.state, raro.certain], ['later', false]);
});

test('detect: el umbral de lo visto, con tope de 10 minutos y sin contar vídeos de menos de 30 s', () => {
  const url = `https://youtu.be/${ID}`;
  assert.equal(Classify.detect({ url, exists: false, duration: 600, played: 299, threshold: 50 }).state, 'later');
  const mitad = Classify.detect({ url, exists: false, duration: 600, played: 300, threshold: 50 });
  assert.equal(mitad.state, 'seen');
  assert.match(mitad.reason, /50 %/);
  // Un vídeo de 2 h: con 10 minutos vistos ya cuenta como visto aunque no llegue al 50 %
  assert.equal(Classify.detect({ url, exists: false, duration: 7200, played: 600, threshold: 50 }).state, 'seen');
  // Muy corto: no se juzga por lo reproducido
  assert.equal(Classify.detect({ url, exists: false, duration: 20, played: 20 }).state, 'later');
});
