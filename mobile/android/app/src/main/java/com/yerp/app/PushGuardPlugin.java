package com.yerp.app;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

/**
 * Says whether this build has Firebase set up (a google-services.json was in it when it was built). Without it, the push
 * plugin's register and unregister calls throw on a background thread, which JavaScript cannot catch, and the app closes.
 * The page asks first and leaves push alone when the answer is no.
 */
@CapacitorPlugin(name = "PushGuard")
public class PushGuardPlugin extends Plugin {
    @PluginMethod
    public void available(PluginCall call) {
        int id = getContext().getResources().getIdentifier("google_app_id", "string", getContext().getPackageName());
        JSObject out = new JSObject();
        out.put("available", id != 0);
        call.resolve(out);
    }
}
