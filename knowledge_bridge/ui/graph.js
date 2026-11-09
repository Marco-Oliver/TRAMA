/* TRAMA — Grafo de conexões (canvas, sem dependências externas).
   Uso: const g = TramaGraph.mount(container, {nodes, edges}, {onOpen(id){...}});
   nodes: [{id, title, kind, degree?}]   kind: aula | conceito | duvida | projeto | resumo | indice | outro
   edges: [[a, b], ...] índices em nodes */
(function (global) {
  'use strict';

  const KINDS = {
    aula:     { label: 'Aulas',     color: '#4f8fd0' },
    conceito: { label: 'Conceitos', color: '#3fa774' },
    duvida:   { label: 'Dúvidas',   color: '#e0a43a' },
    projeto:  { label: 'Projetos',  color: '#c0794f' },
    resumo:   { label: 'Resumos',   color: '#2f9c9c' },
    indice:   { label: 'Índices',   color: '#8a7bb8' },
    outro:    { label: 'Outros',    color: '#8c9a93' }
  };
  const THEMES = {
    claro:  { bg: '#fbfcfa', edge: 'rgba(60,80,70,0.18)', edgeHi: 'rgba(40,110,75,0.75)',
              label: '#22302a', labelBg: 'rgba(251,252,250,0.85)', dim: 0.16 },
    escuro: { bg: '#1e2124', edge: 'rgba(200,210,205,0.14)', edgeHi: 'rgba(170,230,195,0.8)',
              label: '#e8ece9', labelBg: 'rgba(30,33,36,0.8)', dim: 0.12 }
  };

  function mount(container, data, options) {
    options = options || {};
    const state = {
      theme: options.theme === 'escuro' ? 'escuro' : 'claro',
      showIndex: false,
      hidden: new Set(),
      query: '',
      hover: -1,
      drag: -1,
      pan: false,
      view: { x: 0, y: 0, k: 1 },
      alpha: 1
    };

    // ---------- dados ----------
    const nodes = (data.nodes || []).map((n, i) => ({
      i, id: n.id, title: String(n.title || n.id), kind: KINDS[n.kind] ? n.kind : 'outro',
      x: Math.cos(i * 2.399) * (40 + 9 * Math.sqrt(i)),
      y: Math.sin(i * 2.399) * (40 + 9 * Math.sqrt(i)),
      vx: 0, vy: 0, fixed: false, deg: 0, nb: new Set()
    }));
    const edges = [];
    for (const e of data.edges || []) {
      const a = nodes[e[0]], b = nodes[e[1]];
      if (!a || !b || a === b) continue;
      edges.push([a, b]);
    }
    let labelCut = 0;
    function resize() {                               // tamanho pelo nº de conexões VISÍVEIS
      nodes.forEach(n => { n.deg = 0; n.nb = new Set(); });
      for (const [a, b] of edges) {
        if (!visible(a) || !visible(b)) continue;
        a.deg++; b.deg++; a.nb.add(b.i); b.nb.add(a.i);
      }
      const vis = nodes.filter(visible), maxDeg = Math.max(1, ...vis.map(n => n.deg));
      nodes.forEach(n => { n.r = 4.5 + 11 * Math.sqrt(n.deg / maxDeg); });
      const sorted = vis.map(n => n.deg).sort((a, b) => b - a);
      labelCut = sorted[Math.min(11, sorted.length - 1)] || 0;
    }

    // ---------- DOM (sem estilos inline: CSP do app) ----------
    container.innerHTML = '';
    container.classList.add('tg-root');
    const bar = el('div', 'tg-toolbar');
    const search = el('input', 'tg-search'); search.type = 'search'; search.placeholder = 'Buscar nota no grafo…';
    const legend = el('div', 'tg-legend');
    const idxToggle = button('Mostrar índices', 'tg-chip');
    const themeToggle = button('Tema escuro', 'tg-chip');
    const fit = button('Centralizar', 'tg-chip');
    bar.append(search, legend, idxToggle, themeToggle, fit);
    const canvas = el('canvas', 'tg-canvas');
    const tip = el('div', 'tg-tip hidden');
    container.append(bar, canvas, tip);
    const ctx = canvas.getContext('2d');
    const visible = n => !state.hidden.has(n.kind);

    for (const [kind, meta] of Object.entries(KINDS)) {
      if (!nodes.some(n => n.kind === kind)) continue;
      const chip = button('', 'tg-chip tg-kind on');
      chip.dataset.kind = kind;
      const dot = el('span', 'tg-dot tg-dot-' + kind);
      const count = nodes.filter(n => n.kind === kind).length;
      chip.append(dot, document.createTextNode(meta.label + ' (' + count + ')'));
      chip.addEventListener('click', () => {
        state.hidden.has(kind) ? state.hidden.delete(kind) : state.hidden.add(kind);
        chip.classList.toggle('on', !state.hidden.has(kind)); reheat();
      });
      legend.append(chip);
    }
    if (nodes.some(n => n.kind === 'indice')) state.hidden.add('indice');
    legend.querySelectorAll('[data-kind="indice"]').forEach(c => c.classList.remove('on'));
    idxToggle.addEventListener('click', () => {
      state.showIndex = !state.showIndex;
      state.showIndex ? state.hidden.delete('indice') : state.hidden.add('indice');
      legend.querySelectorAll('[data-kind="indice"]').forEach(c => c.classList.toggle('on', state.showIndex));
      idxToggle.textContent = state.showIndex ? 'Ocultar índices' : 'Mostrar índices'; reheat();
    });
    function applyTheme(theme, save) {
      state.theme = theme === 'escuro' ? 'escuro' : 'claro';
      container.classList.toggle('tg-dark', state.theme === 'escuro');
      themeToggle.textContent = state.theme === 'claro' ? 'Tema escuro' : 'Tema claro';
      if (save) { try { localStorage.setItem('trama.graph.theme', state.theme); } catch (_) {} }
    }
    themeToggle.addEventListener('click', () => applyTheme(state.theme === 'claro' ? 'escuro' : 'claro', true));
    let storedTheme = null;
    try { storedTheme = localStorage.getItem('trama.graph.theme'); } catch (_) {}
    applyTheme(storedTheme || state.theme, false);
    search.addEventListener('input', () => { state.query = norm(search.value); });
    fit.addEventListener('click', () => fitView(true));


    // ---------- física ----------
    function tick() {
      const vis = nodes.filter(visible);
      const a = state.alpha;
      for (let p = 0; p < vis.length; p++) {           // repulsão (O(n²): ok até ~800 nós)
        const u = vis[p];
        for (let q = p + 1; q < vis.length; q++) {
          const v = vis[q];
          let dx = v.x - u.x, dy = v.y - u.y, d2 = dx * dx + dy * dy || 0.01;
          if (d2 > 250000) continue;
          const f = (2400 * a) / d2, d = Math.sqrt(d2);
          dx = (dx / d) * f; dy = (dy / d) * f;
          u.vx -= dx; u.vy -= dy; v.vx += dx; v.vy += dy;
        }
      }
      for (const [u, v] of edges) {                    // molas
        if (!visible(u) || !visible(v)) continue;
        const dx = v.x - u.x, dy = v.y - u.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
        const f = (d - 95) * 0.018 * a;
        const fx = (dx / d) * f, fy = (dy / d) * f;
        u.vx += fx; u.vy += fy; v.vx -= fx; v.vy -= fy;
      }
      for (const n of vis) {                           // gravidade + atrito
        n.vx -= n.x * 0.0022 * a; n.vy -= n.y * 0.0022 * a;
        if (n.fixed) { n.vx = n.vy = 0; continue; }
        n.vx *= 0.82; n.vy *= 0.82; n.x += n.vx; n.y += n.vy;
      }
      state.alpha = Math.max(0, state.alpha * 0.985 - 0.0005);
    }
    function reheat() { resize(); state.alpha = Math.max(state.alpha, 0.5); }

    // ---------- desenho ----------
    function draw() {
      const t = THEMES[state.theme], dpr = global.devicePixelRatio || 1;
      const w = canvas.clientWidth, h = canvas.clientHeight;
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
        canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = t.bg; ctx.fillRect(0, 0, w, h);
      const { x: ox, y: oy, k } = state.view;
      ctx.setTransform(dpr * k, 0, 0, dpr * k, dpr * (w / 2 + ox), dpr * (h / 2 + oy));

      const focus = state.hover >= 0 ? state.hover : state.drag;
      const hits = state.query ? new Set(nodes.filter(n => visible(n) && norm(n.title).includes(state.query)).map(n => n.i)) : null;
      const lit = n => focus < 0 ? (!hits || hits.has(n.i)) : (n.i === focus || nodes[focus].nb.has(n.i));

      ctx.lineWidth = 1 / k;
      for (const [u, v] of edges) {
        if (!visible(u) || !visible(v)) continue;
        const on = focus >= 0 && (u.i === focus || v.i === focus);
        ctx.strokeStyle = on ? t.edgeHi : t.edge;
        ctx.lineWidth = (on ? 1.6 : 1) / k;
        ctx.beginPath(); ctx.moveTo(u.x, u.y); ctx.lineTo(v.x, v.y); ctx.stroke();
      }
      for (const n of nodes) {
        if (!visible(n)) continue;
        ctx.globalAlpha = lit(n) ? 1 : t.dim;
        ctx.fillStyle = KINDS[n.kind].color;
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2); ctx.fill();
        if (n.i === focus) { ctx.lineWidth = 2.5 / k; ctx.strokeStyle = t.label; ctx.stroke(); }
      }
      ctx.globalAlpha = 1;
      const fs = 12 / Math.sqrt(k);
      ctx.font = '600 ' + fs + 'px "Segoe UI", system-ui, sans-serif';
      ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      const placed = [];
      const order = nodes.filter(visible).sort((a, b) => (b.i === focus) - (a.i === focus) || b.deg - a.deg);
      for (const n of order) {
        const show = n.i === focus || (focus >= 0 && nodes[focus].nb.has(n.i)) ||
                     (hits && hits.has(n.i)) || (focus < 0 && !hits && (n.deg >= labelCut || k > 1.6));
        if (!show) continue;
        const text = n.title.length > 34 ? n.title.slice(0, 33) + '…' : n.title;
        const tw = ctx.measureText(text).width, y = n.y + n.r + 3 / k;
        const box = [n.x - tw / 2 - 4 / k, y - 2 / k, n.x + tw / 2 + 4 / k, y + fs + 3 / k];
        if (n.i !== focus && placed.some(b => box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1])) continue;
        placed.push(box);
        ctx.fillStyle = t.labelBg; ctx.fillRect(n.x - tw / 2 - 3 / k, y - 1 / k, tw + 6 / k, fs + 3 / k);
        ctx.fillStyle = t.label; ctx.fillText(text, n.x, y);
      }
    }

    // ---------- interação ----------
    function toWorld(ev) {
      const r = canvas.getBoundingClientRect(), { x, y, k } = state.view;
      return [(ev.clientX - r.left - r.width / 2 - x) / k, (ev.clientY - r.top - r.height / 2 - y) / k];
    }
    function pick(ev) {
      const [wx, wy] = toWorld(ev); let best = -1, bd = Infinity;
      for (const n of nodes) {
        if (!visible(n)) continue;
        const d = (n.x - wx) ** 2 + (n.y - wy) ** 2, rr = (n.r + 4 / state.view.k) ** 2;
        if (d < rr && d < bd) { bd = d; best = n.i; }
      }
      return best;
    }
    let last = null, moved = false;
    canvas.addEventListener('pointerdown', ev => {
      canvas.setPointerCapture(ev.pointerId); moved = false; last = [ev.clientX, ev.clientY];
      const p = pick(ev);
      if (p >= 0) { state.drag = p; nodes[p].fixed = true; reheat(); } else state.pan = true;
    });
    canvas.addEventListener('pointermove', ev => {
      if (last && (Math.abs(ev.clientX - last[0]) + Math.abs(ev.clientY - last[1]) > 3)) moved = true;
      if (state.drag >= 0) {
        const [wx, wy] = toWorld(ev); const n = nodes[state.drag]; n.x = wx; n.y = wy; reheat();
      } else if (state.pan && last) {
        state.view.x += ev.clientX - last[0]; state.view.y += ev.clientY - last[1];
        last = [ev.clientX, ev.clientY];
      } else {
        state.hover = pick(ev);
        canvas.classList.toggle('tg-pointer', state.hover >= 0);
        if (state.hover >= 0) {
          const n = nodes[state.hover];
          tip.textContent = n.title + ' · ' + KINDS[n.kind].label.replace(/s$/, '') + ' · ' + n.deg + ' conexões';
          tip.classList.remove('hidden');
          const r = container.getBoundingClientRect();
          tip.style.transform = 'translate(' + (ev.clientX - r.left + 14) + 'px,' + (ev.clientY - r.top + 14) + 'px)';
        } else tip.classList.add('hidden');
      }
    });
    canvas.addEventListener('pointerup', ev => {
      const p = state.drag;
      if (p >= 0) { nodes[p].fixed = false; if (!moved && options.onOpen) options.onOpen(nodes[p].id); }
      state.drag = -1; state.pan = false; last = null;
    });
    canvas.addEventListener('pointerleave', () => { state.hover = -1; tip.classList.add('hidden'); });
    canvas.addEventListener('wheel', ev => {
      ev.preventDefault();
      const r = canvas.getBoundingClientRect(), v = state.view;
      const mx = ev.clientX - r.left - r.width / 2, my = ev.clientY - r.top - r.height / 2;
      const k2 = Math.min(4, Math.max(0.2, v.k * Math.exp(-ev.deltaY * 0.0015)));
      v.x = mx - (mx - v.x) * (k2 / v.k); v.y = my - (my - v.y) * (k2 / v.k); v.k = k2;
    }, { passive: false });

    function fitView(animated) {
      const vis = nodes.filter(visible); if (!vis.length) return;
      const xs = vis.map(n => n.x), ys = vis.map(n => n.y);
      const w = canvas.clientWidth || 800, h = canvas.clientHeight || 600;
      const bw = Math.max(...xs) - Math.min(...xs) + 80, bh = Math.max(...ys) - Math.min(...ys) + 80;
      const k = Math.min(2, Math.max(0.2, Math.min(w / bw, h / bh)));
      const cx = (Math.max(...xs) + Math.min(...xs)) / 2, cy = (Math.max(...ys) + Math.min(...ys)) / 2;
      state.view = { x: -cx * k, y: -cy * k, k };
    }

    // ---------- loop ----------
    let raf = 0, alive = true, warm = 0;
    resize();
    for (let s = 0; s < 220; s++) tick();          // pré-aquecimento: abre já organizado
    fitView();
    function frame() {
      if (!alive) return;
      if (state.alpha > 0.002) tick();
      if (warm++ === 30) fitView();
      draw();
      raf = global.requestAnimationFrame(frame);
    }
    raf = global.requestAnimationFrame(frame);

    return { destroy() { alive = false; global.cancelAnimationFrame(raf); container.innerHTML = ''; } };

    // ---------- util ----------
    function el(tag, cls) { const e = document.createElement(tag); if (cls) e.className = cls; return e; }
    function button(text, cls) { const b = el('button', cls); b.type = 'button'; b.textContent = text; return b; }
  }
  function norm(s) { return String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim(); }

  global.TramaGraph = { mount, KINDS };
})(window);
