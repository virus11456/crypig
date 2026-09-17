const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const root = path.resolve(__dirname, '..');
test('frontend exports locally and API rewrites cannot loop through frontend domains', () => {
  execFileSync(process.execPath, [path.join(root, 'scripts/build-vercel.cjs')]);
  const config = JSON.parse(fs.readFileSync(path.join(root, '.vercel/output/config.json')));
  assert.equal(config.routes[0].dest, '/index.html');
  assert.equal(config.routes[1].handle, 'filesystem');
  const proxy = config.routes.find(r => r.src === '/(.*)');
  assert.equal(new URL(proxy.dest).origin, 'https://api.hypeboss.cc');
  for (const pathname of ['account_replay', 'data_status', 'account_history?address=0x123', 'vault.zip']) {
    const target = new URL(proxy.dest.replace('$1', pathname));
    assert.equal(target.protocol, 'https:');
    assert(!['hypeboss.cc', 'www.hypeboss.cc', 'hypeboss.vercel.app'].includes(target.hostname));
    assert.equal(target.pathname + target.search, '/' + pathname);
  }
  assert.equal(proxy.headers['Cache-Control'], 'no-store');
});
