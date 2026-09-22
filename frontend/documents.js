/* ===========================================================================
   documents.js - every bill and order as the sheet of paper it becomes.

   The RA bill is the document the business lives on, and until now the only
   way to look at one was to download a workbook - which is where the bill
   then got finished, formatted and sent from. Now each document has a page:
   the abstract of cost, the deductions in the order they are made, the
   figure in words, the signature blocks. Print it, or read it here.

   One view, one renderer per kind. They share the work order's sheet styles
   so every document that leaves the office looks like it came from the same
   place.
   =========================================================================== */

var DOC = { kind: null, id: null, data: null, back: null };

var DOC_SOURCES = {
    'ra-bill':  { url: function (id) { return '/api/ra-bills/' + id; },  pick: 'bill',  render: function (d) { return docRaBill(d); },       title: 'Running Account Bill' },
    'sub-bill': { url: function (id) { return '/api/sub-bills/' + id; }, pick: null,    render: function (d) { return docSubBill(d); },      title: 'Subcontractor RA Bill' },
    'po':       { url: function (id) { return '/api/purchase-orders/' + id; }, pick: null, render: function (d) { return docPurchaseOrder(d); }, title: 'Purchase Order' },
    'grn':      { url: function (id) { return '/api/grn/' + id; },       pick: null,    render: function (d) { return docGrn(d); },          title: 'Goods Receipt' },
};

async function openDocument(kind, id) {
    var src = DOC_SOURCES[kind];
    if (!src) return;
    var host = document.getElementById('document-body');
    if (!host) return;
    DOC.kind = kind; DOC.id = id;
    DOC.back = (typeof currentView === 'string' && currentView) || null;
    host.innerHTML = '<p style="text-align:center;padding:40px;color:var(--text-secondary);">Laying out the document...</p>';
    showView('document-view');
    var res = await fetch(src.url(id), { credentials: 'include' });
    if (!res.ok) { host.innerHTML = '<p style="text-align:center;padding:40px;">Could not load it.</p>'; return; }
    var out = await res.json();
    DOC.data = src.pick ? out[src.pick] : out;
    document.getElementById('document-title').textContent = src.title;
    host.innerHTML = src.render(DOC.data);
    window.scrollTo(0, 0);
}
window.openDocument = openDocument;

function docBack() {
    showView(DOC.back || 'dashboard-view');
}
window.docBack = docBack;

/* --- Shared pieces -------------------------------------------------------- */

function docNl(s) { return esc(s || '').replace(/\n/g, '<br>'); }

function docDate(v) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(v || ''));
    return m ? m[3] + '/' + m[2] + '/' + m[1] : esc(v || '');
}

function docQty(v) {
    var n = Number(v || 0);
    return n.toLocaleString('en-IN', { maximumFractionDigits: 3 });
}

function docRate(v) {
    return Number(v || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
}

function docHead(our, title, number, extra) {
    our = our || {};
    return '<div class="wo-head"><div>' +
        (our.logo_url ? '<img src="' + esc(our.logo_url) + '" alt="" style="max-height:56px;max-width:180px;margin-bottom:6px;display:block;">' : '') +
        '<div class="wo-head-name">' + esc(our.name || '') + '</div>' +
        (our.address ? '<div class="wo-muted" style="font-size:0.74rem;">' + docNl(our.address) + '</div>' : '') +
        (our.gstin ? '<div class="wo-muted" style="font-size:0.72rem;">GSTIN: ' + esc(our.gstin) + '</div>' : '') +
        '</div><div><div class="wo-doctitle">' + esc(title) + '</div>' +
        '<div class="wo-number" style="text-align:right;">' + esc(number) + '</div>' +
        (extra || '') + '</div></div>';
}

function docFacts(pairs) {
    return '<div class="wo-facts">' + pairs.filter(function (p) { return p[1] !== undefined && p[1] !== null && p[1] !== ''; })
        .map(function (p) {
            return '<div><span class="wo-label">' + esc(p[0]) + '</span><div>' + p[1] + '</div></div>';
        }).join('') + '</div>';
}

function docWatermark(status) {
    var text = { DRAFT: 'DRAFT', SUBMITTED: 'SUBMITTED - NOT CERTIFIED', CANCELLED: 'CANCELLED' }[status];
    return text ? '<div class="wo-watermark"><span>' + text + '</span></div>' : '';
}

function docSigns(list) {
    return '<div class="wo-signs">' + list.map(function (s) {
        return '<div class="wo-sign"><span class="wo-label">' + esc(s[0]) + '</span>' +
            '<div><div class="wo-sign-name">' + (esc(s[1]) || '&nbsp;') + '</div>' +
            '<div class="wo-label" style="letter-spacing:0;text-transform:none;">' + esc(s[2] || '') + '</div></div></div>';
    }).join('') + '</div>';
}

function docMoneyRow(label, value, opts) {
    opts = opts || {};
    return '<tr' + (opts.strong ? ' style="font-weight:700;"' : '') + '><td>' + label + '</td>' +
        '<td style="text-align:right;white-space:nowrap;">' + (opts.less ? '(' + formatCurrency(value) + ')' : formatCurrency(value)) + '</td></tr>';
}

function docGstRows(d, taxable) {
    // The split as it was charged, never as a single "tax" line.
    var rows = '';
    if (d.igst_amount) rows += docMoneyRow('Add: IGST @ ' + (d.tax_percent || d.gst_percent) + '%', d.igst_amount);
    else if (d.cgst_amount || d.sgst_amount) {
        var half = (d.tax_percent || d.gst_percent || 0) / 2;
        rows += docMoneyRow('Add: CGST @ ' + half + '%', d.cgst_amount) +
                docMoneyRow('Add: SGST @ ' + half + '%', d.sgst_amount);
    } else if (d.tax_amount || d.gst_amount) {
        rows += docMoneyRow('Add: GST @ ' + (d.tax_percent || d.gst_percent) + '%', d.tax_amount || d.gst_amount);
    }
    return rows;
}

/* --- The client's RA bill ------------------------------------------------ */

function docAbstract(lines, uptoLabel) {
    /* The abstract of cost: every ordered line, what has been done to date,
       what earlier bills took, what this one claims. The columns a client's
       engineer checks in the order he checks them. */
    var body = lines.map(function (l, i) {
        return '<tr><td>' + (i + 1) + '</td>' +
            '<td>' + esc(l.fg_code || l.activity_no || '') + '</td>' +
            '<td>' + esc(l.description) + '</td>' +
            '<td>' + esc(l.uom) + '</td>' +
            '<td class="num">' + docQty(l.ordered_qty) + '</td>' +
            '<td class="num">' + docRate(l.rate) + '</td>' +
            '<td class="num">' + docQty(l.measured_to_date) + '</td>' +
            '<td class="num">' + docQty(l.previously_billed_qty) + '</td>' +
            '<td class="num">' + docQty(l.this_bill_qty) + '</td>' +
            '<td class="num">' + formatCurrency(l.amount) + '</td>' +
            '<td class="num">' + formatCurrency(l.upto_date_amount) + '</td></tr>';
    }).join('');
    var thisTotal = lines.reduce(function (t, l) { return t + (l.amount || 0); }, 0);
    var uptoTotal = lines.reduce(function (t, l) { return t + (l.upto_date_amount || 0); }, 0);
    return '<div style="overflow-x:auto;"><table class="wo-table doc-abstract" style="margin-top:8px;font-size:0.72rem;"><thead><tr>' +
        '<th>#</th><th>Code</th><th style="min-width:180px;">Description of work</th><th>UOM</th><th class="num">Ordered</th>' +
        '<th class="num">Rate</th><th class="num">' + (uptoLabel || 'Up to date') + '</th><th class="num">Previous</th>' +
        '<th class="num">This bill</th><th class="num">This bill ₹</th><th class="num">Up to date ₹</th>' +
        '</tr></thead><tbody>' + (body || '<tr><td colspan="11" style="text-align:center;padding:12px;">Nothing claimed.</td></tr>') +
        '</tbody><tfoot><tr style="font-weight:700;"><td colspan="9" style="text-align:right;">Total</td>' +
        '<td class="num">' + formatCurrency(thisTotal) + '</td><td class="num">' + formatCurrency(uptoTotal) + '</td></tr></tfoot></table></div>';
}

function docRaBill(b) {
    var our = b.our || {}, party = b.client_party || {}, wo = b.work_order_detail || {};
    var afterHold = b.this_bill - b.retention_amount - b.advance_recovery - b.other_deductions;
    return '<div class="wo-sheet">' + docWatermark(b.status) +
        docHead(our, 'RUNNING ACCOUNT BILL', b.number,
            '<div class="wo-muted" style="font-size:0.7rem;text-align:right;">RA ' + b.sequence + '</div>') +

        '<div class="wo-cols" style="margin-top:14px;"><div>' +
            '<span class="wo-label">Bill to</span>' +
            '<div style="font-weight:700;margin-top:2px;">' + esc(party.name || '') + '</div>' +
            (party.site ? '<div class="wo-muted">Site: ' + docNl(party.site) + '</div>' : '') +
            (b.place_of_supply_name ? '<div class="wo-muted" style="font-size:0.72rem;margin-top:3px;">Place of supply: ' +
                esc(b.place_of_supply_name) + ' (' + esc(b.place_of_supply) + ') &nbsp;|&nbsp; SAC 9954</div>' : '') +
        '</div><div>' + docFacts([
            ['Bill date', docDate(b.certified_at || b.created_at)],
            ['Period', b.period_from ? docDate(b.period_from) + ' – ' + docDate(b.period_to) : 'Up to ' + docDate(b.period_to)],
            ['Project', esc(b.project)],
            ['Work order', esc(wo.number || b.work_order) + (wo.date ? ' of ' + docDate(wo.date) : '')],
            ['Your reference', esc(wo.reference || '')],
            ['Order value', wo.value ? formatCurrency(wo.value) : ''],
            ['Status', esc(b.status)]]) + '</div></div>' +

        '<div class="wo-section">Abstract of cost</div>' +
        docAbstract(b.lines || []) +

        '<div class="wo-cols" style="margin-top:16px;align-items:start;"><div>' +
            '<div class="wo-section" style="margin-top:0;">Summary of the account</div>' +
            '<table class="wo-money"><tbody>' +
                docMoneyRow('Value of work done to date', b.gross_to_date) +
                docMoneyRow('Less: claimed in earlier bills', b.previously_billed, { less: true }) +
                docMoneyRow('Value of work in this bill', b.this_bill, { strong: true }) +
            '</tbody></table>' +
        '</div><div>' +
            '<div class="wo-section" style="margin-top:0;">Deductions and tax</div>' +
            '<table class="wo-money"><tbody>' +
                docMoneyRow('Work in this bill', b.this_bill) +
                (b.retention_amount ? docMoneyRow('Less: retention @ ' + b.retention_percent + '%', b.retention_amount, { less: true }) : '') +
                (b.advance_recovery ? docMoneyRow('Less: mobilisation advance recovered', b.advance_recovery, { less: true }) : '') +
                (b.other_deductions ? docMoneyRow('Less: other deductions' + (b.deduction_notes ? ' (' + esc(b.deduction_notes) + ')' : ''), b.other_deductions, { less: true }) : '') +
                docMoneyRow('Taxable value', afterHold) +
                docGstRows(b, afterHold) +
                (b.tds_amount ? docMoneyRow('Less: TDS @ ' + b.tds_percent + '% (to be deducted by the client)', b.tds_amount, { less: true }) : '') +
                docMoneyRow('Net amount payable', b.net_payable, { strong: true }) +
            '</tbody></table>' +
        '</div></div>' +
        '<div class="wo-band" style="margin-top:10px;font-size:0.78rem;"><strong>In words:</strong> ' + esc(b.amount_in_words || '') + '</div>' +
        (b.remarks ? '<p class="wo-muted" style="margin-top:8px;font-size:0.74rem;">' + docNl(b.remarks) + '</p>' : '') +
        '<p class="wo-muted" style="margin-top:10px;font-size:0.7rem;">Quantities are as recorded in the measurement book and jointly ' +
        'verified. Retention is held per the contract and released on completion of the defect liability period.</p>' +

        docSigns([['Prepared by', '', 'Billing Engineer'], ['Checked by', '', 'Project Manager'],
                  ['Certified by', b.certified_by_name || '', b.certified_at ? docDate(b.certified_at) : "Client's Engineer"],
                  ['For ' + (our.name || ''), '', 'Authorised signatory']]) +
        '</div>';
}

/* --- The gang's RA bill --------------------------------------------------- */

function docSubBill(b) {
    var our = b.our || {}, con = b.contractor_detail || {}, od = b.order_detail || {};
    var afterHold = b.this_bill - b.retention_amount - b.advance_recovery - b.other_deductions;
    return '<div class="wo-sheet">' + docWatermark(b.status) +
        docHead(our, 'SUBCONTRACTOR RA BILL', b.number,
            '<div class="wo-muted" style="font-size:0.7rem;text-align:right;">RA ' + b.sequence + ' against ' + esc(od.number || b.order) + '</div>') +

        '<div class="wo-cols" style="margin-top:14px;"><div>' +
            '<span class="wo-label">Contractor</span>' +
            '<div style="font-weight:700;margin-top:2px;">' + esc(con.name || b.contractor || '') + '</div>' +
            (con.contact ? '<div>Attn: ' + esc(con.contact) + '</div>' : '') +
            (con.address ? '<div class="wo-muted">' + docNl(con.address) + '</div>' : '') +
            '<div class="wo-muted" style="font-size:0.72rem;margin-top:3px;">' +
                [con.gstin ? 'GSTIN: ' + esc(con.gstin) : '', con.pan ? 'PAN: ' + esc(con.pan) : ''].filter(Boolean).join(' &nbsp;|&nbsp; ') + '</div>' +
        '</div><div>' + docFacts([
            ['Bill date', docDate(b.certified_at || b.created_at)],
            ['Period', b.period_from ? docDate(b.period_from) + ' – ' + docDate(b.period_to) : 'Up to ' + docDate(b.period_to)],
            ['Project', esc(b.project)], ['Site', esc(b.site || '')],
            ['Order value', od.value ? formatCurrency(od.value) : ''],
            ['Status', esc(b.status)]]) + '</div></div>' +
        (od.subject ? '<div class="wo-band" style="margin-top:12px;"><strong>Work:</strong> ' + esc(od.subject) + '</div>' : '') +

        '<div class="wo-section">Abstract of work done</div>' +
        docAbstract(b.lines || []) +

        '<div class="wo-cols" style="margin-top:16px;align-items:start;"><div>' +
            '<div class="wo-section" style="margin-top:0;">Summary of the account</div>' +
            '<table class="wo-money"><tbody>' +
                docMoneyRow('Value of work done to date', b.gross_to_date) +
                docMoneyRow('Less: paid in earlier bills', b.previously_billed, { less: true }) +
                docMoneyRow('Value of work in this bill', b.this_bill, { strong: true }) +
            '</tbody></table>' +
        '</div><div>' +
            '<div class="wo-section" style="margin-top:0;">Deductions and tax</div>' +
            '<table class="wo-money"><tbody>' +
                docMoneyRow('Work in this bill', b.this_bill) +
                (b.retention_amount ? docMoneyRow('Less: retention held @ ' + b.retention_percent + '%', b.retention_amount, { less: true }) : '') +
                (b.advance_recovery ? docMoneyRow('Less: advance recovered', b.advance_recovery, { less: true }) : '') +
                (b.other_deductions ? docMoneyRow('Less: other deductions' + (b.deduction_notes ? ' (' + esc(b.deduction_notes) + ')' : ''), b.other_deductions, { less: true }) : '') +
                docMoneyRow('Taxable value', afterHold) +
                docGstRows(b, afterHold) +
                (b.tds_amount ? docMoneyRow('Less: TDS @ ' + b.tds_percent + '% u/s 194C', b.tds_amount, { less: true }) : '') +
                (b.labour_cess_amount ? docMoneyRow('Less: labour welfare cess @ ' + b.labour_cess_percent + '%', b.labour_cess_amount, { less: true }) : '') +
                docMoneyRow('Net amount payable', b.net_payable, { strong: true }) +
            '</tbody></table>' +
        '</div></div>' +
        '<div class="wo-band" style="margin-top:10px;font-size:0.78rem;"><strong>In words:</strong> ' + esc(b.amount_in_words || '') + '</div>' +
        (b.paid_at ? '<p class="wo-muted" style="margin-top:8px;font-size:0.74rem;">Paid on ' + docDate(b.paid_at) +
            (b.paid_reference ? ', ref. ' + esc(b.paid_reference) : '') + '.</p>' : '') +
        docSigns([['Prepared by', '', 'Billing Engineer'], ['Certified by', b.certified_by_name || '', 'Project Manager'],
                  ['Received by', '', 'For the contractor'], ['Approved for payment', '', 'For ' + (our.name || '')]]) +
        '</div>';
}

/* --- The purchase order --------------------------------------------------- */

function docPurchaseOrder(o) {
    var our = o.our || {};
    var lines = (o.line_items || []).map(function (l, i) {
        var amt = (l.qty || 0) * (l.price || 0);
        return '<tr><td>' + (i + 1) + '</td><td>' + esc(l.item_code || '') + '</td>' +
            '<td>' + esc(l.description) + '</td><td>' + esc(l.uom || '') + '</td>' +
            '<td class="num">' + docQty(l.qty) + '</td><td class="num">' + docRate(l.price) + '</td>' +
            '<td class="num">' + esc(String(l.tax_rate || '')) + '</td><td class="num">' + formatCurrency(amt) + '</td></tr>';
    }).join('');
    return '<div class="wo-sheet">' + (o.status === 'Draft' ? docWatermark('DRAFT') : '') +
        docHead(our, 'PURCHASE ORDER', o.number) +
        '<div class="wo-cols" style="margin-top:14px;"><div>' +
            '<span class="wo-label">To</span>' +
            '<div style="font-weight:700;margin-top:2px;">' + esc(o.supplier_name || '') + '</div>' +
            (o.supplier_email ? '<div class="wo-muted">' + esc(o.supplier_email) + '</div>' : '') +
            (o.deliver_to ? '<div style="margin-top:8px;"><span class="wo-label">Deliver to</span><div class="wo-muted">' + docNl(o.deliver_to) + '</div></div>' : '') +
        '</div><div>' + docFacts([
            ['Date', docDate(o.issue_date)], ['Needed by', docDate(o.needed_by)],
            ['Project', esc(o.job_name || '')], ['Reference', esc(o.reference || '')],
            ['Status', esc(o.status)]]) + '</div></div>' +
        '<div class="wo-section">Items ordered</div>' +
        '<table class="wo-table" style="margin-top:8px;"><thead><tr><th>#</th><th>Code</th><th>Description</th><th>UOM</th>' +
        '<th class="num">Qty</th><th class="num">Rate</th><th class="num">Tax</th><th class="num">Amount</th></tr></thead>' +
        '<tbody>' + (lines || '<tr><td colspan="8" style="text-align:center;padding:12px;">No items.</td></tr>') + '</tbody></table>' +
        '<div class="wo-cols" style="margin-top:14px;align-items:start;"><div>' +
            (o.notes ? '<span class="wo-label">Terms and notes</span><div class="wo-muted" style="font-size:0.76rem;">' + docNl(o.notes) + '</div>' : '') +
        '</div><div><table class="wo-money"><tbody>' +
            docMoneyRow('Value of goods', o.amount) +
            docMoneyRow('Add: GST', o.tax_amount) +
            docMoneyRow('Order total', o.total, { strong: true }) +
        '</tbody></table>' +
        '<div class="wo-band" style="margin-top:8px;font-size:0.76rem;"><strong>In words:</strong> ' + esc(o.amount_in_words || '') + '</div></div></div>' +
        docSigns([['Prepared by', o.submitted_by_name || '', 'Stores'], ['Approved by', '', 'Project Head'],
                  ['For ' + (our.name || ''), '', 'Authorised signatory'], ['Accepted by', '', 'For the supplier']]) +
        '</div>';
}

/* --- The goods receipt ---------------------------------------------------- */

function docGrn(g) {
    var lines = (g.lines || []).map(function (l, i) {
        return '<tr><td>' + (i + 1) + '</td><td>' + esc(l.item_code || '') + '</td><td>' + esc(l.description) + '</td>' +
            '<td>' + esc(l.uom || '') + '</td><td class="num">' + docQty(l.ordered_qty) + '</td>' +
            '<td class="num">' + docQty(l.previously_received) + '</td><td class="num">' + docQty(l.received_qty) + '</td>' +
            '<td class="num">' + docQty(l.accepted_qty) + '</td><td class="num">' + docQty(l.rejected_qty) +
            (l.rejection_reason ? '<div style="font-size:0.66rem;color:#b45309;">' + esc(l.rejection_reason) + '</div>' : '') + '</td>' +
            '<td class="num">' + formatCurrency(l.amount) + '</td></tr>';
    }).join('');
    return '<div class="wo-sheet">' + (g.status === 'DRAFT' ? docWatermark('DRAFT') : '') +
        docHead(g.our || {}, 'GOODS RECEIPT NOTE', g.number) +
        '<div class="wo-cols" style="margin-top:14px;"><div>' +
            '<span class="wo-label">Received from</span>' +
            '<div style="font-weight:700;margin-top:2px;">' + esc(g.supplier_name || '') + '</div>' +
            '<div class="wo-muted" style="font-size:0.74rem;">Against PO ' + esc(g.purchase_order || '') +
            (g.challan_number ? ' &nbsp;|&nbsp; Challan ' + esc(g.challan_number) : '') +
            (g.invoice_number ? ' &nbsp;|&nbsp; Invoice ' + esc(g.invoice_number) : '') + '</div>' +
        '</div><div>' + docFacts([
            ['Received on', docDate(g.received_on)], ['Project', esc(g.project || '')],
            ['Store', esc(g.store_location || '')], ['Vehicle', esc(g.vehicle_number || '')],
            ['Received by', esc(g.received_by_name || '')], ['Inspected by', esc(g.inspected_by || '')],
            ['Status', esc(g.status)]]) + '</div></div>' +
        '<div class="wo-section">Material received</div>' +
        '<table class="wo-table" style="margin-top:8px;font-size:0.72rem;"><thead><tr><th>#</th><th>Code</th><th>Description</th><th>UOM</th>' +
        '<th class="num">Ordered</th><th class="num">Earlier</th><th class="num">Received</th><th class="num">Accepted</th><th class="num">Rejected</th><th class="num">Value</th></tr></thead>' +
        '<tbody>' + (lines || '<tr><td colspan="10" style="text-align:center;padding:12px;">No lines.</td></tr>') + '</tbody>' +
        '<tfoot><tr style="font-weight:700;"><td colspan="9" style="text-align:right;">Accepted value</td><td class="num">' + formatCurrency(g.accepted_value) + '</td></tr></tfoot></table>' +
        (g.remarks ? '<p class="wo-muted" style="margin-top:8px;font-size:0.74rem;">' + docNl(g.remarks) + '</p>' : '') +
        docSigns([['Received by', g.received_by_name || '', 'Storekeeper'], ['Inspected by', g.inspected_by || '', 'Site Engineer'],
                  ['Delivered by', '', "Supplier's representative"], ['Posted to stock', g.posted_at ? docDate(g.posted_at) : '', '']]) +
        '</div>';
}
