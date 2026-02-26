"""
patch_android.py
Patches the generated Android project to add:
  - Share intent filter (SEND text/plain)
  - Deep link intent filter (earth.app.goo.gl, google.com/maps)
  - Internet + cleartext traffic permissions
  - MainActivity code to pass shared URLs into the WebView
"""

import os
import re

# ── Patch AndroidManifest.xml ──────────────────────────────────────────────
manifest_path = "android/app/src/main/AndroidManifest.xml"

with open(manifest_path, "r") as f:
    manifest = f.read()

# Add cleartext traffic if not present
if 'usesCleartextTraffic' not in manifest:
    manifest = manifest.replace(
        "android:label=",
        'android:usesCleartextTraffic="true"\n        android:label='
    )

# Intent filters to add inside the <activity> tag
intent_filters = """
        <!-- Share text/url from other apps (Google Maps, Earth, etc.) -->
        <intent-filter>
            <action android:name="android.intent.action.SEND" />
            <category android:name="android.intent.category.DEFAULT" />
            <data android:mimeType="text/plain" />
        </intent-filter>

        <!-- Deep link: earth.app.goo.gl -->
        <intent-filter android:autoVerify="true">
            <action android:name="android.intent.action.VIEW" />
            <category android:name="android.intent.category.DEFAULT" />
            <category android:name="android.intent.category.BROWSABLE" />
            <data android:scheme="https" android:host="earth.app.goo.gl" />
        </intent-filter>

        <!-- Deep link: google.com/maps -->
        <intent-filter android:autoVerify="true">
            <action android:name="android.intent.action.VIEW" />
            <category android:name="android.intent.category.DEFAULT" />
            <category android:name="android.intent.category.BROWSABLE" />
            <data android:scheme="https" android:host="www.google.com" android:pathPrefix="/maps" />
        </intent-filter>
"""

# Insert before the closing </activity> tag
manifest = manifest.replace("</activity>", intent_filters + "\n        </activity>", 1)

with open(manifest_path, "w") as f:
    f.write(manifest)

print("✓ Patched AndroidManifest.xml")


# ── Patch MainActivity.java ────────────────────────────────────────────────
main_act_path = None
for root, dirs, files in os.walk("android/app/src/main/java"):
    for file in files:
        if file == "MainActivity.java":
            main_act_path = os.path.join(root, file)
            break

if not main_act_path:
    print("✗ WARNING: MainActivity.java not found — share intent won't work")
else:
    with open(main_act_path, "r") as f:
        main = f.read()

    # Add required imports after the package declaration
    if "import android.content.Intent;" not in main:
        main = re.sub(
            r"(package .+?;)",
            r"\1\n\nimport android.content.Intent;\nimport android.os.Bundle;",
            main,
            count=1
        )

    # Insert handler methods into the class body
    handler_code = r"""
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // Delay so the WebView has time to load before we inject the URL
        getBridge().getWebView().postDelayed(() -> handleIncomingIntent(getIntent()), 2000);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        getBridge().getWebView().postDelayed(() -> handleIncomingIntent(intent), 500);
    }

    private void handleIncomingIntent(Intent intent) {
        if (intent == null) return;
        String action = intent.getAction();
        String sharedUrl = null;

        if (Intent.ACTION_SEND.equals(action) && "text/plain".equals(intent.getType())) {
            sharedUrl = intent.getStringExtra(Intent.EXTRA_TEXT);
        } else if (Intent.ACTION_VIEW.equals(action) && intent.getData() != null) {
            sharedUrl = intent.getData().toString();
        }

        if (sharedUrl == null) return;

        // Escape for JS string — replace backslashes first, then single quotes
        final String safeUrl = sharedUrl.replace("\\", "\\\\").replace("'", "\\'");
        getBridge().getWebView().post(() ->
            getBridge().getWebView().evaluateJavascript(
                "if(window.handleSharedUrl){window.handleSharedUrl('" + safeUrl + "')}", null
            )
        );
    }
"""

    # Insert into the class body (after the opening brace of the class)
    main = re.sub(
        r"(public class MainActivity extends BridgeActivity \{)",
        r"\1" + handler_code,
        main,
        count=1
    )

    with open(main_act_path, "w") as f:
        f.write(main)

    print(f"✓ Patched {main_act_path}")


# ── Add network_security_config.xml ──────────────────────────────────────
xml_dir = "android/app/src/main/res/xml"
os.makedirs(xml_dir, exist_ok=True)

net_security = """<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <base-config cleartextTrafficPermitted="true">
        <trust-anchors>
            <certificates src="system" />
        </trust-anchors>
    </base-config>
    <domain-config cleartextTrafficPermitted="true">
        <domain includeSubdomains="true">cbk0.google.com</domain>
        <domain includeSubdomains="true">lh3.googleusercontent.com</domain>
        <domain includeSubdomains="true">maps.googleapis.com</domain>
    </domain-config>
</network-security-config>
"""

with open(os.path.join(xml_dir, "network_security_config.xml"), "w") as f:
    f.write(net_security)

# Reference it in manifest
with open(manifest_path, "r") as f:
    manifest = f.read()

if "networkSecurityConfig" not in manifest:
    manifest = manifest.replace(
        'android:usesCleartextTraffic="true"',
        'android:usesCleartextTraffic="true"\n        android:networkSecurityConfig="@xml/network_security_config"'
    )
    with open(manifest_path, "w") as f:
        f.write(manifest)

print("✓ Added network_security_config.xml")
print("\nAll patches applied successfully!")
