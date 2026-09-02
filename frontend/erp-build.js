/* ===========================================================================
   erp-build.js - entering this data without a spreadsheet.

   A sheet is a poor instrument for master data. It accepts a code that
   already exists, a unit that is not a unit, an FG code on a job that never
   sold it - and only says so afterwards, in a red box, once the work is done.

   Here the code is issued rather than typed, the pickers only contain codes
   that exist, and a line prices itself as it is entered. The failures the
   upload path spends its effort detecting simply have nowhere to occur.
   Upload remains, behind a toggle, for bulk migration out of another system.
   =========================================================================== */

var VOCAB = null;
var _newItems = [];        // rows being typed on the Item Master screen
var _woDraft = { job_id: null, lines: [] };
var _bomDraft = { work_order_id: null, lines: [] };
var _fgMaster = [];
var _rmMaster = [];

async function vocabulary() {
    if (VOCAB) return VOCAB;
    try {
        VOCAB = await (await fetch('/api/erp/vocabulary')).json();
    } catch (e) {
        VOCAB = { item_types: ['Purchased', 'Service'],
                  units: ['Meters', 'Nos', 'Kgs', 'Litres', 'Sets', 'Lot'],
                  tax_rates: ['0%', '5%', '12%', '18%', '28%'] };
    }
    return VOCAB;
}

async function loadMasters() {
    try {
        var data = await (await fetch('/api/erp/items')).json();
        _fgMaster = (data.items || []).filter(function (i) { return i.kind === 'FG'; });
        _rmMaster = (data.items || []).filter(function (i) { return i.kind === 'RM'; });
    } catch (e) { _fgMaster = []; _rmMaster = []; }
}

function opts(list, selected) {
    return list.map(function (o) {
        return '<option' + (o === selected ? ' selected' : '') + '>' + esc(o) + '</option>';
    }).join('');
}

var cellCls = 'w-full bg-transparent px-2 py-1.5 rounded-md text-[13px] border border-slate-200 ' +
              'focus:border-brand focus:ring-1 focus:ring-brand focus:outline-none';

/* =========================================================================
   ITEM MASTER — type codes straight in
   ========================================================================= */

async function startNewItems(kind) {
    await vocabulary();
    if (!_newItems.length) await addItemRow(kind);
    renderItemComposer();
}
window.startNewItems = startNewItems;

async function addItemRow(kind) {
    kind = kind || (_newItems.length ? _newItems[_newItems.length - 1].kind : 'RM');
    var code = '';
    try {
        code = (await (await fetch('/api/erp/items/next-code?kind=' + kind)).json()).item_code;
    } catch (e) { /* the server will issue one on save */ }
    // Each pending row reserves the next code so two rows never claim one.
    var pending = _newItems.filter(function (r) { return r.kind === kind; }).length;
    if (code && pending) {
        var m = code.match(/^([A-Z]+)(\d+)$/);
        if (m) code = m[1] + String(parseInt(m[2]) + pending).padStart(m[2].length, '0');
    }
    _newItems.push({ kind: kind, item_code: code, item_name: '', description: '',
                     item_type: 'Purchased', units_of_measure: 'Nos',
                     hsn_code: '', item_tax_type: '18%' });
    renderItemComposer();
}
window.addItemRow = addItemRow;

function removeItemRow(i) {
    _newItems.splice(i, 1);
    renderItemComposer();
}
window.removeItemRow = removeItemRow;

function editNewItem(i, field, value) {
    _newItems[i][field] = value;
    // Changing the kind changes which series the code comes from.
    if (field === 'kind') refreshRowCode(i);
}
window.editNewItem = editNewItem;

async function refreshRowCode(i) {
    try {
        var r = await (await fetch('/api/erp/items/next-code?kind=' + _newItems[i].kind)).json();
        _newItems[i].item_code = r.item_code;
        renderItemComposer();
    } catch (e) { /* leave it; the server issues one on save */ }
}

/* Ask the server for the next number in the series. The button exists because
   a code is a thing you are given, not a thing you invent - and somebody who
   has cleared the field needs a way back to a valid one. */
async function issueCode(index) {
    try {
        var r = await (await fetch('/api/erp/items/next-code')).json();
        var offset = _newItems.slice(0, index).filter(function (row) {
            return (row.item_code || '').length === (r.item_code || '').length;
        }).length;
        _newItems[index].item_code = offset ? '' : r.item_code;
        // Rows above this one will take the numbers in between, so anything
        // after the first is left blank and issued properly on save.
        renderItemComposer();
        if (offset) showToast('This row is issued its number when you save', 'info');
    } catch (e) { showToast('Could not reach the code series', 'error'); }
}
window.issueCode = issueCode;

function renderItemComposer() {
    var host = document.getElementById('item-composer');
    if (!host) return;
    if (!_newItems.length) { host.innerHTML = ''; return; }
    var v = VOCAB || {};

    var rows = _newItems.map(function (r, i) {
        return '<tr class="border-b border-slate-100">' +
            '<td class="px-1 py-1"><select class="' + cellCls + '" onchange="editNewItem(' + i + ',\'kind\',this.value)">' +
                ['RM', 'FG'].map(function (k) {
                    return '<option value="' + k + '"' + (k === r.kind ? ' selected' : '') + '>' + k + '</option>';
                }).join('') + '</select></td>' +
            // Issued, not typed. Editable for anyone migrating an existing
            // numbering scheme, but never blank and never a guess.
            '<td class="px-1 py-1"><input class="' + cellCls + ' font-mono" value="' + esc(r.item_code) +
                '" oninput="editNewItem(' + i + ',\'item_code\',this.value)"></td>' +
            '<td class="px-1 py-1"><input class="' + cellCls + '" placeholder="What is it?" value="' + esc(r.item_name) +
                '" oninput="editNewItem(' + i + ',\'item_name\',this.value)"></td>' +
            '<td class="px-1 py-1"><select class="' + cellCls + '" onchange="editNewItem(' + i + ',\'item_type\',this.value)">' +
                opts(v.item_types || [], r.item_type) + '</select></td>' +
            '<td class="px-1 py-1"><select class="' + cellCls + '" onchange="editNewItem(' + i + ',\'units_of_measure\',this.value)">' +
                opts(v.units || [], r.units_of_measure) + '</select></td>' +
            '<td class="px-1 py-1"><input class="' + cellCls + '" value="' + esc(r.hsn_code) +
                '" oninput="editNewItem(' + i + ',\'hsn_code\',this.value)"></td>' +
            '<td class="px-1 py-1"><select class="' + cellCls + '" onchange="editNewItem(' + i + ',\'item_tax_type\',this.value)">' +
                opts(v.tax_rates || [], r.item_tax_type) + '</select></td>' +
            '<td class="px-1 py-1 text-right"><button class="text-ink-faint hover:text-red-600 px-2" ' +
                'onclick="removeItemRow(' + i + ')" title="Remove">&times;</button></td></tr>';
    }).join('');

    host.innerHTML =
        '<div class="border border-slate-200 rounded-lg overflow-x-auto">' +
        '<table class="min-w-full text-[13px]"><thead class="bg-slate-50"><tr>' +
        ['Kind', 'Code', 'Name', 'Type', 'Unit', 'HSN', 'Tax', ''].map(function (h) {
            return '<th class="px-2 py-2 text-left font-semibold text-ink-soft">' + h + '</th>';
        }).join('') + '</tr></thead><tbody>' + rows + '</tbody></table></div>' +
        '<div class="flex items-center gap-2 mt-3">' +
        '<button class="btn btn-outline btn-sm" onclick="addItemRow()">+ Another row</button>' +
        '<button class="btn btn-primary btn-sm" onclick="saveNewItems()">Save ' + _newItems.length + ' code(s)</button>' +
        '<button class="btn btn-sm" onclick="cancelNewItems()">Cancel</button>' +
        '<span class="text-xxs text-ink-soft ml-1">Codes are issued automatically — change one only if you are matching an existing scheme.</span>' +
        '</div>';
}

function cancelNewItems() {
    _newItems = [];
    renderItemComposer();
}
window.cancelNewItems = cancelNewItems;

async function saveNewItems() {
    var rows = _newItems.filter(function (r) { return (r.item_name || '').trim(); });
    if (!rows.length) { showToast('Give at least one item a name', 'error'); return; }
    try {
        var res = await fetch('/api/erp/items/bulk', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ items: rows })
        });
        var data = await res.json();
        if (!res.ok) { showToast(data.detail || 'Could not save', 'error'); return; }
        showToast(data.message, 'success');
        _newItems = [];
        renderItemComposer();
        loadItems();
        loadMasters();
    } catch (e) { showToast('Could not save', 'error'); }
}
window.saveNewItems = saveNewItems;

/* =========================================================================
   WORK ORDER — assembled from codes that exist
   ========================================================================= */

async function startWorkOrderBuilder() {
    await Promise.all([vocabulary(), loadMasters()]);
    // No bounce to the Item Master any more. A new deliverable is exactly the
    // thing somebody is pricing when they open this, and being sent to another
    // screen to name it - then back here to find the job and reference gone -
    // is how an order gets started three times. It is created from here.
    _woDraft = { job_id: null, lines: [] };
    var jobs = await jobOptions();
    var host = document.getElementById('wo-builder');
    host.innerHTML =
        '<div class="grid md:grid-cols-2 gap-4 mb-4">' +
        '<label class="block"><span class="block text-xxs font-semibold text-ink-soft mb-1">Job</span>' +
        '<select id="wob-job" class="' + cellCls + '">' +
            (jobs.length ? jobs.map(function (j) {
                return '<option value="' + j.id + '">' + esc(j.number + ' — ' + j.name) + '</option>';
            }).join('') : '<option value="">Create a job first</option>') + '</select></label>' +
        '<label class="block"><span class="block text-xxs font-semibold text-ink-soft mb-1">Reference</span>' +
        '<input id="wob-ref" class="' + cellCls + '" placeholder="Customer PO number"></label></div>' +
        '<div id="wob-lines"></div>';
    if (_fgMaster.length) addWorkOrderLine();
    else renderWorkOrderLines();
}
window.startWorkOrderBuilder = startWorkOrderBuilder;

function addWorkOrderLine() {
    // Offer only what has not been used; a repeated code on one order is a
    // quantity that should have been added together.
    var used = _woDraft.lines.map(function (l) { return l.code; });
    var free = _fgMaster.filter(function (i) { return used.indexOf(i.item_code) < 0; });
    if (!free.length) {
        showToast(_fgMaster.length
            ? 'Every finished goods code is already on this order'
            : 'Name the first deliverable to price it', 'error');
        return;
    }
    _woDraft.lines.push({ code: free[0].item_code, qty: 1,
                          rate: lastRate(free[0].item_code), description: '' });
    renderWorkOrderLines();
}
window.addWorkOrderLine = addWorkOrderLine;

/* --- A deliverable that does not have a code yet -------------------------
   An FG code identifies one thing being sold, so a new scope means a new
   code. Making that a trip to another screen is what pushed people back to
   the spreadsheet: there, a new line is just a new line.
   ------------------------------------------------------------------------ */

function newFgCode() {
    var v = VOCAB || {};
    openModal('fg-quick-modal');
    document.getElementById('fg-quick-name').value = '';
    var unit = document.getElementById('fg-quick-uom');
    unit.innerHTML = (v.units || ['Nos']).map(function (u) {
        return '<option' + (u === 'Nos' ? ' selected' : '') + '>' + esc(u) + '</option>';
    }).join('');
    var type = document.getElementById('fg-quick-type');
    type.innerHTML = (v.item_types || ['Purchased', 'Service']).map(function (t) {
        return '<option>' + esc(t) + '</option>';
    }).join('');
    var tax = document.getElementById('fg-quick-tax');
    tax.innerHTML = (v.tax_rates || ['18%']).map(function (t) {
        return '<option' + (t === '18%' ? ' selected' : '') + '>' + esc(t) + '</option>';
    }).join('');
    document.getElementById('fg-quick-name').focus();
}
window.newFgCode = newFgCode;

function closeFgQuick() {
    closeModal('fg-quick-modal');
}
window.closeFgQuick = closeFgQuick;

async function saveFgQuick() {
    var name = document.getElementById('fg-quick-name').value.trim();
    if (!name) { showToast('Say what is being sold', 'error'); return; }
    var res = await fetch('/api/erp/items', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            kind: 'FG', item_name: name, description: name,
            item_type: document.getElementById('fg-quick-type').value,
            units_of_measure: document.getElementById('fg-quick-uom').value,
            item_tax_type: document.getElementById('fg-quick-tax').value,
            hsn_code: document.getElementById('fg-quick-hsn').value.trim(),
        }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not add the code', 'error'); return; }

    closeFgQuick();
    showToast(out.item_code + ' issued for ' + name, 'success');
    await loadMasters();
    // Put it on the order, which is what it was created for. An existing
    // blank-ish line takes it rather than growing a second one.
    var used = _woDraft.lines.map(function (l) { return l.code; });
    if (used.indexOf(out.item_code) < 0) {
        _woDraft.lines.push({ code: out.item_code, qty: 1,
                              rate: lastRate(out.item_code), description: '' });
    }
    renderWorkOrderLines();
}
window.saveFgQuick = saveFgQuick;

/* What this code was last sold at. An offer, not a rule - prices move on a
   contract, so it is filled in and left editable rather than enforced. */
function lastRate(code) {
    var hit = _fgMaster.filter(function (i) { return i.item_code === code; })[0];
    return hit ? (hit.last_rate || 0) : 0;
}
window.lastRate = lastRate;

function editWoLine(i, field, value) {
    // Swapping the item brings its own price with it, unless somebody has
    // already typed one on this line.
    if (field === 'code' && !_woDraft.lines[i].rate) {
        _woDraft.lines[i].rate = lastRate(value);
    }
    _woDraft.lines[i][field] = (field === 'qty' || field === 'rate')
        ? (parseFloat(value) || 0) : value;
    renderWorkOrderLines();
}
window.editWoLine = editWoLine;

function removeWoLine(i) {
    _woDraft.lines.splice(i, 1);
    renderWorkOrderLines();
}
window.removeWoLine = removeWoLine;

function renderWorkOrderLines() {
    var host = document.getElementById('wob-lines');
    if (!host) return;
    var total = 0;

    var rows = _woDraft.lines.map(function (l, i) {
        var item = _fgMaster.filter(function (x) { return x.item_code === l.code; })[0] || {};
        var amount = (l.qty || 0) * (l.rate || 0);
        total += amount;
        var used = _woDraft.lines.map(function (x, j) { return j === i ? null : x.code; });
        var choices = _fgMaster.filter(function (x) { return used.indexOf(x.item_code) < 0; });
        return '<tr class="border-b border-slate-100">' +
            '<td class="px-1 py-1" style="min-width:260px;">' +
                '<select class="' + cellCls + '" onchange="editWoLine(' + i + ',\'code\',this.value)">' +
                choices.map(function (x) {
                    return '<option value="' + esc(x.item_code) + '"' +
                        (x.item_code === l.code ? ' selected' : '') + '>' +
                        esc(x.item_code + ' — ' + x.item_name) + '</option>';
                }).join('') + '</select></td>' +
            '<td class="px-2 py-1 text-xxs text-ink-soft">' + esc(item.item_type || '') + '</td>' +
            '<td class="px-1 py-1" style="width:100px;"><input type="number" min="0" step="any" class="' + cellCls + ' text-right" ' +
                'value="' + (l.qty || 0) + '" oninput="editWoLine(' + i + ',\'qty\',this.value)"></td>' +
            '<td class="px-2 py-1 text-xxs text-ink-soft">' + esc(item.units_of_measure || '') + '</td>' +
            '<td class="px-1 py-1" style="width:110px;"><input type="number" min="0" step="any" class="' + cellCls + ' text-right" ' +
                'value="' + (l.rate || 0) + '" oninput="editWoLine(' + i + ',\'rate\',this.value)"></td>' +
            '<td class="px-2 py-1 text-right font-medium">' + formatCurrency(amount) + '</td>' +
            '<td class="px-1 py-1 text-right"><button class="text-ink-faint hover:text-red-600 px-2" ' +
                'onclick="removeWoLine(' + i + ')">&times;</button></td></tr>';
    }).join('');

    host.innerHTML =
        '<div class="border border-slate-200 rounded-lg overflow-x-auto"><table class="min-w-full text-[13px]">' +
        '<thead class="bg-slate-50"><tr>' +
        ['Item', 'Type', 'Qty', 'Unit', 'Rate', 'Amount', ''].map(function (h) {
            return '<th class="px-2 py-2 text-left font-semibold text-ink-soft">' + h + '</th>';
        }).join('') + '</tr></thead><tbody>' + (rows ||
            '<tr><td colspan="7" class="px-2 py-6 text-center text-[13px] text-ink-soft">' +
            'Nothing priced yet. Name the first deliverable below.</td></tr>') +
        '</tbody></table></div>' +
        // Offered only while there is something left to add. Every code being
        // on the order already is an ordinary end to the list, not a mistake,
        // and a live button that answers with an error each time it is pressed
        // is how three identical complaints end up stacked on the screen.
        '<div class="flex items-center justify-between mt-3 flex-wrap gap-3">' +
        '<div class="flex gap-2 flex-wrap">' +
        (_woDraft.lines.length < _fgMaster.length
            ? '<button class="btn btn-outline btn-sm" onclick="addWorkOrderLine()">+ Add line</button>'
            : (_fgMaster.length
                ? '<span class="text-xxs text-ink-soft self-center">Every finished goods code is on this order.</span>'
                : '')) +
        // Always available: what is being sold on this order may simply not
        // have been named anywhere yet, and that is the ordinary case on a
        // new job rather than a mistake.
        '<button class="btn btn-outline btn-sm" onclick="newFgCode()">+ New deliverable</button>' +
        '</div>' +
        '<div class="text-[15px]">Order value <strong class="ml-2">' + formatCurrency(total) + '</strong></div>' +
        '</div>' +
        '<div class="flex gap-2 mt-3">' +
        '<button class="btn btn-primary" onclick="saveWorkOrder()">Create work order</button>' +
        '<button class="btn" onclick="closeWorkOrderBuilder()">Cancel</button></div>';
}

function closeWorkOrderBuilder() {
    var m = document.getElementById('wo-builder-modal');
    if (m) m.style.display = 'none';
    _woDraft = { job_id: null, lines: [] };
}
window.closeWorkOrderBuilder = closeWorkOrderBuilder;

async function saveWorkOrder() {
    var jobId = parseInt((document.getElementById('wob-job') || {}).value);
    if (!jobId) { showToast('Choose a job', 'error'); return; }
    if (!_woDraft.lines.length) { showToast('Add at least one line', 'error'); return; }
    var value = _woDraft.lines.reduce(function (t, l) {
        return t + (l.qty || 0) * (l.rate || 0);
    }, 0);
    if (value <= 0) {
        showToast('Every line is priced at zero. Put a rate against each line — ' +
                  'an order worth nothing cannot be measured or billed.', 'error');
        return;
    }
    try {
        var res = await fetch('/api/erp/work-orders/build', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_id: jobId,
                reference: (document.getElementById('wob-ref') || {}).value || '',
                lines: _woDraft.lines })
        });
        var data = await res.json();
        if (!res.ok) { showToast(data.detail || 'Could not create it', 'error'); return; }
        showToast(data.message, 'success');
        closeWorkOrderBuilder();
        loadWorkOrders();
    } catch (e) { showToast('Could not create it', 'error'); }
}
window.saveWorkOrder = saveWorkOrder;

/* =========================================================================
   BUDGET — allocate raw material against the lines actually sold
   ========================================================================= */

async function startBomBuilder(woId) {
    await loadMasters();
    if (!_rmMaster.length) {
        showToast('Add some raw material codes first', 'error');
        showView('items-view');
        return;
    }
    var wo;
    try {
        wo = await (await fetch('/api/erp/work-orders/' + woId)).json();
    } catch (e) { showToast('Could not open that order', 'error'); return; }

    _bomDraft = { work_order_id: woId, lines: (wo.bom || []).map(function (b) {
        return { fg_code: b.fg_code, rm_code: b.rm_code, qty: b.qty, rate: b.rate };
    }), sold: wo.lines || [], value: wo.total_value };

    document.getElementById('bom-builder-title').textContent = 'Budget — ' + wo.number;
    document.getElementById('bom-builder-modal').style.display = 'flex';
    if (!_bomDraft.lines.length) addBomLine();
    else renderBomLines();
}
window.startBomBuilder = startBomBuilder;

function addBomLine() {
    var sold = _bomDraft.sold || [];
    if (!sold.length) { showToast('That order has no lines', 'error'); return; }
    _bomDraft.lines.push({ fg_code: sold[0].fg_code, rm_code: _rmMaster[0].item_code,
                           qty: 1, rate: 0 });
    renderBomLines();
}
window.addBomLine = addBomLine;

function editBomLine(i, field, value) {
    _bomDraft.lines[i][field] = (field === 'qty' || field === 'rate')
        ? (parseFloat(value) || 0) : value;
    renderBomLines();
}
window.editBomLine = editBomLine;

function removeBomLine(i) {
    _bomDraft.lines.splice(i, 1);
    renderBomLines();
}
window.removeBomLine = removeBomLine;

function renderBomLines() {
    var host = document.getElementById('bom-builder-lines');
    if (!host) return;
    var cost = 0;

    var rows = _bomDraft.lines.map(function (l, i) {
        var rm = _rmMaster.filter(function (x) { return x.item_code === l.rm_code; })[0] || {};
        var amount = (l.qty || 0) * (l.rate || 0);
        cost += amount;
        return '<tr class="border-b border-slate-100">' +
            // Only lines that were actually sold: budgeting against anything
            // else is how a job costs more than it was ever worth.
            '<td class="px-1 py-1" style="min-width:200px;"><select class="' + cellCls + '" ' +
                'onchange="editBomLine(' + i + ',\'fg_code\',this.value)">' +
                (_bomDraft.sold || []).map(function (s) {
                    return '<option value="' + esc(s.fg_code) + '"' +
                        (s.fg_code === l.fg_code ? ' selected' : '') + '>' +
                        esc(s.fg_code + ' — ' + s.item_name) + '</option>';
                }).join('') + '</select></td>' +
            '<td class="px-1 py-1" style="min-width:220px;"><select class="' + cellCls + '" ' +
                'onchange="editBomLine(' + i + ',\'rm_code\',this.value)">' +
                _rmMaster.map(function (x) {
                    return '<option value="' + esc(x.item_code) + '"' +
                        (x.item_code === l.rm_code ? ' selected' : '') + '>' +
                        esc(x.item_code + ' — ' + x.item_name) + '</option>';
                }).join('') + '</select></td>' +
            '<td class="px-1 py-1" style="width:100px;"><input type="number" min="0" step="any" class="' + cellCls + ' text-right" ' +
                'value="' + (l.qty || 0) + '" oninput="editBomLine(' + i + ',\'qty\',this.value)"></td>' +
            '<td class="px-2 py-1 text-xxs text-ink-soft">' + esc(rm.units_of_measure || '') + '</td>' +
            '<td class="px-1 py-1" style="width:110px;"><input type="number" min="0" step="any" class="' + cellCls + ' text-right" ' +
                'value="' + (l.rate || 0) + '" oninput="editBomLine(' + i + ',\'rate\',this.value)"></td>' +
            '<td class="px-2 py-1 text-right font-medium">' + formatCurrency(amount) + '</td>' +
            '<td class="px-1 py-1 text-right"><button class="text-ink-faint hover:text-red-600 px-2" ' +
                'onclick="removeBomLine(' + i + ')">&times;</button></td></tr>';
    }).join('');

    /* The margin, live, as the budget is typed. It is the number the approver
       is actually being asked about, so it should not require a save to see. */
    var value = _bomDraft.value || 0;
    var margin = value - cost;
    var pct = value ? Math.round(margin / value * 1000) / 10 : 0;
    var tone = margin < 0 ? 'text-red-600' : 'text-emerald-700';

    host.innerHTML =
        '<div class="border border-slate-200 rounded-lg overflow-x-auto"><table class="min-w-full text-[13px]">' +
        '<thead class="bg-slate-50"><tr>' +
        ['Sold line (FG)', 'Consumes (RM)', 'Qty', 'Unit', 'Rate', 'Amount', ''].map(function (h) {
            return '<th class="px-2 py-2 text-left font-semibold text-ink-soft">' + h + '</th>';
        }).join('') + '</tr></thead><tbody>' + rows + '</tbody></table></div>' +
        '<div class="grid grid-cols-3 gap-3 mt-3">' +
        '<div class="border border-slate-200 rounded-lg px-3 py-2"><div class="text-xxs text-ink-soft">Order value</div>' +
            '<div class="font-semibold">' + formatCurrency(value) + '</div></div>' +
        '<div class="border border-slate-200 rounded-lg px-3 py-2"><div class="text-xxs text-ink-soft">Budgeted cost</div>' +
            '<div class="font-semibold">' + formatCurrency(cost) + '</div></div>' +
        '<div class="border border-slate-200 rounded-lg px-3 py-2"><div class="text-xxs text-ink-soft">Margin</div>' +
            '<div class="font-semibold ' + tone + '">' + formatCurrency(margin) +
            ' <span class="text-xxs font-normal">' + pct + '%</span></div></div></div>' +
        '<div class="flex gap-2 mt-3">' +
        '<button class="btn btn-outline btn-sm" onclick="addBomLine()">+ Add material</button>' +
        '<button class="btn btn-primary" onclick="saveBom()">Save budget</button>' +
        '<button class="btn" onclick="closeBomBuilder()">Cancel</button></div>';
}

function closeBomBuilder() {
    var m = document.getElementById('bom-builder-modal');
    if (m) m.style.display = 'none';
}
window.closeBomBuilder = closeBomBuilder;

async function saveBom() {
    if (!_bomDraft.lines.length) { showToast('Add at least one material line', 'error'); return; }
    try {
        var res = await fetch('/api/erp/bom/build', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ work_order_id: _bomDraft.work_order_id,
                                   lines: _bomDraft.lines })
        });
        var data = await res.json();
        if (!res.ok) { showToast(data.detail || 'Could not save', 'error'); return; }
        showToast(data.message, 'success');
        closeBomBuilder();
        loadWorkOrders();
    } catch (e) { showToast('Could not save', 'error'); }
}
window.saveBom = saveBom;

/* The upload path is still there for migrating out of another system; it is
   just no longer the way this data is normally entered. */
function toggleImportPanel() {
    var p = document.getElementById('import-panel');
    if (p) p.hidden = !p.hidden;
}
window.toggleImportPanel = toggleImportPanel;

/* The builder opens in a modal so the existing list stays behind it. */
async function openWorkOrderBuilder() {
    document.getElementById('wo-builder-modal').style.display = 'flex';
    await startWorkOrderBuilder();
}
window.openWorkOrderBuilder = openWorkOrderBuilder;

/* =========================================================================
   THE ITEM MASTER AS A SHEET

   The grid is mounted when the screen opens rather than waiting for a button,
   because an empty panel that needs a click first is the thing people said
   was missing. Codes are deliberately not a column you can type in: they are
   issued on save, so the sheet shows what each row will be given.
   ========================================================================= */

/* The nth code after this one, keeping the prefix and the zero padding.
   Shown rather than a repeated placeholder so the sheet says what each row
   will actually be called - which is the only reason to show a code that has
   not been issued yet. */
function nextCodeAfter(code, n) {
    var m = /^(.*?)(\d+)$/.exec(code || '');
    if (!m) return '';
    var num = String(parseInt(m[2], 10) + n);
    return m[1] + (num.length >= m[2].length ? num
        : new Array(m[2].length - num.length + 1).join('0') + num);
}
window.nextCodeAfter = nextCodeAfter;


async function mountItemGrid() {
    var host = document.getElementById('item-grid');
    if (!host || typeof mountGrid !== 'function') return;
    var v = await vocabulary();
    var next = '';
    try {
        next = (await (await fetch('/api/erp/items/next-code')).json()).item_code;
    } catch (e) { /* shown as a dash below */ }

    mountGrid('item-grid', [
        { key: 'kind', label: 'Kind', width: '80px',
          options: ['RM', 'FG'], def: 'RM' },
        { key: 'item_code', label: 'Code', width: '90px', readonly: true,
          hint: 'issued on save', derive: function (n) { return nextCodeAfter(next, n); } },
        { key: 'item_name', label: 'Item name', width: '260px',
          placeholder: 'What is it?' },
        { key: 'item_type', label: 'Type', width: '120px',
          options: v.item_types || ['Purchased', 'Service'], def: 'Purchased' },
        { key: 'units_of_measure', label: 'Unit', width: '110px',
          options: v.units || ['Nos'], def: 'Nos' },
        { key: 'hsn_code', label: 'HSN', width: '90px' },
        { key: 'item_tax_type', label: 'Tax', width: '90px',
          options: v.tax_rates || ['18%'], def: '18%' },
    ], { minRows: 8 });
}
window.mountItemGrid = mountItemGrid;

async function saveGridItems() {
    var rows = (typeof gridData === 'function' ? gridData() : [])
        .filter(function (r) { return (r.item_name || '').trim(); });
    var out = document.getElementById('grid-result');
    if (!rows.length) {
        showToast('Give at least one row an item name', 'error');
        return;
    }
    try {
        var res = await fetch('/api/erp/items/bulk', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ items: rows.map(function (r) {
                return { kind: r.kind, item_name: r.item_name,
                         item_type: r.item_type, units_of_measure: r.units_of_measure,
                         hsn_code: r.hsn_code, item_tax_type: r.item_tax_type };
            }) })
        });
        var data = await res.json();
        if (!res.ok) {
            out.innerHTML = '<div class="border border-red-300 bg-red-50 rounded-lg p-3 ' +
                'text-[13px] text-red-800">' + esc(data.detail || 'Nothing was saved') + '</div>';
            showToast(data.detail || 'Nothing was saved', 'error');
            return;
        }
        /* The codes it was given, listed, because they were issued rather than
           chosen and the person has not seen them before. */
        out.innerHTML = '<div class="border border-emerald-300 bg-emerald-50 rounded-lg p-3 ' +
            'text-[13px] text-emerald-900">' + esc(data.message) +
            ' <span class="font-mono">' + data.codes.map(esc).join(', ') + '</span></div>';
        showToast(data.message, 'success');
        gridReset();
        loadItems();
        mountItemGrid();
    } catch (e) { showToast('Could not save those rows', 'error'); }
}
window.saveGridItems = saveGridItems;

/* --- The Excel path, as two explicit steps ------------------------------
   Validate and Upload are separate buttons because that is the flow people
   already run: check the file first, commit it second. Validate writes
   nothing at all. */

function toggleTypeIn(btn) {
    var panel = document.getElementById('typein-panel');
    if (!panel) return;
    panel.hidden = !panel.hidden;
    if (!panel.hidden && typeof mountItemGrid === 'function') mountItemGrid();
    // The button has to say what pressing it will do, not what it just did.
    var control = btn || document.querySelector('[onclick^="toggleTypeIn"]');
    if (control) control.textContent = panel.hidden ? 'Show the grid' : 'Hide the grid';
}
window.toggleTypeIn = toggleTypeIn;

async function validateItemFile() {
    var out = document.getElementById('item-analysis');
    var input = document.getElementById('item-file');
    if (!input || !input.files.length) { showToast('Choose a file first', 'error'); return; }
    out.innerHTML = '<p class="text-[13px] text-ink-soft">Reading the file…</p>';

    var fd = new FormData();
    fd.append('file', input.files[0]);
    try {
        var res = await fetch('/api/erp/items/analyse', { method: 'POST', body: fd });
        var data = await res.json();
        if (!res.ok) {
            out.innerHTML = '<div class="border border-red-300 bg-red-50 rounded-lg p-3 ' +
                'text-[13px] text-red-800">' + esc(data.detail || 'That file could not be read') + '</div>';
            return;
        }
        _analysis = data;
        renderAnalysis();
        showToast(data.ok ? 'Validated — nothing saved yet'
                          : data.summary.blocked + ' row(s) need fixing', data.ok ? 'success' : 'error');
    } catch (e) {
        out.innerHTML = '<div class="border border-red-300 bg-red-50 rounded-lg p-3 text-[13px] text-red-800">' +
            'Could not read that file.</div>';
    }
}
window.validateItemFile = validateItemFile;

/* Upload validates again on the way through rather than trusting that the
   button beside it was pressed first. */
async function uploadItemFile() {
    if (!_analysis) {
        await validateItemFile();
        if (!_analysis) return;
    }
    await commitItemSheet();
}
window.uploadItemFile = uploadItemFile;
