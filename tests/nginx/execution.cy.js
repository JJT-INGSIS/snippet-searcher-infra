// Opt-in SNI-52 transport checks. NGINX/fixture API + a real local Spring backend.
// No cy.intercept, interpreter or application execution endpoints are provided here.
describe('SNI-52 / real browser transport', () => {
  it('reads NDJSON and sends input before the controlled upstream finishes', () => {
    cy.visit('/');
    cy.window().then({timeout: 15000}, async win => {
      const path = '/api/executions/' + win.crypto.randomUUID();
      const controller = new win.AbortController();
      const timer = win.setTimeout(() => controller.abort(), 6000);
      try {
        const response = await win.fetch(path + '/events?after=1', {signal: controller.signal});
        expect(response.status).to.eq(200);
        expect(response.headers.get('Content-Type')).to.eq('application/x-ndjson');
        expect(response.headers.get('Cache-Control')).to.eq('no-store');
        const reader = response.body.getReader();
        const decoder = new win.TextDecoder();
        const records = [];
        let pending = '';
        while (true) {
          const {value, done} = await reader.read();
          pending += decoder.decode(value, {stream: !done});
          const lines = pending.split('\n');
          pending = lines.pop();
          for (const line of lines) {
            const event = JSON.parse(line);
            records.push(event);
            if (event.type === 'output') {
              expect(event.data.text).to.eq('¡Hola 🌎!');
              const state = await (await win.fetch(path)).json();
              expect(state.finished, 'output arrives while upstream still waits').to.eq(false);
            }
            if (event.type === 'input-required') {
              const accepted = await win.fetch(path + '/inputs', {method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-Dev-Actor-Id': 'fixture-actor'},
                body: JSON.stringify({requestId: event.data.requestId, value: 'ñ\n'})});
              expect(accepted.status).to.eq(200);
            }
          }
          if (done) break;
        }
        expect(pending).to.eq('');
        expect(records.map(row => row.seq)).to.deep.eq([2, 3, 4, 5]);
        expect(records.map(row => row.type)).to.deep.eq(['output', 'heartbeat', 'input-required', 'terminal']);
      } finally {
        controller.abort();
        win.clearTimeout(timer);
      }
    });
  });

  it('allows SNI-45 preflights and readable errors through the real Spring CORS filter', () => {
    cy.visit('/');
    cy.window().then(async win => {
      const backend = Cypress.env('backend');
      expect(backend, 'local Spring backend with this page origin explicitly allowed').to.be.a('string');
      const id = '550e8400-e29b-41d4-a716-446655440011';
      for (const [path, method] of [[`/executions/${id}/events?after=1`, 'GET'],
        [`/executions/${id}/inputs`, 'POST'], [`/executions/${id}/cancel`, 'POST']]) {
        const response = await win.fetch(backend + path, {method,
          headers: {'Content-Type': 'application/json', 'X-Dev-Actor-Id': 'dev-thiago'},
          ...(method === 'POST' ? {body: '{}'} : {})});
        // Missing endpoints/sessions remain errors: CORS never implements the operation.
        expect(response.status).to.be.oneOf([400, 401, 404]);
      }
      for (const options of [{method: 'DELETE'}, {headers: {Authorization: 'Bearer fixture'}}]) {
        let rejected = false;
        try {
          await win.fetch(backend + `/executions/${id}/events`, options);
        } catch (error) {
          rejected = true;
          expect(error.name).to.eq('TypeError');
        }
        expect(rejected, 'browser rejects unauthorized method/header').to.eq(true);
      }
    });
  });

  it('blocks the same Spring request from the unlisted 127.0.0.1 origin', () => {
    const otherOrigin = Cypress.config('baseUrl').replace('localhost', '127.0.0.1');
    cy.visit(otherOrigin, {failOnStatusCode: false});
    cy.window().then(async win => {
      let rejected = false;
      try {
        await win.fetch(Cypress.env('backend') + '/executions/550e8400-e29b-41d4-a716-446655440011/events',
          {headers: {'X-Dev-Actor-Id': 'dev-thiago'}});
      } catch (error) {
        rejected = true;
        expect(error.name).to.eq('TypeError');
      }
      expect(rejected, 'browser enforces exact origins').to.eq(true);
    });
  });
});
