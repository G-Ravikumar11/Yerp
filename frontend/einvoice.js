/* ===========================================================================
   einvoice.js - a bill's e-invoice: the file for the portal, then the IRN,
   acknowledgement and signed QR the portal gives back.
   =========================================================================== */

var EINV = { type: '', id: 0 };

async function einvoiceBox(docType, id) {
    EINV.type = docType; EINV.id = id;
    var res = await fetch('/api/einvoice/' + docType + '/' + id, { credentials: 'include' });
    var d = await res.json();
    if (!res.ok) { showToast(d.detail || 'Could not open it', 'error'); return; }
    var box = document.getElementById('einv-modal');
    if (!box) {
        box = document.createElement('div');
        box.id = 'einv-modal';
        box.className = 'modal-overlay';
        document.body.appendChild(box);
    }
    var inner, foot = '';
    var mono = 'font-family:monospace;word-break:break-all;';
    if (d.irn) {
        var r = d.irn;
        inner = '<div style="display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap;">' +
            '<img src="' + r.qr_url + '" alt="Signed QR" style="width:150px;height:150px;border:1px solid var(--border-color);border-radius:6px;">' +
            '<div style="flex:1;min-width:220px;font-size:0.85rem;">' +
                '<div style="color:var(--success-color);font-weight:700;margin-bottom:6px;">Registered on the e-invoice portal</div>' +
                '<div style="color:var(--text-secondary);font-size:0.75rem;">IRN</div><div style="' + mono + 'font-size:0.78rem;">' + esc(r.irn) + '</div>' +
                '<div style="margin-top:6px;"><span style="color:var(--text-secondary);font-size:0.75rem;">Ack no.</span> ' + esc(r.ack_no) +
                ' &nbsp; <span style="color:var(--text-secondary);font-size:0.75rem;">on</span> ' + esc(r.ack_date) + '</div>' +
                (r.ewb_no ? '<div><span style="color:var(--text-secondary);font-size:0.75rem;">E-way bill</span> ' + esc(r.ewb_no) + '</div>' : '') +
                '<div style="margin-top:6px;font-size:0.75rem;color:var(--text-secondary);">Recorded by ' + esc(r.created_by_name) +
                '. The QR prints on the bill.</div></div></div>';
        foot = r.cancellable ? '<button class="btn btn-outline" style="color:var(--danger-color);" onclick="einvoiceCancel(' + r.id + ')">Cancelled on the portal</button>' : '';
    } else if (d.ready) {
        var v = d.payload.ValDtls;
        inner = '<table class="data-table" style="margin:0 0 10px;"><tbody>' +
            '<tr><td>Invoice no.</td><td class="text-right" style="font-family:monospace;">' + esc(d.payload.DocDtls.No) + '</td></tr>' +
            '<tr><td>Buyer GSTIN</td><td class="text-right" style="font-family:monospace;">' + esc(d.payload.BuyerDtls.Gstin) + '</td></tr>' +
            '<tr><td>Taxable value</td><td class="text-right">' + formatCurrency(v.AssVal) + '</td></tr>' +
            '<tr><td>GST</td><td class="text-right">' + formatCurrency(v.CgstVal + v.SgstVal + v.IgstVal) + '</td></tr>' +
            '<tr><td><strong>Invoice value</strong></td><td class="text-right"><strong>' + formatCurrency(v.TotInvVal) + '</strong></td></tr>' +
            '</tbody></table>' +
            '<p style="font-size:0.8rem;color:var(--text-secondary);margin:0 0 12px;">1. Download the file and upload it at einvoice1.gst.gov.in. ' +
            '2. Paste back what the portal returns, so the IRN and QR go on the bill.</p>' +
            '<div class="form-group"><label>The portal\'s response (JSON)</label>' +
            '<textarea id="einv-response" class="form-control" rows="4" placeholder=\'{"AckNo": ..., "AckDt": ..., "Irn": ..., "SignedQRCode": ...}\'></textarea></div>' +
            '<details style="font-size:0.84rem;"><summary style="cursor:pointer;">Or type the fields in</summary>' +
                '<div class="form-group" style="margin-top:8px;"><label>IRN</label><input id="einv-irn" class="form-control" style="font-family:monospace;"></div>' +
                '<div class="form-row"><div class="form-group"><label>Ack no.</label><input id="einv-ack" class="form-control"></div>' +
                '<div class="form-group"><label>Ack date and time</label><input id="einv-ackdt" class="form-control" placeholder="26/09/2026 11:02:00"></div></div>' +
                '<div class="form-group"><label>Signed QR code</label><textarea id="einv-qr" class="form-control" rows="3"></textarea></div>' +
            '</details>';
        foot = '<a class="btn btn-outline" href="/api/einvoice/' + docType + '/' + id + '/json">Download the file</a>' +
            '<button class="btn btn-primary" onclick="einvoiceSave()">Record the IRN</button>';
    } else {
        inner = '<p>The portal will not take this bill yet. Still needed:</p><ul style="margin:8px 0 0 18px;">' +
            d.missing.map(function (m) { return '<li style="margin:4px 0;">' + esc(m) + '</li>'; }).join('') + '</ul>';
    }
    if ((d.history || []).length) {
        inner += '<p style="margin-top:12px;font-size:0.74rem;color:var(--text-secondary);">Earlier: ' + d.history.map(function (h) {
            return 'IRN ' + esc(h.irn.slice(0, 12)) + '... cancelled ' + esc(h.cancelled_at.slice(0, 10)) + ' (' + esc(h.cancel_reason) + ')';
        }).join('; ') + '</p>';
    }
    box.innerHTML = '<div class="modal" style="max-width:560px;"><div class="modal-header"><h3>e-Invoice - ' + esc(d.number) + '</h3>' +
        '<button class="modal-close" onclick="closeModal(\'einv-modal\')">&times;</button></div>' +
        '<div class="modal-body">' + inner + '</div><div class="modal-footer">' +
        '<button class="btn btn-outline" onclick="closeModal(\'einv-modal\')">Close</button>' + foot + '</div></div>';
    box.style.display = 'flex';
}
window.einvoiceBox = einvoiceBox;

async function einvoiceSave() {
    var v = function (id) { var el = document.getElementById(id); return el ? el.value.trim() : ''; };
    var body = v('einv-response') ? { response: v('einv-response') }
        : { irn: v('einv-irn'), ack_no: v('einv-ack'), ack_date: v('einv-ackdt'), signed_qr: v('einv-qr') };
    var res = await fetch('/api/einvoice/' + EINV.type + '/' + EINV.id + '/irn', { method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Not recorded', 'error'); return; }
    showToast(out.message, 'success');
    einvoiceBox(EINV.type, EINV.id);
}
window.einvoiceSave = einvoiceSave;

async function einvoiceCancel(irnId) {
    var reason = prompt('The reason you gave on the portal when cancelling (duplicate, data entry mistake, order cancelled):');
    if (!reason) return;
    var res = await fetch('/api/einvoice/irns/' + irnId + '/cancel', { method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason: reason }) });
    var out = await res.json();
    if (!res.ok) { showToast(out.detail || 'Not recorded', 'error'); return; }
    showToast(out.message, 'success');
    einvoiceBox(EINV.type, EINV.id);
}
window.einvoiceCancel = einvoiceCancel;
