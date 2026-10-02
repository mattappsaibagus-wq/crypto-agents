// Starts the "Auto-scan" GitHub Actions workflow (scan.yml) on demand.
// Called via /api/trigger-scan or /api/run (see netlify.toml redirects).
//
// Uses the workflow_dispatch API, which matches the `workflow_dispatch:`
// trigger already in scan.yml. (The old version sent a repository_dispatch
// event that scan.yml never listened for, so nothing ran.)

const https = require('https');

const REPO_OWNER = 'mattappsaibagus-wq';
const REPO_NAME = 'crypto-agents';
const WORKFLOW_FILE = 'scan.yml';
const BRANCH = 'main';

function json(statusCode, body) {
  return {
    statusCode,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  };
}

exports.handler = async () => {
  // The Netlify variable is currently named GITHUN_TOKEN (typo); accept both
  // so the function works whether or not it gets renamed later.
  const githubToken = process.env.GITHUB_TOKEN || process.env.GITHUN_TOKEN;
  if (!githubToken) {
    return json(500, {
      success: false,
      error: 'GitHub token not configured. Add GITHUB_TOKEN in Netlify → Project configuration → Environment variables (needs Actions write access to crypto-agents).',
    });
  }

  const payload = JSON.stringify({ ref: BRANCH });
  const options = {
    hostname: 'api.github.com',
    port: 443,
    path: `/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/${WORKFLOW_FILE}/dispatches`,
    method: 'POST',
    headers: {
      Authorization: `Bearer ${githubToken}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'crypto-agents-dashboard',
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(payload),
    },
  };

  try {
    const result = await new Promise((resolve, reject) => {
      const req = https.request(options, (res) => {
        let data = '';
        res.on('data', (chunk) => { data += chunk; });
        res.on('end', () => resolve({ status: res.statusCode, data }));
      });
      req.on('error', reject);
      req.write(payload);
      req.end();
    });

    if (result.status === 204) {
      return json(200, {
        success: true,
        message: 'Scan started. Fresh results appear on the dashboard in a few minutes.',
        workflow_url: `https://github.com/${REPO_OWNER}/${REPO_NAME}/actions/workflows/${WORKFLOW_FILE}`,
        timestamp: new Date().toISOString(),
      });
    }

    let details;
    try { details = JSON.parse(result.data); } catch (e) { details = { message: result.data }; }
    return json(result.status || 500, {
      success: false,
      error: `GitHub API error ${result.status}: ${details.message || 'Unknown error'}`,
    });
  } catch (error) {
    return json(500, { success: false, error: `Request error: ${error.message}` });
  }
};
