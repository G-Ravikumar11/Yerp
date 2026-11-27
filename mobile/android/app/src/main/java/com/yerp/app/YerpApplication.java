package com.yerp.app;

import android.app.Application;
import android.content.Context;

import java.io.File;
import java.io.FileWriter;
import java.io.PrintWriter;
import java.io.StringWriter;

/**
 * Keeps the last crash. When the app dies, the error is written to a file before the process goes; the next time the app
 * opens, MainActivity shows it, so a person can send it without a cable or a laptop.
 */
public class YerpApplication extends Application {
    static final String CRASH_FILE = "last_crash.txt";

    @Override
    public void onCreate() {
        super.onCreate();
        record(this);
    }

    /**
     * Put in front of whatever handler is there. Called again once the screen is up, because the web view installs its own
     * handler of its own after start-up, and one put in before it is not always passed the crash.
     */
    static void record(final Context context) {
        final Thread.UncaughtExceptionHandler previous = Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler((thread, error) -> {
            try {
                StringWriter text = new StringWriter();
                error.printStackTrace(new PrintWriter(text));
                Throwable root = error;
                for (int i = 0; i < 20 && root.getCause() != null; i++) root = root.getCause();
                String head = "Y ERP crash on thread " + thread.getName() + "\n"
                    + "Cause: " + root + "\n"
                    + "Android " + android.os.Build.VERSION.RELEASE + " (API " + android.os.Build.VERSION.SDK_INT + ")\n"
                    + android.os.Build.MANUFACTURER + " " + android.os.Build.MODEL + "\n\n";
                String body = text.toString();
                if (body.length() > 6000) body = body.substring(0, 6000);
                try (FileWriter out = new FileWriter(new File(context.getFilesDir(), CRASH_FILE))) {
                    out.write(head + body);
                }
            } catch (Throwable ignored) {
                // Recording must never make the crash worse.
            }
            if (previous != null) previous.uncaughtException(thread, error);
        });
    }
}
