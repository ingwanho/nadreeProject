// Local contract subset: https://developer.paypal.com/api/orders/v2/orders-create
// Fake credentials only. Unknown operations are intentionally unsupported.
const http = require('http');
http.createServer(async (req, res) => {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString();
  const reply = (status, body) => {
    res.writeHead(status, {'Content-Type': 'application/json'});
    res.end(JSON.stringify(body));
  };
  if (req.method === 'POST' && req.url === '/v1/oauth2/token') {
    if (new URLSearchParams(raw).get('grant_type') !== 'client_credentials') {
      return reply(400, {error: 'unsupported_grant_type'});
    }
    return reply(200, {access_token: 'local-simulation-token', token_type: 'Bearer', expires_in: 3600});
  }
  if (req.method === 'POST' && req.url === '/v2/checkout/orders') {
    let body;
    try { body = JSON.parse(raw); } catch { return reply(400, {name: 'INVALID_REQUEST'}); }
    const experience = body.payment_source?.paypal?.experience_context;
    const expected = 'https://na-dree.com/api/v1/nadree/rental/payment/return';
    if (body.intent !== 'CAPTURE' || body.purchase_units?.length !== 1 ||
        !body.purchase_units[0].payee?.merchant_id || experience?.return_url !== expected ||
        experience?.cancel_url !== expected + '?cancelled=true') {
      return reply(400, {name: 'INVALID_REQUEST'});
    }
    return reply(201, {id: '5O190127TN364715T', status: 'PAYER_ACTION_REQUIRED',
      links: [{rel: 'payer-action', method: 'GET',
        href: 'https://www.sandbox.paypal.com/checkoutnow?token=5O190127TN364715T'}]});
  }
  reply(501, {name: 'SIMULATION_OPERATION_NOT_IMPLEMENTED'});
}).listen(process.env.PORT);
