const fs = require('node:fs');

module.exports = {
  video: false, screenshotOnRunFailure: false, trashAssetsBeforeRuns: false,
  screenshotsFolder: '/tmp/screenshots', videosFolder: '/tmp/videos', downloadsFolder: '/tmp/downloads',
  numTestsKeptInMemory: 0, retries: 0,
  e2e: {
    baseUrl: 'https://jjt-snippets-dev.duckdns.org', supportFile: false, specPattern: 'dev.cy.js',
    setupNodeEvents(on, config) {
      const credentials = JSON.parse(fs.readFileSync('/run/auth0.json', 'utf8'));
      if (!credentials.username || !credentials.password) throw new Error('Missing dedicated test identity');
      config.env = {...credentials, scenario: process.env.SNI87_SCENARIO, jobId: process.env.SNI87_JOB_ID};
      if (config.env.scenario === 'restore-format') {
        config.env.previousRules = JSON.parse(fs.readFileSync('/run/rules-before.json', 'utf8'));
      }
      on('task', {
        awaitPrintscriptCut() {
          fs.writeFileSync('/run/result/cut-requested', 'ready', {mode: 0o600});
          return new Promise((resolve, reject) => {
            const started = Date.now();
            const poll = setInterval(() => {
              if (fs.existsSync('/run/result/cut-complete')) {clearInterval(poll); resolve(null);}
              else if (Date.now() - started > 80_000) {clearInterval(poll); reject(new Error('Cut handshake timed out'));}
            }, 100);
          });
        },
        saveRules(rules) {
          if (!rules || Array.isArray(rules) || Object.keys(rules).length > 64 ||
              Object.values(rules).some(value => value !== null && !['boolean', 'number'].includes(typeof value))) {
            throw new Error('Invalid rule snapshot');
          }
          fs.writeFileSync('/run/result/rules-before.json', JSON.stringify(rules), {mode: 0o600});
          return null;
        },
        stage(value) {
          if (!['AUTH0_LOGIN', 'LISTING_HTTP', 'SNIPPET_MISSING', 'DETAIL_CONTENT', 'COMPLETE'].includes(value)) {
            throw new Error('Invalid stage');
          }
          fs.writeFileSync('/run/result/stage', value, {mode: 0o600});
          return null;
        },
        evidence(value) {
          const allowed = new Set(['at', 'scenario', 'status', 'requestId', 'snippetId', 'idempotencyKey',
            'problemType', 'jobId', 'changed', 'jobStatus', 'processed', 'failed']);
          if (!value || Object.keys(value).some(key => !allowed.has(key)) ||
              Object.values(value).some(item => item !== null && !['string', 'number', 'boolean'].includes(typeof item))) {
            throw new Error('Invalid evidence fields');
          }
          fs.appendFileSync('/run/result/evidence.jsonl', JSON.stringify(value) + '\n', {mode: 0o600});
          return null;
        },
      });
      return config;
    },
  },
};
