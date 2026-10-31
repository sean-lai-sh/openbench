import { createAnthropic } from '/h1/opencode-src/provider-pins/2.0.58/node_modules/@ai-sdk/anthropic/dist/index.mjs';
const m = createAnthropic({ baseURL: 'http://127.0.0.1:40475/v1', apiKey: 'probe' })('claude-opus-5-5');
const r = await m.doGenerate({ prompt: [{ role: 'user', content: [{ type: 'text', text: 'Reply with OK.' }] }], maxOutputTokens: 8 });
console.log(JSON.stringify({ text: r.content ?? r.text, usage: r.usage }));