const fs = require('node:fs');

const stages = new Set([
  'AUTH0_LOGIN', 'LISTING_HTTP', 'SNIPPET_MISSING', 'DETAIL_CONTENT', 'COMPLETE',
  'FIXTURE_MARKER', 'FIXTURE_SAVE', 'FIXTURE_RENAME',
]);

module.exports = {
  video: false,
  screenshotOnRunFailure: false,
  trashAssetsBeforeRuns: false,
  screenshotsFolder: '/tmp/screenshots',
  videosFolder: '/tmp/videos',
  downloadsFolder: '/tmp/downloads',
  numTestsKeptInMemory: 0,
  retries: 0,
  e2e: {
    baseUrl: 'https://jjt-snippets-prod.duckdns.org',
    supportFile: false,
    specPattern: '*.cy.js',
    setupNodeEvents(on, config) {
      const {username, password} = JSON.parse(fs.readFileSync('/run/auth0.json', 'utf8'));
      if (typeof username !== 'string' || !username || typeof password !== 'string' || !password) {
        throw new Error('Invalid synthetic account configuration');
      }
      config.env = {username, password, fixtureAction: process.env.SNI89_FIXTURE_ACTION};
      on('task', {
        stage(value) {
          if (!stages.has(value)) throw new Error('Invalid check stage');
          fs.writeFileSync('/run/result/stage', value, {mode: 0o600});
          return null;
        },
      });
      return config;
    },
  },
};
