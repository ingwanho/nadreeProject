// Narrow S3 HEAD/GetObject/CopyObject wire contract; no AWS authentication emulator.
const http = require('http');
const etag = '"098f6bcd4621d373cade4e832627b4f6"';
const version = 'source-version-1';
http.createServer((req, res) => {
  const path = new URL(req.url, 'http://localhost').pathname;
  const error = (status, code) => {
    res.writeHead(status, {'Content-Type': 'application/xml'});
    res.end(`<Error><Code>${code}</Code><Message>Synthetic local test</Message></Error>`);
  };
  if (path.includes('/missing/')) return error(404, 'NoSuchKey');
  if (path.includes('/unavailable/')) return error(503, 'ServiceUnavailable');
  if (req.method === 'HEAD') {
    res.writeHead(200, {'Content-Length': '4', ETag: etag, 'x-amz-version-id': version});
    return res.end();
  }
  if (req.method === 'GET') {
    if (req.headers['if-match'] !== etag) return error(412, 'PreconditionFailed');
    res.writeHead(200, {'Content-Type': 'video/mp4', 'Content-Length': '4', ETag: etag});
    return res.end('test');
  }
  if (req.method === 'PUT' && req.headers['x-amz-copy-source']) {
    if (req.headers['x-amz-copy-source-if-match'] !== etag) return error(412, 'PreconditionFailed');
    if (!decodeURIComponent(req.headers['x-amz-copy-source']).includes('versionId=' + version)) {
      return error(412, 'PreconditionFailed');
    }
    res.writeHead(200, {'Content-Type': 'application/xml', 'x-amz-version-id': 'final-version-1'});
    return res.end(`<CopyObjectResult><ETag>${etag}</ETag><LastModified>2026-11-24T00:00:00Z</LastModified></CopyObjectResult>`);
  }
  return error(501, 'NotImplemented');
}).listen(process.env.PORT || 4500);
