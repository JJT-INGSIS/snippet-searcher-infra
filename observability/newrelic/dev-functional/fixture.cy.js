import {fixtureCode, fixtureName, login, search, snippet, verifyContent} from './journey';

const hiddenName = 'Fixture temporal OBS-07';
const marker = 'Fixture dedicado para observabilidad en DEV (SNI-85)';

function verifyFixtureDetails() {
  verifyContent();
  cy.task('stage', 'FIXTURE_MARKER', {log: false});
  cy.get('#detail-description', {log: false}).should($description => {
    if ($description.val() !== marker) throw new Error('Refusing to modify a different snippet');
  });
}

it('prepares or renames only the dedicated SNI-85 fixture', () => {
  cy.task('stage', 'AUTH0_LOGIN', {log: false});
  login();
  cy.task('stage', 'LISTING_HTTP', {log: false});
  const action = Cypress.env('fixtureAction');
  search(action === 'restore' ? hiddenName : fixtureName);
  cy.task('stage', 'DETAIL_CONTENT', {log: false});

  if (action === 'prepare') {
    cy.get('main', {log: false}).then($main => {
      const existing = [...$main.find('[data-testid="snippet-row"] button')]
        .some(button => button.textContent.trim() === fixtureName);
      if (existing) {
        snippet(fixtureName).click({log: false});
        verifyFixtureDetails();
        return;
      }
      cy.contains('button', 'Nuevo snippet', {log: false}).click({log: false});
      cy.contains('li', 'Crear snippet', {log: false}).click({log: false});
      cy.get('#name', {log: false}).type(fixtureName, {log: false});
      cy.get('#description', {log: false}).type(marker, {log: false});
      cy.get('#language', {log: false}).click({log: false});
      cy.contains('[role="option"]', /^printscript$/, {log: false}).click({log: false});
      cy.get('#version', {log: false}).click({log: false});
      cy.contains('[role="option"]', /^1\.1$/, {log: false}).click({log: false});
      cy.get('#create-code', {log: false}).type(fixtureCode, {log: false});
      cy.get('[data-testid="save-snippet"]', {log: false}).click({log: false});
      snippet(fixtureName).should('be.visible');
    });
  } else {
    const restoring = action === 'restore';
    const target = restoring ? fixtureName : hiddenName;
    snippet(restoring ? hiddenName : fixtureName).click({log: false});
    verifyFixtureDetails();
    cy.task('stage', 'FIXTURE_SAVE', {log: false});
    cy.get('#detail-name', {log: false}).clear({log: false}).type(target, {log: false});
    cy.get('[data-testid="save-changes"]', {log: false}).click({log: false});
    cy.task('stage', 'FIXTURE_RENAME', {log: false});
    cy.contains('[role="alert"]', 'Cambios guardados.', {timeout: 20_000, log: false}).should('be.visible');
  }
  cy.task('stage', 'COMPLETE', {log: false});
});
