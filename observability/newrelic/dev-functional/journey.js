const auth0Origin = 'https://jjt-snippet-searcher.us.auth0.com';
const timeout = 20_000;
const filter = 'input[placeholder="Nombre del snippet…"]';
export const fixtureName = 'SNI-85 Synthetic';
export const fixtureCode = 'println("SNI-85 OK");';

export function login() {
  cy.visit('/', {log: false});
  cy.get('[data-testid="login"]', {timeout, log: false}).first().click({log: false});
  cy.origin(auth0Origin, {args: {username: Cypress.env('username'), password: Cypress.env('password'), timeout}},
    ({username, password, timeout}) => {
      const submit = 'button[value="default"]:visible';
      const typeOptions = {log: false, parseSpecialCharSequences: false};
      cy.get('input#username', {timeout, log: false}).type(username, typeOptions);
      cy.get('body', {log: false}).then($body => {
        if (!$body.find('input#password:visible').length) {
          cy.get(submit, {log: false}).first().click({log: false});
        }
      });
      cy.get('input#password:visible', {timeout, log: false}).type(password, typeOptions);
      cy.get(submit, {log: false}).first().click({log: false});
    });
  cy.get(filter, {timeout, log: false}).should('be.visible');
}

export function search(name) {
  cy.get(filter, {log: false}).clear({log: false}).type(name, {log: false});
  cy.window({timeout, log: false}).should(window => {
    const listings = window.performance.getEntriesByType('resource').filter(entry => {
      const url = new URL(entry.name);
      return url.origin === window.location.origin && url.pathname === '/api/snippets' &&
        url.searchParams.get('name') === name;
    });
    if (listings.at(-1)?.responseStatus !== 200) throw new Error('Expected HTTP 200 for the filtered listing');
  });
}

export function snippet(name) {
  return cy.contains('[data-testid="snippet-row"] button', new RegExp(`^${name}$`), {timeout, log: false});
}

export function verifyContent() {
  cy.get('#detail-code', {timeout, log: false}).should($code => {
    if ($code.val() !== fixtureCode) throw new Error('The fixture content did not match');
  });
}
