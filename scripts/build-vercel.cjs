// Export the same dashboard served by FastAPI; no collector or database runs on Vercel.
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'crypig/dashboard/page.py'), 'utf8');
const match = source.match(/INDEX_HTML = r"""([\s\S]*?)"""/);
if (!match || !match[1].startsWith('<!doctype html>') || !match[1].includes('function setLTHRange')) {
  throw new Error('Dashboard export failed: expected HTML and LTH controls');
}
// A dedicated backend origin avoids a proxy loop when hypeboss.cc points to Vercel.
const backendOrigin = 'https://api.hypeboss.cc';
const output = path.join(root, '.vercel/output');
fs.mkdirSync(path.join(output, 'static'), {recursive: true});
fs.writeFileSync(path.join(output, 'static/index.html'), match[1]);
fs.cpSync(path.join(root, 'crypig/dashboard/static'), path.join(output, 'static/static'), {recursive: true});
fs.copyFileSync(path.join(root, 'crypig/dashboard/robots.txt'), path.join(output, 'static/robots.txt'));
fs.copyFileSync(path.join(root, 'crypig/dashboard/sitemap.xml'), path.join(output, 'static/sitemap.xml'));
fs.writeFileSync(path.join(output, 'config.json'), JSON.stringify({
  version: 3,
  routes: [
    {src: '/', dest: '/index.html'},
    {handle: 'filesystem'},
    {src: '/(.*)', dest: backendOrigin + '/$1', headers: {'Cache-Control': 'no-store'}}
  ]
}, null, 2) + '\n');
console.log('Exported Crypig dashboard; data routes use the existing production origin.');
