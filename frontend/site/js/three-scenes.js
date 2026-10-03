// The two 3D pieces: a high-rise with its MEP systems, and the India project map.
// three.js is fetched only when one of them is about to scroll into view.
(() => {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const hasGL = (() => {
    try { const c = document.createElement('canvas'); return !!(window.WebGLRenderingContext && (c.getContext('webgl') || c.getContext('experimental-webgl'))); }
    catch (e) { return false; }
  })();

  let threeP = null;
  const loadThree = () => threeP || (threeP = window.THREE ? Promise.resolve(window.THREE) : new Promise((res, rej) => {
    const s = document.createElement('script');
    s.src = 'site/js/vendor/three.min.js'; // r128, served locally so the 3D view never waits on a CDN
    s.onload = () => (window.THREE ? res(window.THREE) : rej(new Error('three.js missing')));
    s.onerror = () => rej(new Error('three.js failed to load'));
    document.head.appendChild(s);
  }));
  const whenNear = (el, fn) => {
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { io.disconnect(); fn(); } }, { rootMargin: '700px 0px' });
    io.observe(el);
  };
  // Tween a plain object with GSAP when present, otherwise jump to the end.
  const tween = (obj, to, dur, ease) => (window.gsap && !reduce ? gsap.to(obj, { ...to, duration: dur, ease: ease || 'power3.inOut' }) : Object.assign(obj, to));

  /* ---------- shared helpers ---------- */
  function kit(T) {
    const up = new T.Vector3(0, 1, 0);
    const cyl = (a, b, r) => {
      const dir = new T.Vector3().subVectors(b, a), len = dir.length();
      const g = new T.CylinderGeometry(r, r, len, 8, 1, true);
      const m = new T.Matrix4().compose(new T.Vector3().addVectors(a, b).multiplyScalar(.5), new T.Quaternion().setFromUnitVectors(up, dir.normalize()), new T.Vector3(1, 1, 1));
      return g.applyMatrix4(m);
    };
    const joint = (p, r) => new T.SphereGeometry(r * 1.02, 8, 6).translate(p.x, p.y, p.z);
    // Position-only merge, so each system on each floor is a single draw call.
    const merge = geos => {
      const arrs = geos.map(g => (g.index ? g.toNonIndexed() : g).attributes.position.array);
      const out = new Float32Array(arrs.reduce((n, a) => n + a.length, 0));
      let o = 0; arrs.forEach(a => { out.set(a, o); o += a.length; });
      return new T.BufferGeometry().setAttribute('position', new T.BufferAttribute(out, 3));
    };
    const boxSegs = (arr, x0, y0, z0, x1, y1, z1) => {
      const c = [[x0, y0, z0], [x1, y0, z0], [x1, y0, z1], [x0, y0, z1], [x0, y1, z0], [x1, y1, z0], [x1, y1, z1], [x0, y1, z1]];
      [[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4], [0, 4], [1, 5], [2, 6], [3, 7]].forEach(([a, b]) => arr.push(...c[a], ...c[b]));
    };
    const geoOf = arr => new T.BufferGeometry().setAttribute('position', new T.Float32BufferAttribute(arr, 3));
    // A polyline measured by length, so pulses travel at an even speed.
    class Poly extends T.Curve {
      constructor(pts) {
        super(); this.pts = pts; this.lens = [0];
        for (let i = 1; i < pts.length; i++) this.lens.push(this.lens[i - 1] + pts[i].distanceTo(pts[i - 1]));
        this.total = this.lens[this.lens.length - 1] || 1;
      }
      getPoint(t, target = new T.Vector3()) {
        const d = t * this.total; let i = 1;
        while (i < this.lens.length - 1 && this.lens[i] < d) i++;
        const seg = (this.lens[i] - this.lens[i - 1]) || 1;
        return target.copy(this.pts[i - 1]).lerp(this.pts[i], (d - this.lens[i - 1]) / seg);
      }
    }
    const tex = draw => { const c = document.createElement('canvas'); c.width = c.height = 64; draw(c.getContext('2d')); return new T.CanvasTexture(c); };
    const glow = tex(g => { const r = g.createRadialGradient(32, 32, 0, 32, 32, 32); r.addColorStop(0, 'rgba(255,255,255,1)'); r.addColorStop(.25, 'rgba(255,255,255,.8)'); r.addColorStop(1, 'rgba(255,255,255,0)'); g.fillStyle = r; g.fillRect(0, 0, 64, 64); });
    const disc = tex(g => { g.fillStyle = '#fff'; g.beginPath(); g.arc(32, 32, 28, 0, Math.PI * 2); g.fill(); });
    return { cyl, joint, merge, boxSegs, geoOf, Poly, glow, disc };
  }

  function makeRenderer(T, canvas) {
    const r = new T.WebGLRenderer({ canvas, antialias: true, alpha: false, powerPreference: 'high-performance' });
    r.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
    r.setClearColor(0x000000, 1);
    return r;
  }

  // Drag to turn: horizontal drags rotate, vertical ones still scroll the page on touch screens.
  function dragRotate(el, st, opts = {}) {
    let down = false, lx = 0, ly = 0, moved = 0;
    el.addEventListener('pointerdown', e => { down = true; moved = 0; lx = e.clientX; ly = e.clientY; el.setPointerCapture?.(e.pointerId); el.classList.add('grabbing'); });
    el.addEventListener('pointermove', e => {
      if (!down) return;
      const dx = e.clientX - lx, dy = e.clientY - ly; lx = e.clientX; ly = e.clientY; moved += Math.abs(dx) + Math.abs(dy);
      st.vTheta = -dx * .006; st.theta += st.vTheta; st.idle = 0;
      if (opts.tilt && e.pointerType === 'mouse') st.phi = clamp(st.phi + dy * .004, opts.tilt[0], opts.tilt[1]);
      if (opts.range) st.theta = clamp(st.theta, -opts.range, opts.range);
    });
    const end = () => { down = false; el.classList.remove('grabbing'); };
    el.addEventListener('pointerup', end); el.addEventListener('pointercancel', end); el.addEventListener('lostpointercapture', end);
    return { moved: () => moved, isDown: () => down };
  }

  /* =========================================================
     1. The building
     ========================================================= */
  function building(T, K) {
    const view = $('#stageview'), canvas = $('#bldg'), labelsEl = $('#bldglabels');
    const renderer = makeRenderer(T, canvas);
    const scene = new T.Scene(); scene.fog = new T.Fog(0x000000, 110, 230);
    const cam = new T.PerspectiveCamera(30, 1, .5, 500);
    const V = (x, y, z) => new T.Vector3(x, y, z);

    const N = 12, H = 3.2, W2 = 9, D2 = 6, TOP = N * H, B = -4.6;
    const SYS = { elec: 0x4da3ff, fire: 0xff4b3a, phe: 0x2fd3c4 };
    const mat = {}, lineMat = {}, fillMat = {}, headMat = {};
    Object.entries(SYS).forEach(([k, c]) => {
      mat[k] = new T.MeshBasicMaterial({ color: c, transparent: true });
      lineMat[k] = new T.LineBasicMaterial({ color: c, transparent: true, opacity: .5 });
      fillMat[k] = new T.MeshBasicMaterial({ color: c, transparent: true, opacity: .14, depthWrite: false });
      headMat[k] = new T.PointsMaterial({ color: c, size: .32, map: K.disc, transparent: true, alphaTest: .4 });
    });
    const structMat = new T.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: .22 });
    const faintMat = new T.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: .07 });
    const slabMat = new T.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: .035, depthWrite: false, side: T.DoubleSide });

    const groups = [], flows = [], floors = [];
    const G = (kind, index) => {
      const g = new T.Group();
      g.userData = { kind, index, pipes: { elec: [], fire: [], phe: [] }, lines: { struct: [], faint: [], elec: [], fire: [], phe: [] }, fills: [], heads: { fire: [] } };
      scene.add(g); groups.push(g); return g;
    };
    const pipe = (g, sys, pts, r, speed, sync) => {
      const v = pts.map(p => V(...p)), list = g.userData.pipes[sys];
      for (let i = 1; i < v.length; i++) list.push(K.cyl(v[i - 1], v[i], r));
      for (let i = 1; i < v.length - 1; i++) list.push(K.joint(v[i], r));
      if (!speed) return;
      const c = new K.Poly(v), n = Math.max(1, Math.round(c.total / 7));
      // Riser segments share one phase so the pulses read as one continuous train up the shaft.
      for (let k = 0; k < n; k++) flows.push({ g, sys, c, speed, ph: sync ? 0 : k / n + Math.random() * .3 });
    };
    const box = (g, set, x0, y0, z0, x1, y1, z1, fill) => { K.boxSegs(g.userData.lines[set], x0, y0, z0, x1, y1, z1); if (fill) g.userData.fills.push([fill, x0, y0, z0, x1, y1, z1]); };
    const finalize = g => {
      const u = g.userData;
      Object.keys(SYS).forEach(k => {
        if (u.pipes[k].length) g.add(new T.Mesh(K.merge(u.pipes[k]), mat[k]));
        if (u.lines[k].length) g.add(new T.LineSegments(K.geoOf(u.lines[k]), lineMat[k]));
      });
      if (u.heads.fire.length) g.add(new T.Points(K.geoOf(u.heads.fire), headMat.fire));
      if (u.lines.struct.length) g.add(new T.LineSegments(K.geoOf(u.lines.struct), structMat));
      if (u.lines.faint.length) g.add(new T.LineSegments(K.geoOf(u.lines.faint), faintMat));
      u.fills.forEach(([k, x0, y0, z0, x1, y1, z1]) => {
        const m = new T.Mesh(new T.BoxGeometry(x1 - x0, y1 - y0, z1 - z0), k === 'slab' ? slabMat : fillMat[k]);
        m.position.set((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2); g.add(m);
      });
    };

    // Typical floors
    for (let i = 0; i < N; i++) {
      const g = G('floor', i), y0 = i * H, y1 = y0 + H, hc = y1 - .45, hs = hc - .45, hw = y0 + .35, f = g.userData.lines.faint;
      floors.push(g);
      box(g, 'struct', -W2, y0, -D2, W2, y0 + .18, D2, 'slab');
      box(g, 'struct', -1.5, y0 + .18, -1.5, 1.5, y1, 1.5);
      for (let x = -W2; x <= W2 + .01; x += 1.5) f.push(x, y0, -D2, x, y1, -D2, x, y0, D2, x, y1, D2);
      for (let z = -D2 + 1.5; z < D2 - .01; z += 1.5) f.push(-W2, y0, z, -W2, y1, z, W2, y0, z, W2, y1, z);
      // electrical: busduct segment, trays at ceiling, floor DB
      pipe(g, 'elec', [[1, y0, 1], [1, y1, 1]], .22, 7, true);
      pipe(g, 'elec', [[1, hc, 1], [1, hc, -4.6], [7.8, hc, -4.6], [7.8, hc, 4.6], [2.4, hc, 4.6]], .09, 6);
      pipe(g, 'elec', [[1, hc, -4.6], [-7.8, hc, -4.6], [-7.8, hc, 1.6]], .09, 6);
      box(g, 'elec', 1.7, y0 + .4, .3, 2.3, y0 + 1.9, 1.5, 'elec');
      // fire: wet riser segment, mains, sprinkler branches and heads
      pipe(g, 'fire', [[-1, y0, -1], [-1, y1, -1]], .2, 6, true);
      pipe(g, 'fire', [[-1, hs, -1], [-1, hs, -3], [-8.2, hs, -3]], .1, 5);
      pipe(g, 'fire', [[-1, hs, -3], [8.2, hs, -3]], .1, 5);
      [-7, -5, -3, 3, 5, 7].forEach(x => {
        g.userData.lines.fire.push(x, hs, -3, x, hs, 5.2);
        for (let z = -1.3; z <= 5.2; z += 1.6) g.userData.heads.fire.push(x, hs - .12, z);
      });
      // plumbing: supply riser down, branch to wet areas, drainage stack down
      pipe(g, 'phe', [[-1, y1, 1], [-1, y0, 1]], .17, 5, true);
      pipe(g, 'phe', [[-1, hw, 1], [-1, hw, 4.8], [-6.2, hw, 4.8]], .08, 4);
      pipe(g, 'phe', [[-6.9, y1, 5.3], [-6.9, y0, 5.3]], .22, 3.5, true);
      box(g, 'phe', -6.3, y0 + .18, 3.9, -4.5, y0 + .9, 5.6, 'phe');
      finalize(g);
    }

    // Roof: slab, parapet, lift room, overhead tank
    const roof = G('roof', N);
    box(roof, 'struct', -W2, TOP, -D2, W2, TOP + .18, D2, 'slab');
    box(roof, 'faint', -W2, TOP + .18, -D2, W2, TOP + 1.1, D2);
    box(roof, 'struct', -1.5, TOP + .18, -1.5, 1.5, TOP + 3, 1.5);
    box(roof, 'phe', -5.4, TOP + .18, 1.6, -2.2, TOP + 2.6, 4.8, 'phe');
    pipe(roof, 'phe', [[-2.2, TOP + .6, 3], [-1, TOP + .6, 3], [-1, TOP + .6, 1], [-1, TOP, 1]], .17, 4);
    finalize(roof);

    // Basement: LT panel room, fire tank and pumps, STP
    const base = G('base', -1);
    box(base, 'struct', -W2, B, -D2, W2, B + .18, D2, 'slab');
    box(base, 'faint', -W2, B, -D2, W2, 0, D2);
    for (let k = 0; k < 4; k++) box(base, 'elec', 3.4 + k * 1.05, B + .18, 3.6, 4.3 + k * 1.05, B + 2.3, 4.4, 'elec');
    pipe(base, 'elec', [[12.2, .1, 4.6], [12.2, -2.6, 4.6], [7.6, -2.6, 4.6], [7.6, -2.6, 4]], .16, 6);
    pipe(base, 'elec', [[3.4, -2.6, 4], [1, -2.6, 4], [1, -2.6, 1], [1, 0, 1]], .22, 7);
    box(base, 'fire', -8.6, B + .18, -5.6, -4.2, -1.2, -1.6, 'fire');
    [-4.8, -3.8, -2.8].forEach(z => pipe(base, 'fire', [[-3.8, B + .8, z], [-2.5, B + .8, z]], .34));
    pipe(base, 'fire', [[-4.2, B + .8, -3.8], [-3.8, B + .8, -3.8]], .14);
    pipe(base, 'fire', [[-2.5, B + .8, -3.8], [-1, B + .8, -3.8], [-1, B + .8, -1], [-1, 0, -1]], .2, 6);
    pipe(base, 'fire', [[-2.5, B + .8, -4.8], [-2.5, B + .8, -8.5], [-2.5, -.3, -8.5]], .14, 4);
    box(base, 'phe', -8.6, B + .18, 2, -5.8, B + 2.4, 5.6, 'phe');
    pipe(base, 'phe', [[-6.9, 0, 5.3], [-6.9, -2, 5.3], [-7.2, -2, 4.6]], .22, 3.5);
    finalize(base);

    // Site: ground grid, transformer yard, HT line, hydrant ring main
    const site = G('site', 0), gl = site.userData.lines.faint, P = 21;
    for (let x = -30; x <= 36; x += 3) (Math.abs(x) < W2 ? [[-26, -D2], [D2, 26]] : [[-26, 26]]).forEach(([a, b]) => gl.push(x, 0, a, x, 0, b));
    for (let z = -24; z <= 24; z += 3) (Math.abs(z) < D2 ? [[-32, -W2], [W2, 38]] : [[-32, 38]]).forEach(([a, b]) => gl.push(a, 0, z, b, 0, z));
    box(site, 'elec', 11, 0, 3.2, 13.4, 2.4, 5.6, 'elec');
    box(site, 'faint', 9.8, 0, 1.8, 15, 2.2, 7);
    const sl = site.userData.lines.struct;
    sl.push(P, 0, 4.4, P, 9, 4.4, P - 1.6, 8.2, 4.4, P + 1.6, 8.2, 4.4, P - 1, 0, 4.4, P, 5, 4.4, P + 1, 0, 4.4, P, 5, 4.4);
    pipe(site, 'elec', [[P + 9, 9.6, 4.4], [P, 8.2, 4.4], [17, 5.8, 4.4], [13.4, 2.4, 4.4]], .07, 8);
    const ring = [[-12, -.3, -8.5], [13, -.3, -8.5], [13, -.3, 8.5], [-12, -.3, 8.5], [-12, -.3, -8.5]];
    pipe(site, 'fire', ring, .14, 4);
    [[-12, -8.5], [0.5, -8.5], [13, -8.5], [13, 0], [13, 8.5], [0.5, 8.5], [-12, 8.5], [-12, 0]].forEach(([x, z]) => pipe(site, 'fire', [[x, -.3, z], [x, 1.1, z]], .22));
    finalize(site);

    // Flow pulses: one glowing point cloud per system
    const pulses = {};
    Object.keys(SYS).forEach(k => {
      const list = flows.filter(f => f.sys === k);
      const geo = new T.BufferGeometry().setAttribute('position', new T.BufferAttribute(new Float32Array(list.length * 3), 3));
      const pm = new T.PointsMaterial({ color: SYS[k], size: 1.5, map: K.glow, transparent: true, depthWrite: false, blending: T.AdditiveBlending });
      const pts = new T.Points(geo, pm); pts.frustumCulled = false; scene.add(pts);
      pulses[k] = { list, geo, pm, pts };
    });

    // Labels anchored to parts of the model
    const L = (sys, g, p, t, main) => ({ sys, g, p: V(...p), t, main });
    const labels = [
      L('elec', site, [P, 9.4, 4.4], 'HT Incomer'),
      L('elec', site, [12.2, 2.9, 4.4], 'Transformer'),
      L('elec', base, [5.5, -2, 4], 'LT Panels'),
      L('elec', floors[6], [1, 6 * H + 1.6, 1], 'Rising Busduct', true),
      L('elec', floors[10], [7.8, 11 * H - .45, 0], 'Cable Trays & Floor DBs'),
      L('fire', base, [-6.4, -1, -3.6], 'Fire Water Tank'),
      L('fire', base, [-3.1, B + 1.4, -3.8], 'Fire Pumps'),
      L('fire', floors[9], [-1, 9 * H + 1.6, -1], 'Wet Riser', true),
      L('fire', floors[11], [-7, 12 * H - .9, 2], 'Sprinkler Network'),
      L('fire', site, [13, 1.2, -8.5], 'Hydrant Ring Main'),
      L('phe', roof, [-3.8, TOP + 2.8, 3.2], 'Overhead Tank', true),
      L('phe', floors[3], [-1, 3 * H + 1.6, 1], 'Water Supply Riser'),
      L('phe', floors[2], [-6.9, 2 * H + 1.6, 5.3], 'Drainage Stack'),
      L('phe', base, [-7.2, -2, 3.8], 'Sewage Treatment')
    ];
    labelsEl.innerHTML = labels.map(l => `<div class="lab lab--${l.sys}"><i></i><span>${l.t}</span></div>`).join('');
    const labEls = $$('.lab', labelsEl);

    // State
    const st = { theta: .7, phi: .34, vTheta: 0, idle: 0, radius: 95, explode: 0, build: reduce ? 1 : 0, sys: 'all', alpha: { elec: 1, fire: 1, phe: 1 } };
    const drag = dragRotate(canvas, st, { tilt: [.06, .9] });
    view.addEventListener('keydown', e => {
      if (e.key === 'ArrowLeft') { st.theta += .25; st.idle = 0; e.preventDefault(); }
      if (e.key === 'ArrowRight') { st.theta -= .25; st.idle = 0; e.preventDefault(); }
    });

    const INFO = {
      all: ['All Systems', 'A typical high-rise with every system we install. Select one to trace it from source to outlet.'],
      elec: ['Electrical', 'From the utility HT incomer through the transformer and LT panels, up the rising busduct to distribution boards and cable trays on every floor.', 'electrical'],
      fire: ['Fire Protection', 'Fire water storage and pumps feed a wet riser, a sprinkler network on every floor and a hydrant ring main around the site.', 'fire'],
      phe: ['Plumbing', 'An overhead tank feeds supply risers to every floor, while drainage stacks carry waste down to the sewage treatment plant.', 'phe']
    };
    const addBtn = $('#sysadd');
    const syncAdd = () => {
      const scope = INFO[st.sys][2];
      addBtn.hidden = !scope || !window.YQuote;
      if (scope && window.YQuote) addBtn.textContent = window.YQuote.has(scope) ? `${INFO[st.sys][0]} Added to Quote ✓` : `Add ${INFO[st.sys][0]} to Quote +`;
    };
    function setSys(s) {
      st.sys = s;
      $$('#sysbtns button').forEach(b => b.setAttribute('aria-pressed', b.dataset.sys === s));
      $('#sysk').textContent = INFO[s][0]; $('#sysd').textContent = INFO[s][1];
      view.dataset.sys = s; syncAdd();
    }
    $('#sysbtns').addEventListener('click', e => { const b = e.target.closest('button[data-sys]'); if (b) setSys(b.dataset.sys); });
    addBtn.addEventListener('click', () => { const scope = INFO[st.sys][2]; if (scope && window.YQuote) window.YQuote.toggle(scope); });
    document.addEventListener('quote:change', syncAdd);
    const exBtn = $('#explode');
    exBtn.addEventListener('click', () => {
      const on = exBtn.getAttribute('aria-pressed') !== 'true';
      exBtn.setAttribute('aria-pressed', on);
      tween(st, { explode: on ? 1 : 0 }, 1.3);
    });

    let vw = 1, vh = 1;
    function resize() {
      const w = view.clientWidth, h = view.clientHeight; if (!w || !h) return;
      vw = w; vh = h;
      renderer.setSize(w, h, false); cam.aspect = w / h; cam.updateProjectionMatrix();
      const a = w / h; st.radius = a < .75 ? 165 : a < 1.15 ? 128 : 98;
    }
    new ResizeObserver(resize).observe(view); resize();

    let visible = false, started = false, time = 0, last = performance.now();
    new IntersectionObserver(([e]) => {
      visible = e.isIntersecting;
      if (visible && !started) { started = true; if (!reduce) tween(st, { build: 1 }, 3.2, 'none'); }
    }, { threshold: .2 }).observe(view);

    const tmp = V(0, 0, 0), wp = V(0, 0, 0), target = V(3, 15, 0);
    (function frame(now) {
      requestAnimationFrame(frame);
      if (!visible) { last = now; return; }
      const dt = Math.min(.05, (now - last) / 1000); last = now;
      if (!reduce) time += dt;
      if (!drag.isDown()) {
        st.idle += dt; st.theta += st.vTheta; st.vTheta *= .92;
        if (!reduce && st.idle > 2.5) st.theta += dt * .08;
      }
      // floors drop into place one after another, and spread apart in exploded view
      groups.forEach(g => {
        const u = g.userData;
        const lift = u.kind === 'floor' ? (u.index + 1) * 1.8 : u.kind === 'roof' ? (N + 1) * 1.8 : u.kind === 'base' ? -2.8 : 0;
        const order = u.kind === 'floor' ? u.index + 1 : u.kind === 'roof' ? N + 1 : 0;
        const l = clamp((st.build - order * .05) / .3, 0, 1), e = 1 - Math.pow(1 - l, 3);
        g.visible = l > 0; g.userData.shown = l;
        g.position.y = st.explode * lift + (1 - e) * 18;
      });
      // dim the systems that are not selected
      Object.keys(SYS).forEach(k => {
        const want = st.sys === 'all' || st.sys === k ? 1 : .07;
        const a = st.alpha[k] += (want - st.alpha[k]) * Math.min(1, dt * 7);
        mat[k].opacity = a; lineMat[k].opacity = .5 * a; fillMat[k].opacity = .14 * a; headMat[k].opacity = a;
        const p = pulses[k]; p.pm.opacity = a; p.pts.visible = a > .12;
        const arr = p.geo.attributes.position.array;
        p.list.forEach((f, i) => {
          if (!f.g.visible) { arr[i * 3 + 1] = -999; return; }
          f.c.getPoint(((f.ph + time * f.speed / f.c.total) % 1 + 1) % 1, tmp);
          arr[i * 3] = tmp.x; arr[i * 3 + 1] = tmp.y + f.g.position.y; arr[i * 3 + 2] = tmp.z;
        });
        p.geo.attributes.position.needsUpdate = true;
      });
      const r = st.radius * (1 + st.explode * .55);
      target.y = 16 + st.explode * 14;
      cam.position.set(target.x + r * Math.cos(st.phi) * Math.sin(st.theta), target.y + r * Math.sin(st.phi), r * Math.cos(st.phi) * Math.cos(st.theta));
      cam.lookAt(target);
      renderer.render(scene, cam);
      // labels follow their anchors on screen
      const w = vw, h = vh;
      labels.forEach((l, i) => {
        const el = labEls[i], show = l.g.visible && l.g.userData.shown > .9 && (st.sys === 'all' ? l.main : l.sys === st.sys);
        wp.copy(l.p); wp.y += l.g.position.y; wp.project(cam);
        const on = !!(show && wp.z < 1 && Math.abs(wp.x) < 1.05 && Math.abs(wp.y) < 1.05);
        el.classList.toggle('on', on);
        if (on) el.style.transform = `translate3d(${((wp.x + 1) / 2 * w).toFixed(1)}px,${((1 - wp.y) / 2 * h).toFixed(1)}px,0)`;
      });
    })(last);
    view.classList.add('ready');
    setSys('all');
  }

  /* =========================================================
     2. The India map, with a column of light per city
     ========================================================= */
  function map3d(T, K) {
    const A = window.YAtlas; if (!A) return;
    const box = $('#map3dwrap'), canvas = $('#map3d'), labelsEl = $('#maplabels'), mapEl = $('.atlas__map'), tip = $('#maptip');
    mapEl.classList.add('is3d');
    const renderer = makeRenderer(T, canvas);
    const scene = new T.Scene();
    const cam = new T.PerspectiveCamera(30, 1, 1, 600);
    const to3 = ([px, py]) => [(px - 300) / 10, (py - 340) / 10];

    const dp = []; A.dots.forEach(d => { const [x, z] = to3(d); dp.push(x, 0, z); });
    scene.add(new T.Points(K.geoOf(dp), new T.PointsMaterial({ color: 0x5a5a64, size: .5, map: K.disc, transparent: true, alphaTest: .4 })));

    // vertical fade: bright at the base, dim at the top
    const grad = (() => { const c = document.createElement('canvas'); c.width = 4; c.height = 128; const g = c.getContext('2d'); const l = g.createLinearGradient(0, 0, 0, 128); l.addColorStop(0, '#2a2a2e'); l.addColorStop(1, '#ffffff'); g.fillStyle = l; g.fillRect(0, 0, 4, 128); return new T.CanvasTexture(c); })();
    const COL = { hq: 0x2b95ff, br: 0xf2f2f2, site: 0x8e8e96 };
    const hits = [];
    const cols = A.places.map((pl, i) => {
      const [x, z] = to3(A.proj(pl.p)), n = A.counts[i];
      const h = (pl.k === 'hq' ? 2 : pl.k === 'br' ? 1.2 : .8) + Math.sqrt(n) * 2.3;
      const r = pl.k === 'hq' ? .6 : pl.k === 'br' ? .45 : .32;
      const m = new T.Mesh(new T.CylinderGeometry(r, r, h, 24).translate(0, h / 2, 0), new T.MeshBasicMaterial({ color: COL[pl.k], map: grad }));
      m.position.set(x, 0, z); scene.add(m);
      const ring = new T.Mesh(new T.RingGeometry(r * 1.8, r * 2.4, 40), new T.MeshBasicMaterial({ color: COL[pl.k], transparent: true, opacity: .45, side: T.DoubleSide, depthWrite: false }));
      ring.rotation.x = -Math.PI / 2; ring.position.set(x, .03, z); scene.add(ring);
      const hit = new T.Mesh(new T.CylinderGeometry(1.4, 1.4, h + 2, 8).translate(0, (h + 2) / 2, 0), new T.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false, colorWrite: false }));
      hit.position.set(x, 0, z); hit.userData.i = i; scene.add(hit); hits.push(hit);
      return { m, ring, h, x, z, pl, n, grow: reduce ? 1 : 0 };
    });

    // arcs from Hyderabad to each branch, with pulses running out along them
    const hq = cols[0], arcs = [];
    cols.forEach(c => {
      if (c.pl.k !== 'br') return;
      const d = Math.hypot(c.x - hq.x, c.z - hq.z);
      const curve = new T.QuadraticBezierCurve3(new T.Vector3(hq.x, .1, hq.z), new T.Vector3((c.x + hq.x) / 2, d * .38, (c.z + hq.z) / 2), new T.Vector3(c.x, .1, c.z));
      scene.add(new T.Line(new T.BufferGeometry().setFromPoints(curve.getPoints(60)), new T.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: .22 })));
      arcs.push(curve);
    });
    const pg = new T.BufferGeometry().setAttribute('position', new T.BufferAttribute(new Float32Array(arcs.length * 2 * 3), 3));
    const pp = new T.Points(pg, new T.PointsMaterial({ color: 0x9fd0ff, size: 1.6, map: K.glow, transparent: true, depthWrite: false, blending: T.AdditiveBlending }));
    pp.frustumCulled = false; scene.add(pp);

    // name tags for the office cities, and one floating tag for the hovered column
    labelsEl.innerHTML = cols.map(c => `<div class="mlab${c.pl.k === 'site' ? ' mlab--site' : ''}${c.pl.n === 'Bengaluru' || c.pl.n === 'Hyderabad' ? ' mlab--left' : c.pl.n === 'Chennai' ? ' mlab--right' : ''}"><b>${c.pl.n}</b>${c.n ? `<span>${c.n} project${c.n > 1 ? 's' : ''}</span>` : ''}</div>`).join('');
    const tags = $$('.mlab', labelsEl);

    const st = { theta: 0, phi: 1.12, vTheta: 0, idle: 0, radius: 112 };
    const drag = dragRotate(canvas, st, { range: .75 });
    let hover = -1, sel = null, focusIdx = -1;
    A.onChange(i => { sel = i; });

    const ray = new T.Raycaster(), ndc = new T.Vector2();
    const pickAt = e => {
      const r = canvas.getBoundingClientRect();
      ndc.set((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1);
      ray.setFromCamera(ndc, cam);
      const hit = ray.intersectObjects(hits)[0];
      return hit ? hit.object.userData.i : -1;
    };
    canvas.addEventListener('pointermove', e => { if (drag.isDown()) return; hover = pickAt(e); canvas.style.cursor = hover >= 0 ? 'pointer' : ''; });
    canvas.addEventListener('pointerleave', () => { hover = -1; });
    canvas.addEventListener('click', e => { if (drag.moved() > 6) return; const i = pickAt(e); if (i >= 0) A.pick(i); });
    box.addEventListener('keydown', e => {
      const n = cols.length;
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { focusIdx = (focusIdx + 1) % n; e.preventDefault(); }
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { focusIdx = (focusIdx - 1 + n) % n; e.preventDefault(); }
      else if ((e.key === 'Enter' || e.key === ' ') && focusIdx >= 0) { A.pick(focusIdx); e.preventDefault(); return; }
      else if (e.key === 'Escape') { A.clear(); return; }
      else return;
      const c = cols[focusIdx]; tip.innerHTML = `<b>${c.pl.n}</b> — ${c.pl.note}. Press Enter to filter.`;
    });
    box.addEventListener('blur', () => { focusIdx = -1; });

    let bw = 1, bh = 1;
    function resize() {
      const w = box.clientWidth, h = box.clientHeight; if (!w || !h) return;
      bw = w; bh = h;
      renderer.setSize(w, h, false); cam.aspect = w / h; cam.updateProjectionMatrix();
      st.radius = w / h < .8 ? 128 : 112;
    }
    new ResizeObserver(resize).observe(box); resize();

    let visible = false, started = false, time = 0, last = performance.now();
    new IntersectionObserver(([e]) => {
      visible = e.isIntersecting;
      if (visible && !started) { started = true; cols.forEach((c, i) => { if (!reduce) setTimeout(() => tween(c, { grow: 1 }, 1.4, 'expo.out'), 120 + i * 60); }); }
    }, { threshold: .2 }).observe(box);

    const tv = new T.Vector3(), tp = new T.Vector3(), target = new T.Vector3(0, 0, 1.5);
    (function frame(now) {
      requestAnimationFrame(frame);
      if (!visible) { last = now; return; }
      const dt = Math.min(.05, (now - last) / 1000); last = now;
      if (!reduce) time += dt;
      if (!drag.isDown()) {
        st.idle += dt; st.theta += st.vTheta; st.vTheta *= .9;
        if (!reduce && st.idle > 2) st.theta += (Math.sin(time * .25) * .22 - st.theta) * dt * .6;
      }
      cam.position.set(target.x + st.radius * Math.cos(st.phi) * Math.sin(st.theta), st.radius * Math.sin(st.phi), target.z + st.radius * Math.cos(st.phi) * Math.cos(st.theta));
      cam.lookAt(target);
      const active = hover >= 0 ? hover : focusIdx;
      cols.forEach((c, i) => {
        const on = i === active || i === sel;
        c.m.scale.y = Math.max(.001, c.grow);
        c.m.material.color.setHex(on ? 0xffffff : COL[c.pl.k]);
        const pulse = c.pl.k === 'site' ? 1 : 1 + ((time * .6 + i * .17) % 1) * .8;
        c.ring.scale.setScalar(on ? 1.6 : pulse);
        c.ring.material.opacity = on ? .9 : c.pl.k === 'site' ? .3 : .5 * (1 - ((time * .6 + i * .17) % 1) * .8);
      });
      const arr = pg.attributes.position.array;
      arcs.forEach((a, i) => [0, .5].forEach((o, k) => { a.getPoint((time * .35 + o + i * .13) % 1, tp); arr.set([tp.x, tp.y, tp.z], (i * 2 + k) * 3); }));
      pg.attributes.position.needsUpdate = true;
      renderer.render(scene, cam);
      const w = bw, h = bh;
      cols.forEach((c, i) => {
        const el = tags[i], show = c.pl.k !== 'site' || i === active || i === sel;
        tv.set(c.x, c.h * c.grow + 1.2, c.z).project(cam);
        const on = !!(show && c.grow > .6 && tv.z < 1);
        el.classList.toggle('on', on);
        el.classList.toggle('hot', i === active || i === sel);
        if (on) el.style.transform = `translate3d(${((tv.x + 1) / 2 * w).toFixed(1)}px,${((1 - tv.y) / 2 * h).toFixed(1)}px,0)`;
      });
    })(last);
    mapEl.classList.add('is3d');
  }

  /* ---------- boot ---------- */
  const stage = $('#stageview'), mapBox = $('#map3dwrap');
  if (!hasGL) { stage && stage.classList.add('nogl'); return; }
  // Watch a visible element: the map canvas stays display:none until its scene is running.
  const start = (watch, el, fn) => el && whenNear(watch, () => loadThree().then(T => fn(T, kit(T))).catch(err => { console.warn('3D view unavailable:', err.message); el.classList.add('nogl'); }));
  start(stage, stage, building);
  start($('.atlas__map'), mapBox, map3d);
})();
