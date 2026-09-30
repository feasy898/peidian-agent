'use strict';
/* web/public/js/api.js · 轻量 API 封装（相对路径：支持反代子路径 /peidian-agent/ 部署，DEPLOY.md §4 方案 B） */
const API = (() => {
  async function j(method, url, body) {
    const opt = { method, headers: {} };
    if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
    const r = await fetch(url, opt);
    if (!r.ok) {
      let e = {};
      try { e = await r.json(); } catch (_) { /* noop */ }
      const err = new Error(e.error || ('HTTP ' + r.status));
      err.status = r.status; err.body = e;   // 422 拒绝等场景保留 reasons
      throw err;
    }
    return r.json();
  }
  return {
    parks: () => j('GET', 'api/parks'),
    park: (id) => j('GET', 'api/park/' + encodeURIComponent(id)),
    telemetry: (park, points, t) => j('GET', 'api/telemetry?park=' + encodeURIComponent(park) + '&points=' + points + (t ? '&t=' + t : '')),
    fault: (park, text) => j('POST', 'api/fault', { park, text }),
    clear: (park) => j('POST', 'api/fault/clear', { park }),
    attempt: (park, targets, started_at) => j('POST', 'api/human/attempt', { park, targets, started_at }),
  };
})();
