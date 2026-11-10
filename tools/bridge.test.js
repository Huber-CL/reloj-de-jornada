// Pruebas de las funciones puras del puente Apps Script. Uso: node tools/bridge.test.js <muestras.json>
// (lo ejecuta tests/test_bridge_gs.py con HTML generado por los fixtures de Python).
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const codigo = fs.readFileSync(path.join(__dirname, 'workera_gmail_bridge.gs'), 'utf8');
const ctx = { module: { exports: {} } };
vm.createContext(ctx);
vm.runInContext(codigo, ctx);
const g = ctx.module.exports;
const muestras = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));

// Correo A real (tablas HTML con entidades).
const m = g.extraerMarca_(g.textoPlano_(muestras.marcacion));
assert.deepStrictEqual(JSON.parse(JSON.stringify(m)),
  { fecha: '2026-11-09', segundos: 5 * 3600 + 52 * 60 + 47, tipo: 'Entrada', activa: true });

// Versión texto plano y marca anulada.
assert.strictEqual(g.extraerMarca_(muestras.plano).segundos, 7 * 3600);
assert.strictEqual(g.extraerMarca_(g.textoPlano_(muestras.anulada)).activa, false);
assert.strictEqual(g.extraerMarca_('Hola'), null);

const cfg = { jornada_s: 28800, colacion_s: 3600, dias: [0, 1, 2, 3, 4] };
// Lunes 09/11: ingreso 05:52:47 → salida 14:52:47
assert.strictEqual(g.salidaEstimada_([21167], '2026-11-09', cfg).salida_s, 21167 + 32400);
// Rebote a 5 min no cambia la primera marca
assert.strictEqual(g.salidaEstimada_([25210, 25500], '2026-11-09', cfg).salida_s, 25210 + 32400);
// Doble Entrada 07:00:10 + 17:43:15 → ya hay salida → cancelar
assert.deepStrictEqual(JSON.parse(JSON.stringify(g.salidaEstimada_([63795, 25210], '2026-11-06', cfg))), { cancelar: true });
// Marca única de tarde: ambigua → nada
assert.strictEqual(g.salidaEstimada_([63795], '2026-11-06', cfg), null);
// Sábado (día libre) → nada
assert.strictEqual(g.salidaEstimada_([25200], '2026-11-07', cfg), null);
assert.strictEqual(g.diaSemana_('2026-11-09'), 0);

// Respaldo en trozos
const largo = 'x'.repeat(20001);
assert.deepStrictEqual(Array.from(g.trozos_(largo, 8000), t => t.length), [8000, 8000, 4001]);
assert.strictEqual(g.trozos_(largo, 8000).join(''), largo);
assert.strictEqual(g.hhmmss_(63780), '17:43:00');
assert.strictEqual(g.hhmmss_(-60), '23:59:00');

console.log('OK puente Apps Script');
