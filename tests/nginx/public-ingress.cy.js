// Opt-in against the actual HTTPS deployment, not the fixture API. No cy.intercept.
// Copy into the UI Cypress directory and select this spec explicitly (see SNI-44).
describe('SNI-44 / deployed ingress', () => {
  const environment = Cypress.env('environment');
  const host = `https://jjt-snippets-${environment}.duckdns.org`;

  it('serves UI and SPA navigation with same-origin API and readable errors', () => {
    expect(environment).to.be.oneOf(['dev', 'prod']);
    cy.visit(host + '/rules');
    cy.reload();
    cy.window().then(async win => {
      expect(win.location.origin).to.eq(host);
      const config = await (await win.fetch('/app-config.json')).json();
      expect(config.environment).to.eq(environment);
      const languages = await win.fetch('/api/languages');
      expect(languages.status).to.eq(200);
      const catalog = await languages.json();
      expect(catalog).to.be.an('array');
      // Missing identity is an application error, never an HTML fallback or CORS failure.
      const denied = await win.fetch('/api/snippets?page=0&page_size=10');
      expect(denied.status).to.eq(401);
      expect((await denied.json()).type).to.be.a('string');
      if (environment === 'dev') {
        expect(config.identity.mode).to.eq('dev');
        const invalid = await win.fetch('/api/snippets', {method: 'POST',
          headers: {'Content-Type': 'application/json', 'X-Dev-Actor-Id': config.identity.actorId},
          body: '{}'});
        expect(invalid.status).to.eq(400); // Validation without creating a fake snippet.
        expect((await invalid.json()).type).to.be.a('string');
        const language = catalog.find(item => item.language === 'printscript');
        expect(language, 'real catalog must declare the language under test').to.exist;
        expect(language.versions).to.include('1.1');
        const draft = {name: 'SNI-44 HTTPS ' + Date.now(), description: 'Aceptación TLS de dev',
          language: language.language, version: language.versions.find(value => value === '1.1'), code: 'println(44);\n'};
        const headers = {'Content-Type': 'application/json', 'X-Dev-Actor-Id': config.identity.actorId};
        const created = await win.fetch('/api/snippets', {method: 'POST',
          headers: {...headers, 'Idempotency-Key': win.crypto.randomUUID()}, body: JSON.stringify(draft)});
        expect(created.status).to.eq(201);
        const {id} = await created.json();
        expect(id).to.be.a('string');
        const path = '/api/snippets/' + encodeURIComponent(id);
        const updated = await win.fetch(path, {method: 'PUT', headers,
          body: JSON.stringify({...draft, code: 'println(45);\n'})});
        expect(updated.status).to.eq(200);
        const detail = await win.fetch(path, {headers});
        expect(detail.status).to.eq(200);
        expect((await detail.json()).code).to.eq('println(45);\n');
      } else {
        expect(config.identity).to.deep.eq({mode: 'disabled'});
        const spoof = await win.fetch('/api/snippets?page=0&page_size=10',
          {headers: {'X-Dev-Actor-Id': 'dev-juanfran'}});
        expect(spoof.status).to.eq(401);
      }
      const resources = win.performance.getEntriesByType('resource');
      expect(resources.filter(entry => entry.name.startsWith('http://')), 'no mixed HTTP resources').to.have.length(0);
    });
  });

  it('blocks an unlisted browser origin while the same public API is reachable', () => {
    // This control distinguishes browser CORS enforcement from a firewall/DNS outage.
    cy.request(host + '/api/languages').its('status').should('eq', 200);
    cy.visit('http://127.0.0.1:5184/');
    cy.window().then(async win => {
      let blocked = false;
      try {
        await win.fetch(host + '/api/languages');
      } catch (error) {
        blocked = true;
        expect(error.name).to.eq('TypeError');
      }
      expect(blocked, 'browser refuses to expose the cross-origin response').to.eq(true);
    });
  });
});
