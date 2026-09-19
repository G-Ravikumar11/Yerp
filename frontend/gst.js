/* ===========================================================================
   gst.js - the outward and inward supplies a return is filed from.

   Grouped by month because that is how the return is filed, and by rate
   because that is how its tables are laid out. Bills with no place of supply
   are called out at the top, because a return cannot be filed against a
   blank.
   =========================================================================== */

var GST = { states: {}, ours: null };

async function loadGst() {
    var box = document.getElementById('gst-outward-body');
    if (!box) return;
    var settings = await (await fetch('/api/gst/settings', { credentials: 'include' })).json();
    GST.states = settings.states || {};
    GST.ours = settings;
    document.getElementById('gst-gstin').value = settings.gstin || '';
    document.getElementById('gst-state').textContent = settings.state
        ? settings.state + ' (' + settings.state_code + ')'
        : 'Not set - every bill will carry IGST until it is.';

    var from = document.getElementById('gst-from').value;
    var to = document.getElementById('gst-to').value;
    var q = '?date_from=' + encodeURIComponent(from) + '&date_to=' + encodeURIComponent(to);
    var out = await (await fetch('/api/gst/outward' + q, { credentials: 'include' })).json();
    var inw = await (await fetch('/api/gst/inward' + q, { credentials: 'include' })).json();
    renderOutward(out);
    renderInward(inw);
    document.getElementById('gst-export').href = '/api/gst/outward.xlsx' + q;
}
window.loadGst = loadGst;

async function saveGstin() {
    var res = await fetch('/api/gst/settings', {
        method: 'PUT', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gstin: document.getElementById('gst-gstin').value }),
    });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Could not save it', 'error'); return; }
    showToast('Registered in ' + (out.state || 'no state'), 'success');
    loadGst();
}
window.saveGstin = saveGstin;

function renderOutward(d) {
    var s = d.summary || {};
    document.getElementById('gst-out-stats').innerHTML =
        statCard('Taxable value', formatCurrency(s.taxable || 0)) +
        statCard('CGST', formatCurrency(s.cgst || 0)) +
        statCard('SGST', formatCurrency(s.sgst || 0)) +
        statCard('IGST', formatCurrency(s.igst || 0)) +
        statCard('Total tax', formatCurrency(s.tax || 0));

    var warn = document.getElementById('gst-warn');
    warn.innerHTML = s.missing_place_of_supply
        ? '<div style="padding:12px 16px;border-left:3px solid var(--warning-color);' +
          'background:var(--warning-soft,#fff7ed);border-radius:var(--radius-md);font-size:0.85rem;">' +
          '<strong>' + s.missing_place_of_supply + ' bill' + (s.missing_place_of_supply === 1 ? '' : 's') +
          ' with no place of supply.</strong> Set the state on each project under Projects, ' +
          'then the split is recalculated the next time the bill is drawn. Until then they carry IGST.</div>'
        : '';

    document.getElementById('gst-months').innerHTML = (d.by_month || []).length
        ? '<table class="data-table"><thead><tr><th>Month</th><th class="text-right">Bills</th>' +
          '<th class="text-right">Taxable</th><th class="text-right">CGST</th><th class="text-right">SGST</th>' +
          '<th class="text-right">IGST</th><th class="text-right">Tax</th></tr></thead><tbody>' +
          d.by_month.map(function (m) {
              return '<tr><td style="font-weight:600;">' + esc(m.month) + '</td>' +
                  '<td class="text-right">' + m.bills + '</td>' +
                  '<td class="text-right">' + formatCurrency(m.taxable) + '</td>' +
                  '<td class="text-right">' + formatCurrency(m.cgst) + '</td>' +
                  '<td class="text-right">' + formatCurrency(m.sgst) + '</td>' +
                  '<td class="text-right">' + formatCurrency(m.igst) + '</td>' +
                  '<td class="text-right" style="font-weight:600;">' + formatCurrency(m.tax) + '</td></tr>';
          }).join('') + '</tbody></table>'
        : '<p style="color:var(--text-secondary);font-size:0.85rem;padding:12px 0;">Nothing certified in this period.</p>';

    document.getElementById('gst-outward-body').innerHTML = (d.supplies || []).length
        ? d.supplies.map(function (r) {
            return '<tr><td>' + esc(r.date) + '</td>' +
                '<td style="font-family:monospace;">' + esc(r.number) + '</td>' +
                '<td>' + esc(r.party || '—') + '<div style="font-size:0.72rem;color:var(--text-secondary);">' +
                    esc(r.project || '') + '</div></td>' +
                '<td>' + (r.place_of_supply
                    ? esc(GST.states[r.place_of_supply] || r.place_of_supply)
                    : '<span style="color:var(--warning-color);">not set</span>') + '</td>' +
                '<td class="text-right">' + r.rate + '%</td>' +
                '<td class="text-right">' + formatCurrency(r.taxable) + '</td>' +
                '<td class="text-right">' + (r.igst ? formatCurrency(r.igst) + ' <span style="font-size:0.7rem;color:var(--text-secondary);">IGST</span>'
                    : formatCurrency(r.cgst) + ' + ' + formatCurrency(r.sgst)) + '</td>' +
                '<td class="text-right" style="font-weight:600;">' + formatCurrency(r.total) + '</td></tr>';
          }).join('')
        : '<tr><td colspan="8" style="text-align:center;padding:22px;color:var(--text-secondary);">' +
          'No certified bills in this period.</td></tr>';
}

function renderInward(d) {
    var s = d.summary || {};
    document.getElementById('gst-in-stats').innerHTML =
        statCard('Taxable value', formatCurrency(s.taxable || 0)) +
        statCard('Input credit', formatCurrency(s.tax || 0)) +
        statCard('Bills', String(s.bills || 0)) +
        statCard('Missing supplier GSTIN', String(s.missing_party_gstin || 0));
    document.getElementById('gst-inward-body').innerHTML = (d.supplies || []).length
        ? d.supplies.map(function (r) {
            return '<tr><td>' + esc(r.date) + '</td>' +
                '<td style="font-family:monospace;">' + esc(r.number) +
                    '<div style="font-size:0.7rem;font-family:inherit;color:var(--text-secondary);">' + esc(r.kind) + '</div></td>' +
                '<td>' + esc(r.party || '—') +
                    (r.party_gstin ? '<div style="font-size:0.7rem;font-family:monospace;color:var(--text-secondary);">' + esc(r.party_gstin) + '</div>'
                                   : '<div style="font-size:0.7rem;color:var(--warning-color);">no GSTIN - credit at risk</div>') + '</td>' +
                '<td class="text-right">' + (r.rate ? r.rate + '%' : '—') + '</td>' +
                '<td class="text-right">' + formatCurrency(r.taxable) + '</td>' +
                '<td class="text-right" style="font-weight:600;">' + formatCurrency(r.tax) + '</td></tr>';
          }).join('')
        : '<tr><td colspan="6" style="text-align:center;padding:22px;color:var(--text-secondary);">' +
          'Nothing charged to us in this period.</td></tr>';
}
