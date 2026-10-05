'use strict';
/* web/public/js/charts.js · Canvas 时序折线图（零依赖，DPR 自适应） */
class LineChart {
  constructor(canvas, opts = {}) {
    this.cv = canvas; this.ctx = canvas.getContext('2d');
    this.opts = Object.assign({ maxPoints: 180, yPad: 0.1, unit: '' }, opts);
    this.series = [];   // [{label,color,values:[]}]
    this.t = [];        // epoch 秒
  }
  setData(t, series) { this.t = t; this.series = series; this.draw(); }
  push(t, values /* {label?} 按序列顺序数组或 null */) {
    this.t.push(t);
    this.series.forEach((s, i) => { s.values.push(values ? values[i] : null); if (s.values.length > this.opts.maxPoints) s.values.shift(); });
    if (this.t.length > this.opts.maxPoints) this.t.shift();
    this.draw();
  }
  draw() {
    const cv = this.cv, ctx = this.ctx;
    const dpr = window.devicePixelRatio || 1;
    const W = cv.clientWidth || cv.parentElement.clientWidth || 600, H = cv.clientHeight || 240;
    if (cv.width !== W * dpr || cv.height !== H * dpr) { cv.width = W * dpr; cv.height = H * dpr; }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const padL = 46, padR = 12, padT = 26, padB = 18;
    const iw = W - padL - padR, ih = H - padT - padB;

    // 值域
    let vmin = Infinity, vmax = -Infinity;
    for (const s of this.series) for (const v of s.values) if (v != null && isFinite(v)) { vmin = Math.min(vmin, v); vmax = Math.max(vmax, v); }
    if (!isFinite(vmin)) { vmin = 0; vmax = 1; }
    if (vmax - vmin < 1e-6) { vmax = vmin + 1; }
    const pad = (vmax - vmin) * this.opts.yPad;
    vmin -= pad; vmax += pad;
    const X = i => this.t.length > 1 ? padL + (iw * i) / (this.t.length - 1) : padL + iw / 2;
    const Y = v => padT + ih - (ih * (v - vmin)) / (vmax - vmin);

    // 网格
    ctx.strokeStyle = 'hsl(240 5% 15% / .8)'; ctx.fillStyle = 'hsl(240 5% 64%)';
    ctx.lineWidth = 1; ctx.font = '10px ui-monospace, monospace'; ctx.textAlign = 'right';
    for (let g = 0; g <= 4; g++) {
      const v = vmin + ((vmax - vmin) * g) / 4, y = Y(v);
      ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.stroke();
      ctx.fillText(Math.abs(v) >= 1000 ? (v / 1000).toFixed(1) + 'k' : v.toFixed(Math.abs(vmax - vmin) < 10 ? 1 : 0), padL - 6, y + 3);
    }

    // 线
    for (const s of this.series) {
      ctx.strokeStyle = s.color; ctx.lineWidth = 1.8; ctx.lineJoin = 'round'; ctx.beginPath();
      let started = false;
      s.values.forEach((v, i) => {
        if (v == null || !isFinite(v)) { started = false; return; }
        const x = X(i), y = Y(v);
        if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
      });
      ctx.stroke();
      // 末端点
      for (let i = s.values.length - 1; i >= 0; i--) {
        const v = s.values[i];
        if (v != null && isFinite(v)) {
          ctx.fillStyle = s.color; ctx.beginPath(); ctx.arc(X(i), Y(v), 2.6, 0, 7); ctx.fill(); break;
        }
      }
    }

    // 图例（右上）
    ctx.textAlign = 'left'; ctx.font = '10.5px ui-sans-serif, system-ui';
    let lx = padL + 4;
    for (const s of this.series) {
      const last = [...s.values].reverse().find(v => v != null && isFinite(v));
      const label = `${s.label} ${last != null ? Math.round(last * 10) / 10 + this.opts.unit : '—'}`;
      ctx.fillStyle = s.color; ctx.fillRect(lx, 8, 8, 8);
      ctx.fillStyle = 'hsl(0 0% 98%)'; ctx.fillText(label, lx + 12, 16);
      lx += 16 + ctx.measureText(label).width + 12;
    }
  }
}
