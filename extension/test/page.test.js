const test = require('node:test');
const assert = require('node:assert');
const { boot } = require('./helpers');

test('scrapeJob reads schema.org JobPosting JSON-LD', () => {
  const html = `<html><head><script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"WebSite"},
    {"@type":"JobPosting","title":"Data Engineer","hiringOrganization":{"name":"Example Co"},
     "jobLocation":{"address":{"addressLocality":"Plano","addressRegion":"TX"}},"description":"&lt;p&gt;Build ETL in Python and SQL.&lt;/p&gt;"}]}</script></head><body><h1>Ignored</h1></body></html>`;
  const { document, JP } = boot(html);
  require('../lib/page.js');
  const j = globalThis.JP.page.scrapeJob(document);
  assert.deepEqual([j.title, j.company, j.location], ['Data Engineer', 'Example Co', 'Plano, TX']);
  assert.match(j.description, /Build ETL in Python and SQL/);
});

test('scrapeJob falls back to h1 + main text', () => {
  const { document } = boot('<html><head><title>x</title></head><body><h1>Backend Engineer</h1><main>We use Go and Kafka.</main></body></html>');
  require('../lib/page.js');
  const j = globalThis.JP.page.scrapeJob(document);
  assert.equal(j.title, 'Backend Engineer');
  assert.match(j.description, /Go and Kafka/);
});
