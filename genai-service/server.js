import http from 'node:http';
import { GoogleGenAI, ApiError } from '@google/genai';

const PORT = process.env.GENAI_PORT ? parseInt(process.env.GENAI_PORT) : 8001;
const HOST = '127.0.0.1';

function parseJsonBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', chunk => {
      body += chunk;
      if (body.length > 5 * 1024 * 1024) {
        reject(new Error('Payload too large'));
      }
    });
    req.on('end', () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch (e) {
        reject(e);
      }
    });
    req.on('error', reject);
  });
}

function sendJson(res, statusCode, data) {
  res.writeHead(statusCode, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(data));
}

const server = http.createServer(async (req, res) => {
  // Health check
  if (req.method === 'GET' && req.url === '/health') {
    return sendJson(res, 200, {
      status: 'online',
      sdk: '@google/genai',
      package: '@google/genai@2.32.0',
      port: PORT
    });
  }

  // Stream generateContentStream
  if (req.method === 'POST' && req.url === '/stream') {
    try {
      const payload = await parseJsonBody(req);
      const { apiKey, model, contents, systemInstruction, generationConfig } = payload;

      if (!apiKey) {
        return sendJson(res, 401, {
          error: { code: 401, message: 'API key is required.' }
        });
      }

      if (!contents || !contents.length) {
        return sendJson(res, 400, {
          error: { code: 400, message: 'Contents cannot be empty.' }
        });
      }

      const ai = new GoogleGenAI({ apiKey });
      const targetModel = (model || 'gemini-2.5-flash').replace(/^models\//, '');

      const config = {};
      if (systemInstruction) {
        config.systemInstruction = systemInstruction;
      }
      if (generationConfig) {
        if (generationConfig.temperature !== undefined) config.temperature = generationConfig.temperature;
        if (generationConfig.maxOutputTokens !== undefined) config.maxOutputTokens = generationConfig.maxOutputTokens;
      }

      // Sanitize parts for @google/genai SDK format
      const sanitizedContents = contents.map(c => ({
        role: c.role === 'assistant' ? 'model' : c.role,
        parts: (c.parts || []).map(p => {
          if (p.inline_data && !p.inlineData) {
            return {
              inlineData: {
                mimeType: p.inline_data.mime_type || p.inline_data.mimeType,
                data: p.inline_data.data
              }
            };
          }
          if (p.inlineData) {
            return {
              inlineData: {
                mimeType: p.inlineData.mimeType || p.inlineData.mime_type,
                data: p.inlineData.data
              }
            };
          }
          return p;
        })
      }));

      const responseStream = await ai.models.generateContentStream({
        model: targetModel,
        contents: sanitizedContents,
        config
      });

      res.writeHead(200, {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive'
      });

      for await (const chunk of responseStream) {
        // Filter out empty or internal parts
        const text = chunk.text;
        if (text) {
          res.write(`data: ${JSON.stringify({ text })}\n\n`);
        }
      }

      res.write('data: [DONE]\n\n');
      return res.end();
    } catch (err) {
      const statusCode = err.status || 500;
      const message = err.message || 'Error executing @google/genai request';

      // If headers haven't been sent, return JSON error
      if (!res.headersSent) {
        return sendJson(res, statusCode, {
          error: {
            code: statusCode,
            message: message
          }
        });
      } else {
        // SSE already open, emit error event and close
        res.write(`event: error\ndata: ${JSON.stringify({ error: message, code: statusCode })}\n\n`);
        return res.end();
      }
    }
  }

  // Single-shot generateContent
  if (req.method === 'POST' && req.url === '/generate') {
    try {
      const payload = await parseJsonBody(req);
      const { apiKey, model, prompt, systemInstruction } = payload;

      if (!apiKey) {
        return sendJson(res, 401, {
          error: { code: 401, message: 'API key is required.' }
        });
      }

      const ai = new GoogleGenAI({ apiKey });
      const targetModel = (model || 'gemini-2.5-flash').replace(/^models\//, '');

      const config = {};
      if (systemInstruction) {
        config.systemInstruction = systemInstruction;
      }

      const response = await ai.models.generateContent({
        model: targetModel,
        contents: prompt || '',
        config
      });

      return sendJson(res, 200, {
        text: response.text || ''
      });
    } catch (err) {
      const statusCode = err.status || 500;
      return sendJson(res, statusCode, {
        error: {
          code: statusCode,
          message: err.message || 'Error in @google/genai generateContent'
        }
      });
    }
  }

  // 404 for other routes
  return sendJson(res, 404, { error: 'Not found' });
});

server.listen(PORT, HOST, () => {
  console.log(`🧠 DOTMIND @google/genai Service listening on http://${HOST}:${PORT}`);
});
