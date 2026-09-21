/* ===========================================================================
   registers.js - the three sheets the accountant kept by hand.

   TDS by quarter (both directions), bank guarantees and when they lapse,
   advances given and recovered. Every figure was already in the app; the
   sheets existed because nothing laid them out the way the 26Q, the bank
   and the site accountant want them.
   =========================================================================== */

async function loadRegisters() {
    if (!document.getElementById('reg-tds-deducted')) return;
    await Promise.all([loadTdsRegister(), loadGuaranteeRegister(), loadAdvanceRegister()]);
}
window.loadRegisters = loadRegisters;

function regEmpty(cols, text) {
    return '<tr><td colspan="' + cols + '" style="text-align:center;padding:22px;color:var(--text-secondary);">' + text + '</td></tr>';
}

async function loadTdsRegister() {
    var year = document.getElementById('reg-tds-year').value;
    var quarter = document.getElementById('reg-tds-quarter').value;
    var q = '?year=' + encodeURIComponent(year) + '&quarter=' + encodeURIComponent(quarter);
    var d = await (await fetch('/api/registers/tds' + q, { credentials: 'include' })).json();
    var s = d.summary || {};
    document.getElementById('reg-tds-stats').innerHTML =
        statCard('Deducted by us (to deposit)', formatCurrency(s.deducted || 0)) +
        statCard('Deducted from us (to claim)', formatCurrency(s.suffered || 0)) +
        statCard('Deductees without a PAN', String(s.deductees_without_pan || 0));

    var yearSel = document.getElementById('reg-tds-year');
    if (!yearSel.options.length || yearSel.options.length === 1) {
        yearSel.innerHTML = '<option value="">Every year</option>' + (d.years || []).map(function (y) {
            return '<option value="' + esc(y) + '"' + (y === year ? ' selected' : '') + '>' + esc(y) + '</option>'; }).join('');
    }

    document.getElementById('reg-tds-quarters').innerHTML = (d.deducted_by_quarter || []).length
        ? '<table class="data-table"><thead><tr><th>Quarter</th><th class="text-right">Bills</th>' +
          '<th class="text-right">Amount credited ₹</th><th class="text-right">TDS to deposit ₹</th></tr></thead><tbody>' +
          d.deducted_by_quarter.map(function (r) {
              return '<tr><td style="font-weight:600;">' + esc(r.period) + '</td><td class="text-right">' + r.bills + '</td>' +
                  '<td class="text-right">' + formatCurrency(r.amount_credited) + '</td>' +
                  '<td class="text-right" style="font-weight:600;">' + formatCurrency(r.tds) + '</td></tr>';
          }).join('') + '</tbody></table>'
        : '<p style="color:var(--text-secondary);font-size:0.85rem;padding:12px 0;">Nothing deducted in this period.</p>';

    document.getElementById('reg-tds-deducted').innerHTML = (d.deducted || []).length
        ? d.deducted.map(function (r) {
            return '<tr><td>' + esc(r.date) + '</td><td>' + esc(r.year + ' ' + r.quarter) + '</td>' +
                '<td style="font-family:monospace;">' + esc(r.bill) + '</td>' +
                '<td>' + esc(r.deductee) + (r.missing_pan
                    ? '<div style="font-size:0.7rem;color:var(--danger-color);">no PAN - 20% applies</div>'
                    : '<div style="font-size:0.7rem;font-family:monospace;color:var(--text-secondary);">' + esc(r.pan) + '</div>') + '</td>' +
                '<td>' + esc(r.section) + ' @ ' + r.rate + '%</td>' +
                '<td class="text-right">' + formatCurrency(r.amount_credited) + '</td>' +
                '<td class="text-right" style="font-weight:600;">' + formatCurrency(r.tds) + '</td>' +
                '<td>' + esc(r.paid_on || '—') + '</td></tr>';
          }).join('')
        : regEmpty(8, 'Nothing deducted in this period.');

    document.getElementById('reg-tds-suffered').innerHTML = (d.suffered || []).length
        ? d.suffered.map(function (r) {
            return '<tr><td>' + esc(r.date) + '</td><td>' + esc(r.year + ' ' + r.quarter) + '</td>' +
                '<td style="font-family:monospace;">' + esc(r.bill) + '</td>' +
                '<td>' + esc(r.deductor) + '<div style="font-size:0.7rem;color:var(--text-secondary);">' + esc(r.project) + '</div></td>' +
                '<td>' + esc(r.section) + ' @ ' + r.rate + '%</td>' +
                '<td class="text-right">' + formatCurrency(r.amount_credited) + '</td>' +
                '<td class="text-right" style="font-weight:600;">' + formatCurrency(r.tds) + '</td></tr>';
          }).join('')
        : regEmpty(7, 'Nothing deducted from us in this period.');
}
window.loadTdsRegister = loadTdsRegister;

async function loadGuaranteeRegister() {
    var d = await (await fetch('/api/registers/guarantees', { credentials: 'include' })).json();
    var s = d.summary || {};
    document.getElementById('reg-bg-stats').innerHTML =
        statCard('Guarantees held', formatCurrency(s.held || 0)) +
        statCard('Lapsing within 30 days', String(s.lapsing_soon || 0)) +
        statCard('Lapsed', String(s.lapsed || 0)) +
        statCard('No expiry recorded', String(s.no_expiry || 0));
    var tone = { 'in force': 'good', 'lapses within 30 days': 'wait', 'lapsed': 'bad', 'no expiry recorded': 'calm' };
    document.getElementById('reg-bg-body').innerHTML = (d.guarantees || []).length
        ? d.guarantees.map(function (r) {
            return '<tr><td>' + esc(r.contractor) + '</td>' +
                '<td style="font-family:monospace;"><a href="#" onclick="event.preventDefault();openSubcontract(' + r.order_id + ')">' + esc(r.order) + '</a></td>' +
                '<td class="text-right">' + formatCurrency(r.amount) + '</td>' +
                '<td>' + esc(r.valid_until || '—') + '</td>' +
                '<td class="text-right">' + (r.days_left === null ? '—' : r.days_left) + '</td>' +
                '<td>' + esc(r.completion_date || '—') + (r.defect_liability_months ? ' + ' + r.defect_liability_months + ' mo DLP' : '') + '</td>' +
                '<td>' + statusPill(r.state, tone[r.state] || 'calm') + '</td></tr>';
          }).join('')
        : regEmpty(7, 'No bank guarantees on any live order.');
}

async function loadAdvanceRegister() {
    var d = await (await fetch('/api/registers/advances', { credentials: 'include' })).json();
    var s = d.summary || {};
    document.getElementById('reg-adv-stats').innerHTML =
        statCard('Advances given', formatCurrency(s.given || 0)) +
        statCard('Recovered so far', formatCurrency(s.recovered || 0)) +
        statCard('Still out', formatCurrency(s.outstanding || 0)) +
        statCard('Out with no guarantee', formatCurrency(s.unsecured || 0));
    document.getElementById('reg-adv-body').innerHTML = (d.advances || []).length
        ? d.advances.map(function (r) {
            var pc = Math.max(0, Math.min(100, r.percent_recovered));
            return '<tr><td>' + esc(r.contractor) + '</td>' +
                '<td style="font-family:monospace;"><a href="#" onclick="event.preventDefault();openSubcontract(' + r.order_id + ')">' + esc(r.order) + '</a></td>' +
                '<td class="text-right">' + formatCurrency(r.advance) + '</td>' +
                '<td class="text-right">' + r.recovery_percent + '%</td>' +
                '<td class="text-right">' + formatCurrency(r.recovered) +
                    '<div style="height:5px;background:var(--border-color);border-radius:3px;margin-top:4px;overflow:hidden;">' +
                    '<div style="width:' + pc + '%;height:100%;background:var(--primary-color);"></div></div></td>' +
                '<td class="text-right" style="font-weight:600;">' + formatCurrency(r.outstanding) + '</td>' +
                '<td>' + (r.secured_by_bg ? statusPill('BG held', 'good') : statusPill('unsecured', 'wait')) + '</td></tr>';
          }).join('')
        : regEmpty(7, 'No advances on any live order.');
}
