/* ===========================================================================
   fixedassets.js - what each owned asset is worth on the books, and the
   income-tax blocks the return is filed on.
   =========================================================================== */

var FA = { tab: 'register', fy: '', data: null, blocks: null, assetId: 0, blockId: 0 };

async function loadFixedAssets() {
    var sel = document.getElementById('fa-fy');
    if (!sel) return;
    var q = FA.fy ? '?fy=' + encodeURIComponent(FA.fy) : '';
    var d = FA.data = await (await fetch('/api/fixed-assets' + q, { credentials: 'include' })).json();
    FA.fy = d.fy;
    sel.innerHTML = d.fys.map(function (y) { return '<option' + (y === d.fy ? ' selected' : '') + '>' + y + '</option>'; }).join('');
    document.querySelectorAll('#fa-tabs button').forEach(function (b) { b.classList.toggle('active', b.dataset.tab === FA.tab); });
    document.getElementById('fa-xlsx').href = FA.tab === 'register'
        ? '/api/fixed-assets.xlsx?fy=' + d.fy : '/api/fixed-assets/tax-blocks.xlsx?fy=' + d.fy;
    if (FA.tab === 'register') faRegister(d); else await faBlocks();
}
window.loadFixedAssets = loadFixedAssets;

function faTab(t) { FA.tab = t; loadFixedAssets(); }
window.faTab = faTab;

function faYear() { FA.fy = document.getElementById('fa-fy').value; loadFixedAssets(); }
window.faYear = faYear;

function faMethod(r) {
    return r.method === 'SLM' ? 'SLM, ' + r.life_years + ' yrs' : 'WDV ' + r.rate_percent + '%';
}

function faRegister(d) {
    var t = d.totals;
    document.getElementById('fa-stats').innerHTML =
        statCard('Cost', formatCurrency(t.cost)) +
        statCard('Depreciation in ' + d.fy, formatCurrency(t.depreciation)) +
        statCard('Book value at 31 March', formatCurrency(t.closing)) +
        statCard('Accumulated', formatCurrency(t.accumulated)) +
        (t.gain ? statCard((t.gain >= 0 ? 'Profit' : 'Loss') + ' on sales', formatCurrency(Math.abs(t.gain))) : '');
    var nr = 'white-space:nowrap;';
    var rows = d.assets.map(function (r) {
        var y = r.year;
        return '<tr><td style="' + nr + '"><span style="font-family:monospace;font-weight:600;">' + esc(r.code) + '</span>' +
            '<div style="font-size:0.75rem;color:var(--text-secondary);white-space:normal;">' + esc(r.name) + '</div></td>' +
            '<td style="' + nr + '">' + esc(r.put_to_use_on) + '<div style="font-size:0.72rem;color:var(--text-secondary);">' + esc(faMethod(r)) + '</div></td>' +
            '<td class="text-right" style="' + nr + '">' + formatCurrency(r.cost) + '</td>' +
            '<td class="text-right" style="' + nr + '">' + formatCurrency(y.opening + y.added) +
                (y.added ? '<div style="font-size:0.72rem;color:var(--text-secondary);">bought this year</div>' : '') + '</td>' +
            '<td class="text-right" style="' + nr + '">' + formatCurrency(y.depreciation) +
                (y.days < 365 ? '<div style="font-size:0.72rem;color:var(--text-secondary);">' + y.days + ' days</div>' : '') + '</td>' +
            '<td class="text-right" style="' + nr + 'font-weight:700;">' + (y.disposed
                ? '<span style="font-weight:400;">sold ' + formatCurrency(y.disposal_value) + '</span><div style="font-size:0.72rem;color:' +
                  (y.gain >= 0 ? 'var(--success-color)' : 'var(--danger-color)') + ';">' + (y.gain >= 0 ? 'profit ' : 'loss ') + formatCurrency(Math.abs(y.gain)) + '</div>'
                : formatCurrency(y.closing)) + '</td>' +
            '<td class="text-right" style="' + nr + '">' +
                '<button class="btn btn-sm btn-outline" onclick="faSchedule(' + r.asset_id + ')">Years</button> ' +
                (r.disposed_on ? '' : '<button class="btn btn-sm btn-outline" onclick="faEdit(' + r.asset_id + ')">Edit</button> ' +
                 '<button class="btn btn-sm btn-outline" onclick="faDispose(' + r.asset_id + ')">Sold</button>') + '</td></tr>';
    }).join('');
    var unset = d.not_set_up.length ? '<h4 style="font-size:0.9rem;margin:22px 0 8px;">Owned, but no book yet</h4>' +
        '<div class="widget"><div class="table-responsive"><table class="data-table"><thead><tr><th>Asset</th><th>Category</th>' +
        '<th class="text-right">Bought for</th><th>On</th><th></th></tr></thead><tbody>' +
        d.not_set_up.map(function (u) {
            return '<tr><td><span style="font-family:monospace;font-weight:600;">' + esc(u.code) + '</span> ' + esc(u.name) + '</td>' +
                '<td>' + esc(u.category) + '</td><td class="text-right" style="' + nr + '">' + (u.suggest.cost ? formatCurrency(u.suggest.cost) : '—') + '</td>' +
                '<td>' + esc(u.suggest.put_to_use_on || '—') + '</td>' +
                '<td class="text-right"><button class="btn btn-sm btn-outline" onclick="faEdit(' + u.asset_id + ')">Set up</button></td></tr>';
        }).join('') + '</tbody></table></div></div>' : '';
    document.getElementById('fa-body').innerHTML =
        '<div class="widget"><div class="table-responsive"><table class="data-table"><thead><tr><th>Asset</th><th>In use from</th>' +
        '<th class="text-right">Cost</th><th class="text-right">Opening</th><th class="text-right">Depreciation</th>' +
        '<th class="text-right">Closing</th><th></th></tr></thead><tbody>' +
        (rows || '<tr><td colspan="7" style="text-align:center;padding:24px;color:var(--text-secondary);">Nothing on the books for ' +
            esc(d.fy) + '. Owned machines from the equipment register appear below until their book is set up.</td></tr>') +
        '</tbody></table></div></div>' + unset;
    document.getElementById('fa-setup-all').style.display = d.not_set_up.some(function (u) { return u.ready; }) ? '' : 'none';
}

async function faBlocks() {
    var d = FA.blocks = await (await fetch('/api/fixed-assets/tax-blocks?fy=' + encodeURIComponent(FA.fy), { credentials: 'include' })).json();
    var t = d.totals;
    document.getElementById('fa-stats').innerHTML =
        statCard('Opening WDV', formatCurrency(t.opening)) +
        statCard('Added', formatCurrency(t.added_full + t.added_half)) +
        statCard('Tax depreciation', formatCurrency(t.depreciation)) +
        statCard('Closing WDV', formatCurrency(t.closing)) +
        (t.short_term_gain ? statCard('Short-term gain', formatCurrency(t.short_term_gain)) : '');
    var nr = 'white-space:nowrap;';
    document.getElementById('fa-body').innerHTML =
        '<p style="font-size:0.84rem;color:var(--text-secondary);margin:0 0 10px;">As the income-tax return wants it: each block at its rate, ' +
        'half the rate on anything used for less than 180 days in the year it was bought.</p>' +
        '<div class="widget"><div class="table-responsive"><table class="data-table"><thead><tr><th>Block</th>' +
        '<th class="text-right">Opening</th><th class="text-right">Added</th><th class="text-right">Sold</th>' +
        '<th class="text-right">Depreciation</th><th class="text-right">Closing</th><th></th></tr></thead><tbody>' +
        d.blocks.map(function (b) {
            var quiet = !b.opening && !b.added_full && !b.added_half && !b.deleted && !b.closing;
            return '<tr style="' + (quiet ? 'opacity:.55;' : '') + '"><td>' + esc(b.block) + '<div style="font-size:0.72rem;color:var(--text-secondary);">' + b.rate + '%' +
                (b.opening_fy ? ' &middot; opened ' + esc(b.opening_fy) : '') + '</div></td>' +
                '<td class="text-right" style="' + nr + '">' + formatCurrency(b.opening) + '</td>' +
                '<td class="text-right" style="' + nr + '">' + formatCurrency(b.added_full + b.added_half) +
                    (b.added_half ? '<div style="font-size:0.72rem;color:var(--text-secondary);">' + formatCurrency(b.added_half) + ' at half rate</div>' : '') + '</td>' +
                '<td class="text-right" style="' + nr + '">' + formatCurrency(b.deleted) + '</td>' +
                '<td class="text-right" style="' + nr + '">' + formatCurrency(b.depreciation) + '</td>' +
                '<td class="text-right" style="' + nr + 'font-weight:700;">' + formatCurrency(b.closing) +
                    (b.short_term_gain ? '<div style="font-size:0.72rem;color:var(--danger-color);font-weight:400;">short-term gain ' + formatCurrency(b.short_term_gain) + '</div>' : '') +
                    (b.short_term_loss ? '<div style="font-size:0.72rem;font-weight:400;">short-term loss ' + formatCurrency(b.short_term_loss) + '</div>' : '') + '</td>' +
                '<td class="text-right"><button class="btn btn-sm btn-outline" onclick="faBlockEdit(' + b.block_id + ')">Edit</button></td></tr>';
        }).join('') + '</tbody></table></div></div>';
    document.getElementById('fa-setup-all').style.display = 'none';
}

function faFind(assetId) {
    var r = FA.data.assets.find(function (x) { return x.asset_id === assetId; });
    if (r) return { book: r, set: true };
    var u = FA.data.not_set_up.find(function (x) { return x.asset_id === assetId; });
    return u ? { book: Object.assign({ code: u.code, name: u.name, category: u.category, opening_fy: '', opening_book_value: 0 }, u.suggest), set: false } : null;
}

async function faEdit(assetId) {
    var f = faFind(assetId);
    if (!f) {
        // Not in this year's register (bought later, or before its opening): ask for the book itself.
        var s = await fetch('/api/fixed-assets/' + assetId + '/schedule', { credentials: 'include' });
        if (!s.ok) return;
        f = { book: (await s.json()).book, set: true };
    }
    var b = f.book;
    FA.assetId = assetId;
    document.getElementById('fab-title').textContent = (f.set ? 'Book for ' : 'Set up the book for ') + b.code + ' ' + b.name;
    document.getElementById('fab-method').value = b.method || 'WDV';
    document.getElementById('fab-life').value = b.life_years;
    document.getElementById('fab-residual').value = b.residual_percent;
    document.getElementById('fab-put').value = b.put_to_use_on || '';
    document.getElementById('fab-cost').value = b.cost || '';
    document.getElementById('fab-block').innerHTML = FA.data.blocks.map(function (x) {
        return '<option' + (x === b.tax_block ? ' selected' : '') + '>' + esc(x) + '</option>'; }).join('');
    document.getElementById('fab-opening-fy').value = b.opening_fy || '';
    document.getElementById('fab-opening-value').value = b.opening_book_value || '';
    document.getElementById('fab-old').open = !!b.opening_fy;
    faRate();
    openModal('fab-modal');
}
window.faEdit = faEdit;

function faRate() {
    var m = document.getElementById('fab-method').value;
    var life = parseFloat(document.getElementById('fab-life').value) || 0;
    var res = parseFloat(document.getElementById('fab-residual').value) || 0;
    var cost = parseFloat(document.getElementById('fab-cost').value) || 0;
    var out = '';
    if (life > 0 && cost > 0) {
        if (m === 'SLM') out = formatCurrency((cost - cost * res / 100) / life) + ' a year, down to ' + formatCurrency(cost * res / 100);
        else if (res > 0) out = (Math.round((1 - Math.pow(res / 100, 1 / life)) * 10000) / 100) + '% a year on what is left, down to ' + formatCurrency(cost * res / 100);
        else out = '<span style="color:var(--danger-color);">Written-down value needs a residual above nought.</span>';
    }
    document.getElementById('fab-rate').innerHTML = out;
}
window.faRate = faRate;

async function faSave() {
    var v = function (id) { return document.getElementById(id).value; };
    var res = await fetch('/api/fixed-assets/' + FA.assetId + '/book', { method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ method: v('fab-method'), life_years: parseFloat(v('fab-life')) || 0,
            residual_percent: parseFloat(v('fab-residual')) || 0, put_to_use_on: v('fab-put'),
            cost: parseFloat(v('fab-cost')) || 0, tax_block: v('fab-block'),
            opening_fy: v('fab-opening-fy').trim(), opening_book_value: parseFloat(v('fab-opening-value')) || 0 }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Not saved', 'error'); return; }
    showToast(out.message, 'success');
    closeModal('fab-modal');
    loadFixedAssets();
}
window.faSave = faSave;

async function faSetUpAll() {
    var res = await fetch('/api/fixed-assets/set-up-all', { method: 'POST', credentials: 'include' });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Not done', 'error'); return; }
    showToast(out.message, 'success');
    loadFixedAssets();
}
window.faSetUpAll = faSetUpAll;

async function faSchedule(assetId) {
    var d = await (await fetch('/api/fixed-assets/' + assetId + '/schedule', { credentials: 'include' })).json();
    var b = d.book;
    document.getElementById('fas-title').textContent = b.code + ' ' + b.name + ' - ' + faMethod(b);
    var nr = 'white-space:nowrap;';
    document.getElementById('fas-body').innerHTML = '<div class="table-responsive"><table class="data-table"><thead><tr><th>Year</th>' +
        '<th class="text-right">Opening</th><th class="text-right">Depreciation</th><th class="text-right">Closing</th>' +
        '<th class="text-right">Accumulated</th></tr></thead><tbody>' +
        d.rows.map(function (r) {
            return '<tr><td>' + esc(r.fy) + (r.days < 365 ? ' <span style="font-size:0.72rem;color:var(--text-secondary);">(' + r.days + ' days)</span>' : '') + '</td>' +
                '<td class="text-right" style="' + nr + '">' + formatCurrency(r.opening + r.added) + '</td>' +
                '<td class="text-right" style="' + nr + '">' + formatCurrency(r.depreciation) + '</td>' +
                '<td class="text-right" style="' + nr + 'font-weight:600;">' + (r.disposed ? 'sold ' + formatCurrency(r.disposal_value) +
                    ' <span style="font-size:0.72rem;color:' + (r.gain >= 0 ? 'var(--success-color)' : 'var(--danger-color)') + ';">(' +
                    (r.gain >= 0 ? 'profit ' : 'loss ') + formatCurrency(Math.abs(r.gain)) + ')</span>' : formatCurrency(r.closing)) + '</td>' +
                '<td class="text-right" style="' + nr + '">' + formatCurrency(r.accumulated) + '</td></tr>';
        }).join('') + '</tbody></table></div>';
    openModal('fas-modal');
}
window.faSchedule = faSchedule;

function faDispose(assetId) {
    var f = faFind(assetId);
    FA.assetId = assetId;
    document.getElementById('fad-title').textContent = 'Sold or scrapped: ' + f.book.code + ' ' + f.book.name;
    document.getElementById('fad-date').value = localDate(new Date());
    document.getElementById('fad-value').value = '';
    document.getElementById('fad-note').value = '';
    openModal('fad-modal');
}
window.faDispose = faDispose;

async function faDisposeSave() {
    var v = function (id) { return document.getElementById(id).value; };
    var res = await fetch('/api/fixed-assets/' + FA.assetId + '/dispose', { method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ disposed_on: v('fad-date'), disposal_value: parseFloat(v('fad-value')) || 0, note: v('fad-note') }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Not recorded', 'error'); return; }
    showToast(out.message, 'success');
    closeModal('fad-modal');
    loadFixedAssets();
}
window.faDisposeSave = faDisposeSave;

function faBlockEdit(blockId) {
    var b = FA.blocks.blocks.find(function (x) { return x.block_id === blockId; });
    FA.blockId = blockId;
    document.getElementById('fatb-title').textContent = b.block;
    document.getElementById('fatb-rate').value = b.rate;
    document.getElementById('fatb-fy').value = b.opening_fy || '';
    document.getElementById('fatb-wdv').value = b.opening_wdv || '';
    openModal('fatb-modal');
}
window.faBlockEdit = faBlockEdit;

async function faBlockSave() {
    var v = function (id) { return document.getElementById(id).value; };
    var res = await fetch('/api/fixed-assets/tax-blocks/' + FA.blockId, { method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rate: parseFloat(v('fatb-rate')), opening_fy: v('fatb-fy').trim(),
                               opening_wdv: parseFloat(v('fatb-wdv')) || 0 }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Not saved', 'error'); return; }
    showToast(out.message, 'success');
    closeModal('fatb-modal');
    loadFixedAssets();
}
window.faBlockSave = faBlockSave;
