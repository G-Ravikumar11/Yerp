package com.yerp.app;

import android.os.Bundle;
import android.webkit.CookieManager;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // The app's pages are served from https://localhost and the API from Railway, so the sign-in cookie is a
        // third-party cookie to the WebView. Android drops those by default, which would sign everyone straight out.
        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setAcceptThirdPartyCookies(getBridge().getWebView(), true);
    }
}
