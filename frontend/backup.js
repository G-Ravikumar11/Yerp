/* ===========================================================================
   backup.js - the owner's copy of everything, from Settings.
   =========================================================================== */

async function loadBackupInfo() {
    var box = document.getElementById('backup-widget');
    if (!box) return;
    var res = await fetch('/api/backup/info', { credentials: 'include' });
    if (!res.ok) { box.style.display = 'none'; return; }       // the account holder's alone
    box.style.display = '';
    var d = await res.json();
    var mb = Math.round((d.files_bytes || 0) / 1024 / 1024 * 10) / 10;
    document.getElementById('backup-info').innerHTML =
        '<p style="font-size:0.85rem;margin:0 0 10px;">' + d.rows.toLocaleString('en-IN') + ' records across ' + d.tables +
        ' tables, and ' + d.files + ' photos and documents (' + mb + ' MB).</p>' +
        '<p style="font-size:0.82rem;color:var(--text-secondary);margin:0 0 12px;">' +
        (d.last_backup ? 'Last taken ' + esc(d.last_backup) + ' (' + esc(d.last_backup_details) + ').'
                       : 'No backup taken yet.') +
        ' Passwords, sign-in tokens and API keys are never in it. Keep it somewhere the office computer is not.</p>' +
        '<div style="display:flex;gap:8px;flex-wrap:wrap;">' +
        '<a class="btn btn-primary" href="/api/backup" onclick="setTimeout(loadBackupInfo, 4000)">Download the data</a>' +
        '<a class="btn btn-outline" href="/api/backup?files=1" onclick="setTimeout(loadBackupInfo, 8000)">With photos and drawings</a></div>';
}
window.loadBackupInfo = loadBackupInfo;
