const appPath = require('./app-path');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const source = fs.readFileSync(appPath('static/js/main.js'), 'utf8');
const escapeSource = source.match(/function escaparHtml\(texto\) \{[\s\S]*?\n  \}/)[0];
const buttonSource = source.slice(source.indexOf('function botonCarritoHtml(item)'), source.indexOf('  function renderizarResultados'));
function assertEscaped(payload) {
  const context = { estaEnCarrito: () => false };
  vm.createContext(context);
  vm.runInContext(escapeSource + '\n' + buttonSource, context);
  const escaped = context.escaparHtml(payload);
  assert.ok(!/[<>"']/.test(escaped), 'El contenido no puede salir de texto ni de atributos entre comillas');
  const item = Object.fromEntries(['medicamento', 'dci', 'farmacia', 'distrito', 'presentacion', 'precio_unitario', 'precio_empaque', 'tipo', 'cotizacion'].map(key => [key, payload]));
  const html = context.botonCarritoHtml(item);
  assert.ok(!html.includes(payload), 'Ningún campo se interpola sin escape en el botón del carrito');
  assert.ok(!html.includes('<script>') && !html.includes('<img') && !html.includes('<svg'));
}

test("HTML: escapa etiquetas script en el texto y los atributos del carrito", () => {
  assertEscaped('<script>alert(1)</script>');
});

test("HTML: escapa comillas dobles e imágenes con eventos", () => {
  assertEscaped('"><img src=x onerror=alert(1)>');
});

test("HTML: escapa comillas simples e intentos de insertar atributos", () => {
  assertEscaped("' autofocus onfocus='alert(1)");
});

test("HTML: escapa entidades y etiquetas SVG", () => {
  assertEscaped('&quot;<svg/onload=alert(1)>');
});
