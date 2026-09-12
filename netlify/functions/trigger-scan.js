const https = require('https');
const crypto = require('crypto');

exports.handler = async (event, context) => {
  try {
    // Get the GitHub token from Netlify environment variables
    const githubToken = process.env.GITHUB_TOKEN;
    if (!githubToken) {
      return {
        statusCode: 500,
        body: JSON.stringify({ error: 'GitHub token not configured in Netlify' })
      };
    }

    // Repository details
    const repoOwner = 'mattappsaibagus-wq';
    const repoName = 'crypto-agents';
    const workflowId = 'scan.yml'; // Workflow file name
    
    // GitHub API endpoint to trigger workflow dispatch
    const apiUrl = `https://api.github.com/repos/${repoOwner}/${repoName}/dispatches`;
    
    const requestBody = {
      event_type: 'workflow_dispatch',
      client_payload: {
        triggered_from: 'netlify_dashboard',
        timestamp: new Date().toISOString()
      }
    };

    const options = {
      hostname: 'api.github.com',
      port: 443,
      path: `/repos/${repoOwner}/${repoName}/dispatches`,
      method: 'POST',
      headers: {
        'Authorization': `token ${githubToken}`,
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'crypto-agents-dashboard',
        'Content-Type': 'application/json',
        'Content-Length': JSON.stringify(requestBody).length
      }
    };

    const promise = new Promise((resolve, reject) => {
      const req = https.request(options, (res) => {
        let data = '';
        res.on('data', (chunk) => {
          data += chunk;
        });
        res.on('end', () => {
          if (res.statusCode === 204 || res.statusCode === 200) {
            resolve({
              statusCode: 200,
              body: JSON.stringify({
                success: true,
                message: 'GitHub Actions workflow triggered successfully',
                status: res.statusCode,
                timestamp: new Date().toISOString()
              })
            });
          } else {
            let errorData;
            try {
              errorData = JSON.parse(data);
            } catch (e) {
              errorData = { message: data };
            }
            resolve({
              statusCode: res.statusCode || 500,
              body: JSON.stringify({
                success: false,
                error: `GitHub API error: ${res.statusCode || 'Unknown'} - ${errorData.message || 'Unknown error'}`,
                details: errorData
              })
            });
          }
        });
      });

      req.on('error', (error) => {
        reject({
          statusCode: 500,
          body: JSON.stringify({
            success: false,
            error: `Request error: ${error.message}`
          })
        });
      });

      req.write(JSON.stringify(requestBody));
      req.end();
    });

    return await promise;
    
  } catch (error) {
    return {
      statusCode: 500,
      body: JSON.stringify({
        success: false,
        error: `Server error: ${error.message}`
      })
    };
  }
};
