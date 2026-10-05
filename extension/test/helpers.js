// Boots the extension libs inside jsdom so they can be tested without a browser.
const { JSDOM } = require('jsdom');

function boot(html) {
  const dom = new JSDOM(html, { pretendToBeVisual: true, url: 'https://example.com/' });
  const w = dom.window;
  for (const k of ['HTMLInputElement', 'HTMLTextAreaElement', 'HTMLSelectElement', 'Event', 'File', 'CSS', 'document']) globalThis[k] = w[k];
  globalThis.window = w;
  globalThis.getComputedStyle = w.getComputedStyle.bind(w);
  // jsdom has no DataTransfer and a read-only input.files: provide the minimum the libs need.
  globalThis.DataTransfer = class { constructor() { this._f = []; this.items = { add: (f) => this._f.push(f) }; } get files() { return this._f; } };
  w.document.querySelectorAll('input[type=file]').forEach((i) => Object.defineProperty(i, 'files', { get() { return this._f || []; }, set(v) { this._f = v; }, configurable: true }));
  for (const mod of ['mapper', 'dom', 'form', 'flow']) {
    delete require.cache[require.resolve(`../lib/${mod}.js`)];
    require(`../lib/${mod}.js`);
  }
  return { dom, document: w.document, JP: globalThis.JP };
}

module.exports = { boot };
