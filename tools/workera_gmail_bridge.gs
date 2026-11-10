/**
 * Reloj de Jornada — Puente Gmail ↔ app (Google Apps Script).
 *
 * Corre DENTRO de tu cuenta de Google: lee tus correos de Workera (solo lectura), programa el aviso
 * de salida en ntfy aunque la app esté cerrada y guarda un respaldo de tus datos. Nadie más que tú
 * (y quien tenga tu URL + clave) puede consultarlo.
 *
 * Instalación (detalle en GUIA_AMIGOS.md):
 *   1. Copia este proyecto en https://script.google.com (o abre el enlace «Hacer una copia»).
 *   2. Ejecuta la función `setup` y acepta los permisos (Google avisará que la app no está verificada:
 *      es normal, el script es tuyo → Configuración avanzada → Ir a … (no seguro)).
 *   3. Implementar → Nueva implementación → Aplicación web · Ejecutar como: Yo · Acceso: Cualquier usuario.
 *   4. Pega en Reloj de Jornada (Ajustes → Conexión con Workera → Puente Google) la URL de la
 *      implementación y la clave que muestra el registro de `setup`.
 *
 * La lógica de interpretación (doble Entrada/Salida, alertas) vive en la app; aquí solo se extraen
 * los correos y se hace un cálculo simple de la salida para el aviso en segundo plano.
 */

var VERSION = '1.0';
var CONSULTA_WORKERA = 'from:workera.com';
var CONSULTA_MARCAS = 'from:workera.com subject:(registros asistencia)';
var MAX_CORREOS = 400;
var TAM_TROZO = 8000;            // límite por propiedad: 9 KB
var MAX_RESPALDO = 400000;       // límite total de propiedades: 500 KB
var DEBOUNCE_S = 15 * 60;
var MIN_SEPARACION_S = 2 * 3600;
var CORTE_MANANA_S = 13 * 3600;

// =============================================================================== funciones puras
// (sin servicios de Google: se prueban con node, ver tools/bridge.test.js)

var ENTIDADES_ = {
  '&nbsp;': ' ', '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'",
  '&aacute;': 'á', '&eacute;': 'é', '&iacute;': 'í', '&oacute;': 'ó', '&uacute;': 'ú',
  '&Aacute;': 'Á', '&Eacute;': 'É', '&Iacute;': 'Í', '&Oacute;': 'Ó', '&Uacute;': 'Ú',
  '&ntilde;': 'ñ', '&Ntilde;': 'Ñ', '&deg;': '°'
};

function textoPlano_(html) {
  var t = String(html || '')
    .replace(/<(style|script|head)[\s\S]*?<\/\1>/gi, ' ')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/(td|th|tr|p|div|li|h\d|table)>/gi, '\n')
    .replace(/<[^>]+>/g, ' ');
  t = t.replace(/&[a-zA-Z]+;|&#\d+;/g, function (e) {
    if (ENTIDADES_[e] !== undefined) return ENTIDADES_[e];
    var m = /^&#(\d+);$/.exec(e);
    return m ? String.fromCharCode(Number(m[1])) : e;
  });
  return t.replace(/[ \t ]+/g, ' ').replace(/\s*\n\s*/g, '\n').trim();
}

/** Extrae {fecha:'AAAA-MM-DD', segundos, tipo, activa} de un correo «Nuevos registros de asistencia». */
function extraerMarca_(texto) {
  var t = String(texto || '').replace(/\s+/g, ' ');
  var f = /Fecha registro\s*:?\s*(\d{1,2})\/(\d{1,2})\/(\d{4})/i.exec(t);
  var h = /Hora registro\s*:?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?/i.exec(t);
  if (!f || !h) return null;
  var tipo = /Tipo de marcaci[oó]n\s*:?\s*(Entrada|Salida)/i.exec(t);
  var estado = /Estado registro\s*:?\s*(\w+)/i.exec(t);
  var pad = function (n) { return ('0' + n).slice(-2); };
  return {
    fecha: f[3] + '-' + pad(f[2]) + '-' + pad(f[1]),
    segundos: Number(h[1]) * 3600 + Number(h[2]) * 60 + Number(h[3] || 0),
    tipo: tipo ? tipo[1].charAt(0).toUpperCase() + tipo[1].slice(1).toLowerCase() : '',
    activa: !estado || estado[1].toLowerCase() === 'activo'
  };
}

/** Día de la semana con lunes = 0 (como Python). */
function diaSemana_(fecha) {
  return (new Date(fecha + 'T12:00:00Z').getUTCDay() + 6) % 7;
}

/**
 * Decide el aviso del día a partir de las marcas (segundos desde medianoche):
 *   null                 → nada que hacer (día libre, sin marcas o marca única de tarde, ambigua)
 *   {cancelar: true}     → ya hay salida (dos marcas separadas ≥ 2 h)
 *   {salida_s: n}        → salida estimada = primera marca + jornada + colación
 */
function salidaEstimada_(segundos, fecha, cfg) {
  if ((cfg.dias || [0, 1, 2, 3, 4]).indexOf(diaSemana_(fecha)) < 0) return null;
  var orden = segundos.slice().sort(function (a, b) { return a - b; });
  var validas = [];
  orden.forEach(function (s) {
    if (!validas.length || s - validas[validas.length - 1] >= DEBOUNCE_S) validas.push(s);
  });
  if (!validas.length) return null;
  if (validas.length >= 2 && validas[validas.length - 1] - validas[0] >= MIN_SEPARACION_S) {
    return { cancelar: true };
  }
  if (validas[0] >= CORTE_MANANA_S) return null;
  return { salida_s: validas[0] + Number(cfg.jornada_s || 28800) + Number(cfg.colacion_s || 3600) };
}

function trozos_(texto, tam) {
  var out = [];
  for (var i = 0; i < texto.length; i += tam) out.push(texto.slice(i, i + tam));
  return out;
}

function hhmmss_(s) {
  var pad = function (n) { return ('0' + n).slice(-2); };
  s = ((s % 86400) + 86400) % 86400;
  return pad(Math.floor(s / 3600)) + ':' + pad(Math.floor(s / 60) % 60) + ':' + pad(s % 60);
}

// =============================================================================== instalación
function setup() {
  var props = PropertiesService.getScriptProperties();
  if (!props.getProperty('TOKEN')) {
    props.setProperty('TOKEN', Utilities.getUuid().replace(/-/g, '') + Utilities.getUuid().replace(/-/g, '').slice(0, 8));
  }
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'revisar') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('revisar').timeBased().everyMinutes(10).create();
  var n = Gmail.Users.Messages.list('me', { q: CONSULTA_WORKERA + ' newer_than:30d', maxResults: 100 }).messages;
  Logger.log('✓ Puente listo. Correos de Workera en los últimos 30 días: ' + (n ? n.length : 0));
  Logger.log('CLAVE para la app (no la compartas): ' + props.getProperty('TOKEN'));
  Logger.log('Ahora: Implementar → Nueva implementación → Aplicación web (Ejecutar como: Yo · Acceso: Cualquier usuario) y copia la URL.');
}

/** Genera una clave nueva (la anterior deja de funcionar). */
function cambiarClave() {
  PropertiesService.getScriptProperties().deleteProperty('TOKEN');
  setup();
}

// =============================================================================== web app
function doGet(e) { return responder_(manejar_(e, null)); }
function doPost(e) { return responder_(manejar_(e, e && e.postData ? e.postData.contents : '')); }

function responder_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function manejar_(e, cuerpo) {
  var p = (e && e.parameter) || {};
  var props = PropertiesService.getScriptProperties();
  var token = props.getProperty('TOKEN');
  if (!token || p.token !== token) return { ok: false, error: 'Clave inválida' };
  try {
    switch (p.accion || 'ping') {
      case 'ping':
        return { ok: true, version: VERSION, zona: Session.getScriptTimeZone(),
                 respaldo_fecha: props.getProperty('RESPALDO_FECHA') || null };
      case 'correos':
        return { ok: true, correos: listarCorreos_(Number(p.desde || 0), Number(p.dias || 45)) };
      case 'config':
        guardarConfig_(p);
        return { ok: true };
      case 'salida':
        props.setProperty('APP_SALIDA_' + p.fecha, String(p.salida_s || ''));
        limpiarViejas_();
        return { ok: true };
      case 'respaldo_subir':
        guardarRespaldo_(cuerpo || '');
        return { ok: true, fecha: props.getProperty('RESPALDO_FECHA') };
      case 'respaldo_bajar':
        return { ok: true, datos: leerRespaldo_(), fecha: props.getProperty('RESPALDO_FECHA') || null };
      default:
        return { ok: false, error: 'Acción desconocida' };
    }
  } catch (err) {
    return { ok: false, error: String(err && err.message || err) };
  }
}

// =============================================================================== correos
function listarCorreos_(desde, dias) {
  var q = CONSULTA_WORKERA + (desde > 0 ? ' after:' + Math.floor(desde) : ' newer_than:' + dias + 'd');
  var ids = [];
  var pagina;
  do {
    var r = Gmail.Users.Messages.list('me', { q: q, maxResults: 100, pageToken: pagina });
    (r.messages || []).forEach(function (m) { ids.push(m.id); });
    pagina = r.nextPageToken;
  } while (pagina && ids.length < MAX_CORREOS);
  return ids.map(function (id) {
    var m = Gmail.Users.Messages.get('me', id, { format: 'raw' });
    var raw = typeof m.raw === 'string' ? m.raw : Utilities.base64EncodeWebSafe(m.raw);
    return { id: id, fecha: Number(m.internalDate), raw: raw };
  });
}

function cuerpoHtml_(parte) {
  if (!parte) return '';
  if (parte.body && parte.body.data && /^text\/(html|plain)/.test(parte.mimeType || '')) {
    var datos = parte.body.data;
    var bytes = typeof datos === 'string' ? Utilities.base64DecodeWebSafe(datos) : datos;
    return Utilities.newBlob(bytes).getDataAsString('UTF-8');
  }
  var partes = parte.parts || [];
  for (var i = 0; i < partes.length; i++) {
    if (partes[i].mimeType === 'text/html') return cuerpoHtml_(partes[i]);
  }
  for (var j = 0; j < partes.length; j++) {
    var t = cuerpoHtml_(partes[j]);
    if (t) return t;
  }
  return '';
}

// =============================================================================== aviso en segundo plano
function config_() {
  var c = PropertiesService.getScriptProperties().getProperty('CONFIG');
  return c ? JSON.parse(c) : { activo: false };
}

function guardarConfig_(p) {
  var cfg = {
    activo: p.activo === '1',
    canal: String(p.canal || '').replace(/[^A-Za-z0-9_-]/g, '').slice(0, 64),
    servidor: /^https:\/\//.test(p.servidor || '') ? p.servidor.replace(/\/+$/, '') : 'https://ntfy.sh',
    jornada_s: Number(p.jornada_s || 28800),
    colacion_s: Number(p.colacion_s || 3600),
    aviso_min: Number(p.aviso_min || 5),
    dias: String(p.dias || '0,1,2,3,4').split(',').map(Number)
  };
  var props = PropertiesService.getScriptProperties();
  props.setProperty('CONFIG', JSON.stringify(cfg));
  props.deleteProperty('PROGRAMADO');
}

/** Disparador cada 10 min: programa el aviso de salida de hoy si la app no lo hizo. */
function revisar() {
  var cfg = config_();
  if (!cfg.activo || !cfg.canal) return;
  var props = PropertiesService.getScriptProperties();
  var tz = Session.getScriptTimeZone();
  var hoy = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');
  if (props.getProperty('APP_SALIDA_' + hoy) !== null) return;   // la app ya programó con el plan real

  var lista = Gmail.Users.Messages.list('me', { q: CONSULTA_MARCAS + ' newer_than:2d', maxResults: 30 }).messages || [];
  var segundos = [];
  lista.forEach(function (m) {
    var msg = Gmail.Users.Messages.get('me', m.id, { format: 'full' });
    var marca = extraerMarca_(textoPlano_(cuerpoHtml_(msg.payload)));
    if (marca && marca.activa && marca.fecha === hoy) segundos.push(marca.segundos);
  });
  var accion = salidaEstimada_(segundos, hoy, cfg);
  var clave = hoy + '|' + JSON.stringify(accion) + '|' + cfg.canal + '|' + cfg.aviso_min;
  if (!accion || clave === props.getProperty('PROGRAMADO')) return;

  var url = cfg.servidor + '/' + cfg.canal + '/salida-' + hoy.replace(/-/g, '');
  if (accion.cancelar) {
    UrlFetchApp.fetch(url, { method: 'delete', muteHttpExceptions: true });
  } else {
    var aviso = accion.salida_s - cfg.aviso_min * 60;
    var cuando = Utilities.parseDate(hoy + ' ' + hhmmss_(aviso), tz, 'yyyy-MM-dd HH:mm:ss').getTime() / 1000;
    if (cuando - Date.now() / 1000 < 10) return;
    UrlFetchApp.fetch(url, {
      method: 'post', muteHttpExceptions: true,
      headers: { At: String(Math.floor(cuando)), Title: 'Reloj de Jornada', Priority: 'high', Tags: 'alarm_clock' },
      payload: 'Tu salida es a las ' + hhmmss_(accion.salida_s).slice(0, 5) + ' (en ' + cfg.aviso_min +
               ' min). Jornada normal; abre la app si cambiaste el plan.'
    });
  }
  props.setProperty('PROGRAMADO', clave);
}

function limpiarViejas_() {
  var props = PropertiesService.getScriptProperties();
  var limite = Utilities.formatDate(new Date(Date.now() - 7 * 86400000), Session.getScriptTimeZone(), 'yyyy-MM-dd');
  Object.keys(props.getProperties()).forEach(function (k) {
    if (k.indexOf('APP_SALIDA_') === 0 && k.slice(11) < limite) props.deleteProperty(k);
  });
}

// =============================================================================== respaldo
function guardarRespaldo_(texto) {
  if (texto.length > MAX_RESPALDO) throw new Error('Respaldo demasiado grande (' + texto.length + ' bytes)');
  var props = PropertiesService.getScriptProperties();
  var anteriores = Number(props.getProperty('RESPALDO_N') || 0);
  var partes = trozos_(texto, TAM_TROZO);
  var nuevos = {};
  partes.forEach(function (p, i) { nuevos['RESPALDO_' + i] = p; });
  nuevos.RESPALDO_N = String(partes.length);
  nuevos.RESPALDO_FECHA = new Date().toISOString();
  props.setProperties(nuevos);
  for (var i = partes.length; i < anteriores; i++) props.deleteProperty('RESPALDO_' + i);
}

function leerRespaldo_() {
  var props = PropertiesService.getScriptProperties();
  var n = Number(props.getProperty('RESPALDO_N') || 0);
  var out = '';
  for (var i = 0; i < n; i++) out += props.getProperty('RESPALDO_' + i) || '';
  return out || null;
}

// Para probar las funciones puras con node (en Apps Script `module` no existe).
if (typeof module !== 'undefined') {
  module.exports = { textoPlano_: textoPlano_, extraerMarca_: extraerMarca_, salidaEstimada_: salidaEstimada_,
                     diaSemana_: diaSemana_, trozos_: trozos_, hhmmss_: hhmmss_ };
}
