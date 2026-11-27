package com.yerp.app;

import android.app.AlertDialog;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.os.Bundle;
import android.webkit.CookieManager;

import com.getcapacitor.BridgeActivity;

import java.io.File;
import java.io.FileInputStream;
import java.io.ByteArrayOutputStream;

public class MainActivity extends BridgeActivity {

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(PushGuardPlugin.class);
        super.onCreate(savedInstanceState);
        YerpApplication.record(this);
        // The app's pages are served from https://localhost and the API from Railway, so the sign-in cookie is a
        // third-party cookie to the WebView. Android drops those by default, which would sign everyone straight out.
        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setAcceptThirdPartyCookies(getBridge().getWebView(), true);
    }

    @Override
    public void onStart() {
        super.onStart();
        showLastCrash();
    }

    /** If the app died last time, say so and show the error, so it can be copied and sent. */
    private void showLastCrash() {
        try {
            File file = new File(getFilesDir(), YerpApplication.CRASH_FILE);
            if (!file.exists()) return;
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            try (FileInputStream in = new FileInputStream(file)) {
                byte[] buf = new byte[4096];
                int n;
                while ((n = in.read(buf)) > 0) bytes.write(buf, 0, n);
            }
            final String text = bytes.toString("UTF-8");
            file.delete();
            new AlertDialog.Builder(this)
                .setTitle("Y ERP closed unexpectedly last time")
                .setMessage(text)
                .setPositiveButton("Copy", (d, w) -> {
                    ClipboardManager clip = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
                    if (clip != null) clip.setPrimaryClip(ClipData.newPlainText("Y ERP crash", text));
                })
                .setNegativeButton("Close", null)
                .show();
        } catch (Throwable ignored) {
            // Never stop the app opening because of this.
        }
    }
}
