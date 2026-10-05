const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const root = path.resolve(__dirname, '..');
process.chdir(root);
const fa = 'node_modules/@fortawesome/fontawesome-free';
const fonts = 'node_modules/@fontsource/poppins';
fs.mkdirSync('static/vendor/fontawesome/css', { recursive: true });
fs.copyFileSync(`${fa}/css/all.min.css`, 'static/vendor/fontawesome/css/all.min.css');
fs.cpSync(`${fa}/webfonts`, 'static/vendor/fontawesome/webfonts', { recursive: true });
fs.copyFileSync(`${fa}/LICENSE.txt`, 'static/vendor/fontawesome/LICENSE.txt');
fs.mkdirSync('static/vendor/poppins/files', { recursive: true });
let css = '';
for (const weight of [400, 500, 600, 700, 800]) {
  const file = `poppins-latin-${weight}-normal.woff2`;
  fs.copyFileSync(`${fonts}/files/${file}`, `static/vendor/poppins/files/${file}`);
  css += `@font-face{font-family:'Poppins';font-style:normal;font-weight:${weight};font-display:swap;src:url('./files/${file}') format('woff2');}\n`;
}
fs.writeFileSync('static/vendor/poppins/poppins.css', css);
fs.copyFileSync(`${fonts}/LICENSE`, 'static/vendor/poppins/LICENSE');
const manifest = {};
function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(file);
    else if (/\.(css|js)$/.test(file)) {
      // Git usa LF para estos archivos en todas las plataformas (.gitattributes).
      fs.writeFileSync(file, fs.readFileSync(file, 'utf8').replace(/\r\n/g, '\n'));
      manifest[path.relative('static', file).split(path.sep).join('/')] =
        'sha384-' + crypto.createHash('sha384').update(fs.readFileSync(file)).digest('base64');
    }
  }
}
walk('static');
fs.writeFileSync('static/asset-integrity.json', JSON.stringify(manifest, null, 2) + '\n');
