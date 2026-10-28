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
      expect(await languages.json()).to.be.an('array');
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
});
