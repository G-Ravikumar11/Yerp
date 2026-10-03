(() => {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const S = window.SITE, P = window.PROJECTS || [];
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const G = window.gsap && !reduce ? window.gsap : null;
  if (G && window.ScrollTrigger) G.registerPlugin(ScrollTrigger);
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const inr = n => new Intl.NumberFormat('en-IN').format(Math.round(n));
  $('#yr').textContent = new Date().getFullYear();

  const toastEl = $('#toast'); let toastT;
  const toast = m => { toastEl.textContent = m; toastEl.classList.add('on'); clearTimeout(toastT); toastT = setTimeout(() => toastEl.classList.remove('on'), 2400); };

  /* ---------- scrolling ---------- */
  // Native scrolling: no scroll-smoothing library, so trackpads, sticky and pinned sections behave normally.
  const nav = $('#nav'), burger = $('#burger');
  const closeMenu = () => { nav.classList.remove('open'); burger.setAttribute('aria-expanded', 'false'); burger.setAttribute('aria-label', 'Open menu'); };
  document.addEventListener('click', e => {
    const a = e.target.closest('a[href^="#"]'); if (!a) return;
    const id = a.getAttribute('href'), el = id.length > 1 && $(id); if (!el) return;
    e.preventDefault(); closeMenu();
    if (id === '#top') scrollTo({ top: 0, behavior: reduce ? 'auto' : 'smooth' });
    else el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
    history.replaceState(null, '', id === '#top' ? location.pathname : id);
  });
  burger.addEventListener('click', () => {
    const open = nav.classList.toggle('open');
    burger.setAttribute('aria-expanded', open); burger.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
  });
  addEventListener('keydown', e => { if (e.key === 'Escape') closeMenu(); });

  let lastY = 0;
  addEventListener('scroll', () => {
    const y = scrollY, heroH = innerHeight * .85;
    nav.classList.toggle('solid', y > heroH - 80);
    if (!nav.classList.contains('open')) nav.classList.toggle('hide', y > heroH && y > lastY + 4);
    if (y < lastY - 4) nav.classList.remove('hide');
    lastY = y;
    const max = document.documentElement.scrollHeight - innerHeight;
    nav.style.setProperty('--p', max > 0 ? (y / max).toFixed(4) : 0);
  }, { passive: true });
  const navLinks = new Map($$('#navlinks a').map(a => [a.getAttribute('href').slice(1), a]));
  const navIO = new IntersectionObserver(es => es.forEach(e => {
    if (!e.isIntersecting) return;
    navLinks.forEach(a => { a.classList.remove('active'); a.removeAttribute('aria-current'); });
    const a = navLinks.get(e.target.id); if (a) { a.classList.add('active'); a.setAttribute('aria-current', 'true'); }
  }), { rootMargin: '-45% 0px -50% 0px' });
  ['capabilities', 'work', 'projects', 'clients', 'company', 'quote', 'contact'].forEach(id => navIO.observe(document.getElementById(id)));

  /* ---------- hero chapters ---------- */
  (function hero() {
    const box = $('#slides'), chaps = $('#chapters'), DUR = 7000;
    box.innerHTML = S.slides.map((s, i) => `<div class="slide${i ? '' : ' on'}"><img src="${s.img}" alt="${esc(s.t)}" ${i ? 'loading="lazy"' : 'fetchpriority="high"'}></div>`).join('');
    chaps.innerHTML = S.slides.map((s, i) => `<button class="chap" role="tab" aria-selected="${!i}" data-i="${i}"><b>${esc(s.t)}</b><small>${esc(s.l)}</small></button>`).join('');
    const slides = $$('.slide', box), btns = $$('.chap', chaps);
    let cur = 0, t0 = performance.now(), paused = reduce, visible = true;
    function go(i) {
      cur = (i + slides.length) % slides.length; t0 = performance.now();
      slides.forEach((s, k) => s.classList.toggle('on', k === cur));
      btns.forEach((b, k) => { b.setAttribute('aria-selected', k === cur); b.style.setProperty('--p', k < cur ? 1 : 0); });
    }
    btns.forEach(b => b.addEventListener('click', () => go(+b.dataset.i)));
    new IntersectionObserver(([e]) => visible = e.isIntersecting).observe(box);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) t0 = performance.now() - (btns[cur].style.getPropertyValue('--p') || 0) * DUR; });
    (function tick(now) {
      requestAnimationFrame(tick);
      if (paused || !visible || document.hidden) { t0 = now - (+btns[cur].style.getPropertyValue('--p') || 0) * DUR; return; }
      const p = Math.min(1, (now - t0) / DUR);
      btns[cur].style.setProperty('--p', p);
      if (p >= 1) go(cur + 1);
    })(performance.now());
    if (reduce) btns[0].style.setProperty('--p', 1);
    if (G) G.from(['.hero__title', '.hero__sub', '.hero__cta', '.hero__chapters'], { opacity: 0, y: 30, duration: 1.2, stagger: .12, ease: 'expo.out', delay: .1 });
  })();

  /* ---------- counters ---------- */
  function countUp(el) {
    const to = +el.dataset.count, pre = el.dataset.prefix || '', suf = el.dataset.suffix || '', t0 = performance.now(), d = reduce ? 1 : 1600;
    (function f(now) { const p = Math.min(1, (now - t0) / d); el.textContent = pre + inr(to * (1 - Math.pow(1 - p, 4))) + suf; if (p < 1) requestAnimationFrame(f); })(t0);
  }
  const cio = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { cio.unobserve(e.target); countUp(e.target); } }), { threshold: .6 });
  $$('[data-count]').forEach(el => cio.observe(el));

  /* ---------- client logos ---------- */
  // White, background-free versions made from the original logo files (img/clients-mono).
  const CLIENTS = [['c27', 'L&T'], ['c46', 'Shapoorji Pallonji'], ['c31', 'NCC'], ['c18', 'My Home Group'], ['c19', 'Hyderabad Metro Rail'], ['c17', 'Punj Lloyd'],
    ['c28', 'IL&FS'], ['c32', 'Lanco'], ['c26', 'PVR Cinemas'], ['c33', 'APCRDA'], ['c34', 'APTIDCO'], ['c16', 'L&T Infotech'],
    ['c22', 'L&T Infocity'], ['c29', 'Vestian'], ['c20', 'Cybercity Builders'], ['c37', 'Indu Projects'], ['c44', 'Preston Developers'], ['c42', 'Navayuga'],
    ['c39', 'Marina Skies'], ['c41', 'Myscape'], ['c35', 'Garden City Realty'], ['c25', 'Safeway Symphony'], ['c49', 'Western Constructions'], ['c48', 'True Build Products']];
  $('#logos').innerHTML = CLIENTS.map(([f, n]) => `<li><img src="site/img/clients-mono/${f}.png" alt="${esc(n)}" loading="lazy" decoding="async"></li>`).join('');

  /* ---------- planner state (capabilities feed it) ---------- */
  const plan = { type: null, scopes: new Set(), size: 40, city: '', stage: null };
  const scopeLabel = id => S.plan.scopes.find(s => s.id === id).label;

  /* ---------- capabilities ---------- */
  (function capabilities() {
    const list = $('#caps'), frame = $('#capsframe');
    const scopeOf = { electrical: 'electrical', fire: 'fire', panels: 'panels', phe: 'phe', testing: 'testing' };
    frame.innerHTML = S.services.map((s, i) => `<img src="${s.img}" alt="" loading="lazy"${i ? '' : ' class="on"'}>`).join('');
    list.innerHTML = S.services.map((s, i) => `
      <li class="cap${i ? '' : ' on'}" data-i="${i}">
        <div class="cap__head"><span class="cap__n">0${i + 1}</span><h3>${esc(s.title)}</h3><span class="cap__tag">${esc(s.tag)}</span></div>
        <img class="cap__img" src="${s.img}" alt="" loading="lazy">
        <div class="cap__body">
          <p>${esc(s.intro)}</p>
          <ul>${s.list.slice(0, 8).map(x => `<li>${esc(x)}</li>`).join('')}</ul>
          ${scopeOf[s.id] ? `<button class="cap__add" type="button" data-scope="${scopeOf[s.id]}" aria-pressed="false">Add to Quote +</button>` : `<a class="cap__add" href="#quote">Start a Quote →</a>`}
        </div>
      </li>`).join('');
    const items = $$('.cap', list), imgs = $$('img', frame);
    const set = i => { items.forEach((it, k) => it.classList.toggle('on', k === i)); imgs.forEach((im, k) => im.classList.toggle('on', k === i)); };
    const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) set(+e.target.dataset.i); }), { rootMargin: '-45% 0px -45% 0px' });
    items.forEach(it => io.observe(it));
    list.addEventListener('click', e => { const b = e.target.closest('.cap__add[data-scope]'); if (b) toggleScope(b.dataset.scope); });
  })();
  function syncScopeButtons() {
    $$('.cap__add[data-scope]').forEach(b => { const on = plan.scopes.has(b.dataset.scope); b.setAttribute('aria-pressed', on); b.textContent = on ? 'Added to Quote ✓' : 'Add to Quote +'; });
    document.dispatchEvent(new CustomEvent('quote:change'));
  }
  function toggleScope(id) {
    const on = !plan.scopes.has(id); on ? plan.scopes.add(id) : plan.scopes.delete(id);
    const cb = $(`#qscope input[value="${id}"]`); if (cb) cb.checked = on;
    syncScopeButtons(); renderBrief();
    toast(on ? `${scopeLabel(id)} added to your quote` : `${scopeLabel(id)} removed from your quote`);
  }
  window.YQuote = { toggle: toggleScope, has: id => plan.scopes.has(id) };

  /* ---------- selected work ---------- */
  $('#cases').innerHTML = S.featured.map((c, i) => `
    <article class="case">
      <img src="${c.img}" alt="${esc(c.t)}" loading="lazy">
      <div class="wrap case__body">
        <div><p class="case__n">0${i + 1} / 0${S.featured.length}</p><h3>${esc(c.t)}</h3><p>${esc(c.d)}</p></div>
        <div class="case__meta">${c.meta.map(m => `<span>${esc(m)}</span>`).join('')}</div>
      </div>
    </article>`).join('');

  /* ---------- project index ---------- */
  const explorer = (function () {
    const cats = ['All', 'Commercial', 'Residential', 'Industrial', 'IT & SEZ', 'Hospitality'];
    const st = { cat: 'All', q: '', place: null, placeName: '', limit: 10 };
    const chips = $('#pchips'), list = $('#plist'), more = $('#pmore'), search = $('#psearch'), result = $('#presult');
    let onClear = () => {};
    const count = c => c === 'All' ? P.length : P.filter(p => p.s === c).length;
    chips.innerHTML = cats.map(c => `<button class="chip" type="button" aria-pressed="${c === 'All'}" data-c="${esc(c)}">${esc(c)}<small>${count(c)}</small></button>`).join('');
    chips.addEventListener('click', e => { const b = e.target.closest('.chip'); if (!b) return; st.cat = b.dataset.c; st.limit = 10; $$('.chip', chips).forEach(x => x.setAttribute('aria-pressed', x === b)); render(); });
    let qt; search.addEventListener('input', () => { clearTimeout(qt); qt = setTimeout(() => { st.q = search.value.trim().toLowerCase(); st.place = null; st.limit = 10; onClear(); render(); }, 120); });
    more.addEventListener('click', () => { st.limit += 10; render(true); });
    const matchPlace = (p, terms) => terms.some(t => `${p.n} ${p.l}`.toLowerCase().includes(t));
    const filtered = () => P.filter(p => (st.cat === 'All' || p.s === st.cat) && (!st.q || `${p.n} ${p.l} ${p.c} ${p.w}`.toLowerCase().includes(st.q)) && (!st.place || matchPlace(p, st.place)));
    function render(append) {
      const all = filtered(), shown = all.slice(0, st.limit), from = append ? list.children.length : 0;
      result.textContent = `Showing ${shown.length} of ${all.length}${st.place ? ' in ' + st.placeName : ''}${st.cat !== 'All' ? ' · ' + st.cat : ''}`;
      list.innerHTML = shown.length ? shown.map(p => `<li class="prow"><h4>${esc(p.n)}</h4><span class="prow__y">${esc(p.o ? 'Recent' : (p.y || ''))}</span><p><span class="prow__s">${esc(p.s)}</span>${esc([p.l, p.w, p.c].filter(Boolean).join(' · '))}</p></li>`).join('')
        : '<li class="pempty">No projects match. Try a city such as Chennai, or a client such as L&amp;T.</li>';
      more.hidden = all.length <= st.limit;
      if (G) G.fromTo([...list.children].slice(from), { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: .45, stagger: .03, ease: 'power3.out' });
      window.ScrollTrigger && ScrollTrigger.refresh();
    }
    render();
    return {
      count: t => P.filter(p => matchPlace(p, t)).length,
      setPlace(t, name) { st.place = t; st.placeName = name || ''; st.q = ''; search.value = ''; st.cat = 'All'; st.limit = 10; $$('.chip', chips).forEach(x => x.setAttribute('aria-pressed', x.dataset.c === 'All')); render(); },
      onClear(fn) { onClear = fn; }
    };
  })();

  (function atlas() {
    const svg = $('#mapsvg'), tip = $('#maptip'), idle = 'Select a city to filter projects';
    const minLon = 67.5, maxLon = 97.8, minLat = 7.5, maxLat = 37.3, W = 600, H = 680;
    const proj = ([lon, lat]) => [(lon - minLon) / (maxLon - minLon) * W, (maxLat - lat) / (maxLat - minLat) * H];
    const poly = S.india.map(proj);
    const inside = (x, y) => { let c = false; for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) { const [xi, yi] = poly[i], [xj, yj] = poly[j]; if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) c = !c; } return c; };
    const terms = { Hyderabad: ['hyderabad', 'jadcherla', 'sangareddy', 'beeramguda', 'nalgonda', 'hitech', 'jubilee'], Chennai: ['chennai'], Bengaluru: ['bangalore', 'bengaluru'], Bhubaneswar: ['odisha'], Noida: ['noida'], Nagpur: ['nagpur'], Jammu: ['jammu'], Lucknow: ['lucknow'], 'Naya Raipur': ['raipur'], Bhilai: ['bhilai'], Mumbai: ['mumbai'], Pune: ['pune'], Jharsuguda: ['jharsuguda'], Koraput: ['koraput'], Visakhapatnam: ['vizag'], 'Amaravati / Guntur': ['amaravati', 'guntur', 'mangalagiri'], Nellore: ['nellore'], Raichur: ['raichur'], Tiruchi: ['tiruchi'] };
    let dots = ''; const dotList = [];
    for (let y = 4; y < H; y += 10) for (let x = 4; x < W; x += 10) if (inside(x, y)) { dots += `<circle class="dot" cx="${x}" cy="${y}" r="1.7"/>`; dotList.push([x, y]); }
    const hq = proj(S.places[0].p); let arcs = '', pins = '';
    S.places.forEach((pl, i) => {
      const [x, y] = proj(pl.p);
      if (i && pl.k === 'br') arcs += `<path class="arc" d="M${hq[0]} ${hq[1]} Q${(x + hq[0]) / 2} ${(y + hq[1]) / 2 - Math.hypot(x - hq[0], y - hq[1]) * .3} ${x} ${y}"/>`;
      const c = pl.k === 'hq' ? 'var(--blue-h)' : pl.k === 'br' ? '#fff' : '#8a8a90', r = pl.k === 'hq' ? 6 : pl.k === 'br' ? 4 : 2.6;
      const left = pl.n === 'Bengaluru';
      const label = pl.k === 'site' ? '' : `<text x="${left ? x - 10 : x + 10}" y="${y + 4}"${left ? ' text-anchor="end"' : ''}>${esc(pl.n)}</text>`;
      pins += `<g class="pin" data-i="${i}" tabindex="0" role="button" aria-label="${esc(pl.n)}: ${esc(pl.note)}"><circle class="ring" cx="${x}" cy="${y}" r="12"/><circle class="core" cx="${x}" cy="${y}" r="${r}" fill="${c}"/><circle cx="${x}" cy="${y}" r="15" fill="transparent"/>${label}</g>`;
    });
    svg.innerHTML = `<g>${dots}</g><g>${arcs}</g><g>${pins}</g>`;
    const pinEls = $$('.pin', svg);
    const listeners = [];
    const select = i => { pinEls.forEach(p => p.classList.toggle('sel', p.dataset.i === String(i))); listeners.forEach(fn => fn(i)); };
    const reset = () => { select(null); tip.textContent = idle; };
    explorer.onClear(reset);
    function pick(i) {
      const pl = S.places[i], t = terms[pl.n] || [pl.n.toLowerCase()], n = explorer.count(t);
      select(i);
      tip.innerHTML = `<b>${esc(pl.n)}</b> — ${esc(pl.note)}. ${n ? `${n} project${n > 1 ? 's' : ''}.` : 'Regional office.'} <button type="button" id="mapclear">Show All</button>`;
      $('#mapclear').onclick = () => { explorer.setPlace(null); reset(); };
      if (n) explorer.setPlace(t, pl.n);
    }
    const termsOf = pl => terms[pl.n] || [pl.n.toLowerCase()];
    window.YAtlas = {
      places: S.places, proj, dots: dotList, pick,
      counts: S.places.map(pl => explorer.count(termsOf(pl))),
      clear: () => { explorer.setPlace(null); reset(); },
      onChange: fn => listeners.push(fn)
    };
    pinEls.forEach(p => {
      p.addEventListener('click', () => pick(+p.dataset.i));
      p.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(+p.dataset.i); } });
    });
  })();

  /* ---------- milestones: a sticky stage, vertical scroll slides the cards sideways ---------- */
  (function timeline() {
    const sec = $('#company'), track = $('#tltrack'), pin = $('.timeline__pin'), barEl = $('#tlbar');
    track.innerHTML = S.timeline.map(m => `<article class="tl"><p class="tl__y">${esc(m.y)}</p><div class="tl__img"><img src="${m.img}" alt="" loading="lazy" width="340" height="227"></div><h3>${esc(m.t)}</h3><p>${esc(m.d)}</p></article>`).join('');
    const cards = $$('.tl', track), wide = matchMedia('(min-width: 901px)');
    let sticky = false, dist = 0, centres = [], raf = 0;
    // Native position: sticky rather than a JS pin, so nothing snaps when the section starts or ends.
    function measure() {
      sticky = wide.matches && !reduce;
      sec.classList.toggle('timeline--sticky', sticky);
      track.style.transform = '';
      centres = cards.map(c => c.offsetLeft - track.offsetLeft + c.offsetWidth / 2);
      dist = Math.max(0, track.scrollWidth - innerWidth);
      sec.style.height = sticky ? `${Math.round(innerHeight + dist)}px` : '';
      update();
    }
    function update() {
      raf = 0;
      let x, p;
      if (sticky) {
        p = Math.max(0, Math.min(1, (scrollY - sec.offsetTop) / Math.max(1, dist))); x = p * dist;
        track.style.transform = `translate3d(${-x.toFixed(1)}px,0,0)`;
      } else { x = pin.scrollLeft; p = x / Math.max(1, pin.scrollWidth - pin.clientWidth); }
      barEl.style.transform = `scaleX(${p})`;
      if (reduce) return;
      // cards turn in 3D as they pass the centre of the screen
      const mid = innerWidth / 2;
      cards.forEach((c, i) => {
        const d = Math.max(-1.6, Math.min(1.6, (centres[i] - x - mid) / mid));
        c.style.transform = `perspective(1400px) rotateY(${(-d * 24).toFixed(2)}deg) translateZ(${(-Math.abs(d) * 140).toFixed(1)}px)`;
        c.style.opacity = (1 - Math.min(.55, Math.abs(d) * .35)).toFixed(3);
      });
    }
    const req = () => { if (!raf) raf = requestAnimationFrame(update); };
    addEventListener('scroll', req, { passive: true });
    pin.addEventListener('scroll', req, { passive: true });
    addEventListener('resize', measure);
    wide.addEventListener && wide.addEventListener('change', measure);
    addEventListener('load', measure);
    document.fonts && document.fonts.ready.then(measure);
    measure();
  })();

  /* ---------- quote planner ---------- */
  const sizeOf = p => Math.round(10000 * Math.pow(500, p / 100) / 5000) * 5000; // 10,000 to 50 lakh sq ft on a log scale
  function briefText() {
    const T = S.plan.types.find(t => t.id === plan.type), sc = S.plan.scopes.filter(s => plan.scopes.has(s.id));
    return `Hello Yalavarti team,\n\nWe would like a quote for the following project.\n\nProject type: ${T ? T.label : '-'}\nScope: ${sc.map(s => s.label).join(', ') || '-'}\nBuilt-up area: about ${inr(sizeOf(plan.size))} sq ft\nSite: ${plan.city || '-'}\nStage: ${plan.stage || '-'}\n\nName:\nCompany:\nPhone:\n`;
  }
  function renderBrief() {
    const T = S.plan.types.find(t => t.id === plan.type), sc = S.plan.scopes.filter(s => plan.scopes.has(s.id));
    $('#briefmeter').style.width = ([plan.type, sc.length, plan.city, plan.stage].filter(Boolean).length + 1) * 20 + '%';
    const row = (k, v) => `<div><dt>${k}</dt><dd${v ? '' : ' class="empty"'}>${v || 'Not set'}</dd></div>`;
    $('#brieflist').innerHTML = row('Project', T && `${esc(T.label)}<small>${esc(T.hint)}</small>`)
      + row('Scope', sc.length && sc.map(s => `${esc(s.label)}<small>${esc(s.inc)}</small>`).join(''))
      + row('Area', `<span class="num">${inr(sizeOf(plan.size))}</span> sq ft`)
      + row('Site', plan.city && esc(plan.city)) + row('Stage', plan.stage && esc(plan.stage));
    const sim = $('#briefsimilar');
    if (T) {
      let list = P.filter(p => p.s === T.sector && (!T.match || T.match.test(p.n))), local = false;
      if (plan.city) { const c = plan.city.toLowerCase(), near = list.filter(p => p.l.toLowerCase().includes(c)); if (near.length) { list = near; local = true; } }
      const total = list.length; list = list.slice().sort((a, b) => (b.y || '').localeCompare(a.y || '')).slice(0, 3);
      sim.innerHTML = total ? `${total} comparable ${esc(T.label.toLowerCase())} project${total > 1 ? 's' : ''} delivered${local ? ' in ' + esc(plan.city) : ''}, including:<ul>${list.map(p => `<li>${esc(p.n)}<span>${esc(p.l.split(',')[0])}</span></li>`).join('')}</ul>` : '';
    } else sim.textContent = 'Choose a project type to see comparable work.';
    const ready = !!(T && sc.length), send = $('#briefsend');
    send.setAttribute('aria-disabled', !ready);
    send.href = ready ? `mailto:info@yalavarti.com?subject=${encodeURIComponent(`Quote request: ${T.label}${plan.city ? ', ' + plan.city : ''}`)}&body=${encodeURIComponent(briefText())}` : '#quote';
  }
  (function planner() {
    const opt = (name, type, value, label, hint) => `<label class="opt"><input type="${type}" name="${name}" value="${esc(value)}"><span>${esc(label)}${hint ? `<small>${esc(hint)}</small>` : ''}</span></label>`;
    $('#qtype').innerHTML = S.plan.types.map(t => opt('type', 'radio', t.id, t.label, t.hint)).join('');
    $('#qscope').innerHTML = S.plan.scopes.map(s => opt('scope', 'checkbox', s.id, s.label)).join('');
    $('#qstage').innerHTML = S.plan.stages.map(s => opt('stage', 'radio', s, s)).join('');
    const form = $('#planform'), size = $('#qsize'), out = $('#qsizeout');
    const setSize = () => { plan.size = +size.value; out.textContent = inr(sizeOf(plan.size)) + ' sq ft'; size.style.setProperty('--p', size.value + '%'); size.setAttribute('aria-valuetext', out.textContent); };
    form.addEventListener('change', e => {
      const t = e.target;
      if (t.name === 'type') plan.type = t.value;
      if (t.name === 'stage') plan.stage = t.value;
      if (t.name === 'scope') { t.checked ? plan.scopes.add(t.value) : plan.scopes.delete(t.value); syncScopeButtons(); }
      renderBrief();
    });
    size.addEventListener('input', () => { setSize(); renderBrief(); });
    let ct; $('#qcity').addEventListener('input', e => { clearTimeout(ct); ct = setTimeout(() => { plan.city = e.target.value.trim(); renderBrief(); }, 200); });
    form.addEventListener('submit', e => e.preventDefault());
    $('#briefcopy').addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(briefText()); toast('Brief copied to clipboard'); } catch (e) { toast('Copying is blocked here. Use Email This Brief instead.'); }
    });
    $('#briefsend').addEventListener('click', e => { if ($('#briefsend').getAttribute('aria-disabled') === 'true') { e.preventDefault(); toast('Choose a project type and at least one scope first'); } else toast('Opening your email app…'); });
    setSize(); renderBrief();
  })();

  /* ---------- reveals (the only other motion) ---------- */
  if (G) {
    $$('.sechead, .proof__lead, .proof__stats > div, .case__body, .group, .contact__item, .careers__inner, .q, .brief').forEach(el =>
      G.from(el, { opacity: 0, y: 32, duration: 1, ease: 'expo.out', scrollTrigger: { trigger: el, start: 'top 88%' } }));
    $$('.case').forEach(c => G.fromTo(c, { rotateX: 14, scale: .88, transformPerspective: 1400, transformOrigin: '50% 0%' }, { rotateX: 0, scale: 1, ease: 'none', scrollTrigger: { trigger: c, start: 'top bottom', end: 'top 25%', scrub: true } }));
    G.from('#logos li', { opacity: 0, y: 16, duration: .7, stagger: .025, ease: 'power3.out', scrollTrigger: { trigger: '#logos', start: 'top 85%' } });
    // Recompute trigger positions whenever fonts or late images change the page height.
    let rt; const refresh = () => { clearTimeout(rt); rt = setTimeout(() => ScrollTrigger.refresh(), 150); };
    addEventListener('load', refresh);
    document.fonts && document.fonts.ready.then(refresh);
    let lastH = 0;
    new ResizeObserver(() => { const h = document.body.scrollHeight; if (Math.abs(h - lastH) > 4) { lastH = h; refresh(); } }).observe(document.getElementById('main'));
  }
})();
