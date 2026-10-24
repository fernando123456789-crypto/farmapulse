// Localizo el código de la app fuera de esta carpeta de pruebas.
const fs = require('node:fs');
const path = require('node:path');

let root = process.env.FARMAPULSE_APP_ROOT;
const configuration = path.join(__dirname, '../.env.pruebas');
if (!root && fs.existsSync(configuration)) {
  for (const line of fs.readFileSync(configuration, 'utf8').split(/\r?\n/)) {
    const match = line.match(/^\s*FARMAPULSE_APP_ROOT\s*=(.*)$/);
    if (match) { root = match[1].trim().replace(/^(['"])(.*)\1$/, '$2'); break; }
  }
}
if (!root) throw new Error('Configuro FARMAPULSE_APP_ROOT con la ruta de una copia separada de FarmaPulse.');
root = path.resolve(root);
if (!fs.existsSync(path.join(root, 'static/js/main.js'))) {
  throw new Error('Selecciono la raíz de la aplicación FarmaPulse en FARMAPULSE_APP_ROOT.');
}
module.exports = relative => path.join(root, relative);
