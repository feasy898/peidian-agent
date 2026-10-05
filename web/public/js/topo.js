'use strict';
/* web/public/js/topo.js · SVG 电气拓扑渲染器（全景/局部共用）
 * 布局：从上级电源 BFS 分层（y），配电房分列（x），确定性、可复算。
 */
const TOPO = (() => {
  const COL_W = 240, ROW_H = 92, X0 = 90, Y0 = 84;

  function glyph(type) {
    switch (type) {
      case 'Transformer': return '<circle cx="15" cy="17" r="10" class="glyph-box"/><circle cx="29" cy="17" r="10" class="glyph-box"/>';
      case 'Bus': return '';
      case 'Switchgear': return '<rect x="8" y="7" width="28" height="20" rx="4" class="glyph-box"/><path d="M14 22 30 12" class="edge"/>';
      case 'Load': return '<rect x="10" y="10" width="24" height="16" rx="3" class="glyph-box"/><path d="M22 4v6m-4-4 4 4 4-4" fill="none" stroke="hsl(var(--c-load))" stroke-width="1.6"/>';
      case 'PV': return '<rect x="9" y="9" width="26" height="17" rx="2" class="glyph-box"/><path d="M12 13h20M12 18h20M22 9v17" class="edge"/>';
      case 'BESS': return '<rect x="8" y="9" width="26" height="16" rx="3" class="glyph-box"/><rect x="34" y="13" width="3" height="8" rx="1" class="glyph-box"/><path d="M15 17h8m-3-3 3 3-3 3" fill="none" stroke="hsl(var(--c-bess))" stroke-width="1.5"/>';
      case 'EVCharger': return '<rect x="11" y="7" width="22" height="22" rx="4" class="glyph-box"/><circle cx="22" cy="15" r="3" fill="hsl(var(--c-evc))"/><path d="M17 24h10" class="edge"/>';
      case 'GridInlet': return '<path d="M22 4 8 28h28z" class="glyph-box"/><path d="M22 12v16" class="edge"/>';
      case 'CapacitorBank': return '<rect x="10" y="9" width="24" height="17" rx="3" class="glyph-box"/><path d="M18 13v9m8-9v9" stroke="hsl(var(--c-pv))" stroke-width="1.6"/>';
      default: return `<rect x="8" y="8" width="28" height="18" rx="4" class="glyph-box"/>`;
    }
  }

  /** 计算布局：nodes Map(id -> {x,y,type})，edges [{from,to,...}]，subBoxes */
  function layout(parkJson, opts = {}) {
    const onlySub = opts.substation || null;
    const nodes = new Map();
    const list = (parkJson.nodes || []).filter(n => !onlySub || n.substation === onlySub);
    const links = (parkJson.links || []).filter(l => {
      if (onlySub) {
        const idOf = new Set(list.map(n => n.id));
        return idOf.has(l.from) && idOf.has(l.to);
      }
      return true;
    });

    // BFS 深度（常开耦合器断开）
    const ids = new Set(list.map(n => n.id));
    const adj = new Map([...ids].map(i => [i, []]));
    for (const l of links) {
      const open = l.kind === 'coupler' && (l.state || 'OPEN') === 'OPEN';
      if (open || !adj.has(l.from) || !adj.has(l.to)) continue;
      adj.get(l.from).push(l.to); adj.get(l.to).push(l.from);
    }
    const depth = new Map();
    const q = (parkJson.nodes || []).filter(n => n.type === 'GridInlet' && ids.has(n.id)).map(n => (depth.set(n.id, 0), n.id));
    if (!q.length && ids.size) { const f = [...ids][0]; depth.set(f, 0); q.push(f); }
    while (q.length) {
      const u = q.shift();
      for (const v of adj.get(u) || []) if (!depth.has(v)) { depth.set(v, depth.get(u) + 1); q.push(v); }

    }
    // 未可达节点（如断开的联络段）排到最后几行
    let maxD = Math.max(0, ...[...depth.values()]);
    for (const id of ids) if (!depth.has(id)) depth.set(id, ++maxD);

    // 列：无 substation 的（GRID）第 0 列，其余按 substation 出现序
    const subOrder = [];
    for (const n of list) {
      const key = n.substation || '_grid';
      if (!subOrder.includes(key)) subOrder.push(key);
    }
    const colOf = new Map(subOrder.map((s, i) => [s, i]));

    // (col, depth) 槽位
    const slots = new Map();
    for (const n of list) {
      const key = (n.substation || '_grid') + '|' + depth.get(n.id);
      if (!slots.has(key)) slots.set(key, []);
      slots.get(key).push(n);
    }
    const pos = new Map();
    for (const [key, arr] of slots) {
      const [sub, d] = key.split('|');
      const col = colOf.get(sub);
      const y = Y0 + parseInt(d, 10) * ROW_H;
      arr.sort((a, b) => String(a.id).localeCompare(String(b.id)));
      arr.forEach((n, i) => {
        const isBus = n.type === 'Bus';
        const x = X0 + col * COL_W + (arr.length === 1 ? 44 : 8 + i * 74);
        pos.set(n.id, { x, y, type: n.type, node: n, isBus });
      });
    }

    // 配电房外框（第 0 列是 GRID，跳过）
    const subBoxes = [];
    if (!onlySub) {
      for (const subId of subOrder) {
        if (subId === '_grid') continue;
        const ds = [...pos.entries()].filter(([id, p]) => p.node.substation === subId)
          .map(([id]) => depth.get(id));
        if (!ds.length) continue;
        const minD = Math.min(...ds), maxD = Math.max(...ds);
        const c = colOf.get(subId);
        const s = (parkJson.substations || []).find(x => x.id === subId);
        subBoxes.push({
          x: X0 + c * COL_W - 26, y: Y0 + minD * ROW_H - 38,
          w: COL_W - 24, h: (maxD - minD) * ROW_H + 118,
          name: s ? s.name : subId,
        });
      }
    }

    // 边
    const edges = links.map(l => ({ ...l, p1: pos.get(l.from), p2: pos.get(l.to) })).filter(e => e.p1 && e.p2);
    return { pos, edges, subBoxes, depth };
  }
  /** 渲染到 svg 元素 */
  function render(svg, parkJson, opts = {}) {
    const { pos, edges, subBoxes } = layout(parkJson, opts);
    const live = opts.live || new Map();
    let maxX = 200, maxY = 200;
    for (const p of pos.values()) { maxX = Math.max(maxX, p.x + 120); maxY = Math.max(maxY, p.y + 110); }

    const parts = [];
    for (const sb of subBoxes) {
      parts.push(`<rect class="substation-box" x="${sb.x}" y="${sb.y}" width="${sb.w}" height="${sb.h}" rx="12"/>`);
      parts.push(`<text class="substation-name" x="${sb.x + 14}" y="${sb.y + 20}">${esc(sb.name)}</text>`);
    }
    // 边
    for (const e of edges) {
      const { p1, p2 } = e;
      const x1 = p1.x, y1 = p1.y + (p1.isBus ? 5 : 17), x2 = p2.x, y2 = p2.y + (p2.isBus ? 5 : 17);
      const cls = 'edge' + (e.kind === 'coupler' ? ' coupler' : '');
      parts.push(`<line class="${cls}" x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/>`);
      if (e.kind === 'line' && e.id) {
        parts.push(`<text class="edge-label" x="${(x1 + x2) / 2 - 14}" y="${(y1 + y2) / 2 - 4}">${esc(e.id)}</text>`);
      }
      if (e.kind === 'coupler') {
        const open = (e.state || 'OPEN') === 'OPEN';
        parts.push(`<rect x="${(x1 + x2) / 2 - 5}" y="${(y1 + y2) / 2 - 5}" width="10" height="10" fill="hsl(var(--card))" stroke="${open ? 'hsl(var(--warning))' : 'hsl(var(--success))'}" stroke-width="1.6"/>`);
        parts.push(`<text class="edge-label" x="${(x1 + x2) / 2 + 10}" y="${(y1 + y2) / 2 + 3}">${open ? '常开' : '合环'}</text>`);
      }
    }
    // 节点
    for (const [id, p] of pos) {
      const lv = live.get(id) || {};
      const isBus = p.type === 'Bus';
      const w = isBus ? 108 : 44, h = isBus ? 10 : 34;
      const x = isBus ? p.x - 54 : p.x - 22, y = p.y;
      const subLine = isBus
        ? `<text class="glyph-sub" x="${p.x}" y="${y - 5}" text-anchor="middle">${esc(p.node.params?.voltage_level || '')}</text>`
        : '';
      const liveTxt = lv.p != null ? `${fmt(lv.p)} kW`
        : (lv.v != null ? `${Math.round(lv.v)} V` : '');
      const liveEl = liveTxt ? `<text class="live-val" x="${p.x}" y="${y + h + 26}" text-anchor="middle">${liveTxt}</text>` : '';
      parts.push(`<g class="node${opts.pickable ? ' pickable' : ''}${opts.selected && opts.selected.has(id) ? ' selected' : ''}${opts.faultIds && opts.faultIds.has(id) ? ' fault-hit' : ''}" data-id="${esc(id)}" transform="translate(${x},${y})">
        ${isBus ? `<rect class="glyph-box" x="0" y="0" width="${w}" height="${h}" rx="4"/>` : glyph(p.type)}
        ${subLine}
        <text class="glyph-label" x="${isBus ? w / 2 : 22}" y="${h + 13}" text-anchor="middle">${esc(id)}</text>
        ${liveEl}
      </g>`);
    }

    svg.setAttribute('width', maxX);
    svg.setAttribute('height', maxY);
    svg.setAttribute('viewBox', `0 0 ${maxX} ${maxY}`);
    svg.innerHTML = parts.join('');

    if (opts.onNodeClick) {
      svg.querySelectorAll('.node.pickable').forEach(g => {
        g.addEventListener('click', () => opts.onNodeClick(g.dataset.id));
      });
    }
  }

  function fmt(v) { return Math.abs(v) >= 1000 ? (v / 1000).toFixed(2) + 'k' : Math.round(v * 10) / 10; }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

  return { layout, render };
})();
