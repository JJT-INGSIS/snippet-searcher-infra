import {login} from '../newrelic/dev-functional/journey';

function record(response, extra = {}) {
  return cy.task('evidence', {
    at: new Date().toISOString(), scenario: Cypress.env('scenario'), status: response.status,
    requestId: response.headers['x-request-id'] || null, ...extra,
  }, {log: false});
}

it('checks a dedicated DEV operation without exporting credentials', () => {
  cy.intercept('GET', '/api/snippets?*').as('listing');
  cy.task('stage', 'AUTH0_LOGIN', {log: false});
  login();
  cy.task('stage', 'LISTING_HTTP', {log: false});
  cy.wait('@listing', {log: false}).then(({request, response}) => {
    expect(response.statusCode).to.equal(200);
    const authorization = request.headers.authorization;
    expect(typeof authorization).to.equal('string');
    const headers = {authorization};
    const scenario = Cypress.env('scenario');
    if (scenario === 'healthy-create' || scenario === 'printscript-unavailable') {
      if (scenario === 'printscript-unavailable') cy.task('awaitPrintscriptCut', null, {timeout: 90_000, log: false});
      const key = crypto.randomUUID();
      cy.request({method: 'POST', url: '/api/snippets', log: false, failOnStatusCode: false,
        retryOnNetworkFailure: false, headers: {...headers, 'Idempotency-Key': key},
        body: {name: `SNI-87 ${scenario} ${key}`, description: 'Fixture dedicado SNI-87',
          language: 'printscript', version: '1.1', code: 'println("SNI-87 OK");'},
      }).then(result => {
        record(result, {snippetId: result.body.id || null, idempotencyKey: key, problemType: result.body.type || null});
        if (scenario === 'healthy-create') expect(result.status).to.equal(201);
        else {
          expect(result.status).to.equal(502);
          expect(result.body.type).to.equal('urn:snippets:problem:dependency-failure');
        }
      });
    } else if (scenario === 'business-rejections') {
      const draft = {name: 'SNI-87 rechazo esperado', language: 'printscript', version: '1.1'};
      const cases = [
        {method: 'POST', url: '/api/snippets', body: {...draft, code: '  '}, status: 400,
          type: 'urn:snippets:problem:invalid-request'},
        {method: 'POST', url: '/api/snippets', body: {...draft, code: 'let a: number = ;'}, status: 422,
          type: 'urn:snippets:problem:invalid-code'},
        {method: 'GET', url: `/api/snippets/${crypto.randomUUID()}`, status: 404,
          type: 'urn:snippets:problem:snippet-not-found'},
      ];
      for (const expected of cases) {
        cy.request({method: expected.method, url: expected.url, body: expected.body,
          headers: {...headers, 'Idempotency-Key': crypto.randomUUID()}, log: false,
          retryOnNetworkFailure: false, failOnStatusCode: false,
        }).then(result => {
          record(result, {problemType: result.body.type || null});
          expect(result.status).to.equal(expected.status);
          expect(result.body.type).to.equal(expected.type);
        });
      }
    } else if (scenario === 'enqueue-format') {
      cy.request({url: '/api/formatting-rules/printscript/1.1', headers, log: false}).then(current => {
        expect(current.status).to.equal(200);
        const rules = Object.fromEntries(current.body.rules.map(rule => [rule.id, rule.value]));
        cy.task('saveRules', rules, {log: false});
        const currentIndent = rules['indent-inside-if'];
        const candidate = {...rules, 'indent-inside-if': currentIndent === 3 ? 4 : 3};
        cy.request({method: 'PUT', url: '/api/formatting-rules/printscript/1.1', headers, log: false,
          retryOnNetworkFailure: false, body: {rules: candidate},
        }).then(result => {
          record(result, {changed: result.body.changed, jobId: result.body.jobId});
          expect(result.status).to.equal(200);
          expect(result.body.changed).to.equal(true);
          expect(result.body.jobId).to.match(/^[a-f0-9-]{36}$/);
        });
      });
    } else if (scenario === 'restore-format') {
      cy.request({method: 'PUT', url: '/api/formatting-rules/printscript/1.1', headers, log: false,
        retryOnNetworkFailure: false, body: {rules: Cypress.env('previousRules')},
      }).then(result => {
        record(result, {changed: result.body.changed, jobId: result.body.jobId});
        expect(result.status).to.equal(200);
      });
    } else if (scenario === 'job-status') {
      const jobId = Cypress.env('jobId');
      expect(jobId).to.match(/^[a-f0-9-]{36}$/);
      cy.request({url: `/api/jobs/${jobId}`, headers, log: false}).then(result => {
        record(result, {jobId, jobStatus: result.body.status,
          processed: result.body.processed ?? null, failed: result.body.failed ?? null});
        expect(result.status).to.equal(200);
      });
    } else throw new Error('Unsupported scenario');
  });
});
