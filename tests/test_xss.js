const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/main.js', 'utf8');
const escapeSource = source.match(/function escaparHtml\(texto\) \{[\s\S]*?\n  \}/)[0];
const buttonSource = source.slice(source.indexOf('function botonCarritoHtml(item)'), source.indexOf('  function renderizarResultados'));
const context = { estaEnCarrito: () => false };
vm.createContext(context);
vm.runInContext(escapeSource + '\n' + buttonSource, context);
for (const payload of ['<script>alert(1)</script>', '"><img src=x onerror=alert(1)>', "' autofocus onfocus='alert(1)", '&quot;<svg/onload=alert(1)>']) {
  const escaped = context.escaparHtml(payload);
  assert.ok(!/[<>"']/.test(escaped), 'El contenido no puede salir de texto ni de atributos entre comillas');
  const item = Object.fromEntries(['medicamento', 'dci', 'farmacia', 'distrito', 'presentacion', 'precio_unitario', 'precio_empaque', 'tipo', 'cotizacion'].map(key => [key, payload]));
  const html = context.botonCarritoHtml(item);
  assert.ok(!html.includes(payload), 'Ningún campo se interpola sin escape en el botón del carrito');
  assert.ok(!html.includes('<script>') && !html.includes('<img') && !html.includes('<svg'));
}
console.log('OK: escapo texto y atributos del carrito, incluidos precios, tipo y cotización.');
