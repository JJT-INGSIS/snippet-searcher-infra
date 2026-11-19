import {fixtureName, login, search, snippet, verifyContent} from './journey';

it('finds the expected snippet and content in DEV', () => {
  cy.task('stage', 'AUTH0_LOGIN', {log: false});
  login();
  cy.task('stage', 'LISTING_HTTP', {log: false});
  search(fixtureName);
  cy.task('stage', 'SNIPPET_MISSING', {log: false});
  snippet(fixtureName).should('be.visible');
  cy.task('stage', 'DETAIL_CONTENT', {log: false});
  snippet(fixtureName).click({log: false});
  verifyContent();
  cy.task('stage', 'COMPLETE', {log: false});
});
