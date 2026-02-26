"""
patch_android.py
Patches the generated Android project to add:
  - Share intent filter (SEND text/plain)
  - Deep link intent filter (earth.app.goo.gl, google.com/maps)
  - Cleartext traffic + network security config
  - Rewrites MainActivity.java cleanly to handle share/view intents
"""

import os
import re

# ── Patch AndroidManifest.xml ──────────────────────────────────────────────
manifest_path = "android/app/src/main/AndroidManifest.xml"

with open(manifest_path, "r") as f:
    manifest = f.read()

if 'usesCleartextTraffic' not in manifest:
    manifest = manifest.replace(
        "android:label=",
        'android:usesCleartextTraffic="true"\n        android:label='
    )

intent_filters = """
        <intent-filter>
            <action android:name="android.intent.action.SEND" />
            <category android:name="android.intent.category.DEFAULT" />
            <data android:mimeType="text/plain" />
        </intent-filter>
        <intent-filter android:autoVerify="true">
            <action android:name="android.intent.action.VIEW" />
            <category android:name="android.intent.category.DEFAULT" />
            <category android:name="android.intent.category.BROWSABLE" />
            <data android:scheme="https" android:host="earth.app.goo.gl" />
        </intent-filter>
        <intent-filter android:autoVerify="true">
            <action android:name="android.intent.action.VIEW" />
            <category android:name="android.intent.category.DEFAULT" />
            <category android:name="android.intent.category.BROWSABLE" />
            <data android:scheme="https" android:host="www.google.com" android:pathPrefix="/maps" />
        </intent-filter>
"""

manifest = manifest.replace("</activity>", intent_filters + "\n        </activity>", 1)

with open(manifest_path, "w") as f:
    f.write(manifest)

print("Patched AndroidManifest.xml")


# ── Rewrite MainActivity.java completely ──────────────────────────────────
main_act_path = None
package_name = "com.panoview.app"

for root, dirs, files in os.walk("android/app/src/main/java"):
    for file in files:
        if file == "MainActivity.java":
            main_act_path = os.path.join(root, file)
            # Extract package name from existing file
            with open(main_act_path, "r") as f:
                content = f.read()
            m = re.search(r"^package\s+([\w.]+);", content, re.MULTILINE)
            if m:
                package_name = m.group(1)
            break

if not main_act_path:
    print("WARNING: MainActivity.java not found")
else:
    # Build the Java source carefully using string concatenation to avoid escape issues
    # The JS call uses double-quotes around the URL, and we URL-encode it to avoid injection
    java_lines = [
        "package " + package_name + ";",
        "",
        "import android.content.Intent;",
        "import android.net.Uri;",
        "import android.os.Bundle;",
        "import com.getcapacitor.BridgeActivity;",
        "",
        "public class MainActivity extends BridgeActivity {",
        "",
        "    @Override",
        "    protected void onCreate(Bundle savedInstanceState) {",
        "        super.onCreate(savedInstanceState);",
        "        getBridge().getWebView().postDelayed(new Runnable() {",
        "            @Override public void run() { handleIncomingIntent(getIntent()); }",
        "        }, 2000);",
        "    }",
        "",
        "    @Override",
        "    protected void onNewIntent(Intent intent) {",
        "        super.onNewIntent(intent);",
        "        setIntent(intent);",
        "        getBridge().getWebView().postDelayed(new Runnable() {",
        "            @Override public void run() { handleIncomingIntent(intent); }",
        "        }, 500);",
        "    }",
        "",
        "    private void handleIncomingIntent(Intent intent) {",
        "        if (intent == null) return;",
        "        String action = intent.getAction();",
        "        String sharedUrl = null;",
        "        if (Intent.ACTION_SEND.equals(action) && android.content.ClipDescription.MIMETYPE_TEXT_PLAIN.equals(intent.getType())) {",
        "            sharedUrl = intent.getStringExtra(Intent.EXTRA_TEXT);",
        "        } else if (Intent.ACTION_VIEW.equals(action) && intent.getData() != null) {",
        "            sharedUrl = intent.getData().toString();",
        "        }",
        "        if (sharedUrl == null) return;",
        "        // URI-encode the URL so it is safe to embed in JS without any quote escaping",
        "        final String encoded = Uri.encode(sharedUrl);",
        "        final String js = \"if(window.handleSharedUrl){window.handleSharedUrl(decodeURIComponent('\" + encoded + \"'))}\";",
        "        getBridge().getWebView().post(new Runnable() {",
        "            @Override public void run() {",
        "                getBridge().getWebView().evaluateJavascript(js, null);",
        "            }",
        "        });",
        "    }",
        "}",
    ]

    with open(main_act_path, "w") as f:
        f.write("\n".join(java_lines) + "\n")

    print("Rewrote " + main_act_path)


# ── Add network_security_config.xml ───────────────────────────────────────
xml_dir = "android/app/src/main/res/xml"
os.makedirs(xml_dir, exist_ok=True)

net_lines = [
    '<?xml version="1.0" encoding="utf-8"?>',
    '<network-security-config>',
    '    <base-config cleartextTrafficPermitted="true">',
    '        <trust-anchors>',
    '            <certificates src="system" />',
    '        </trust-anchors>',
    '    </base-config>',
    '    <domain-config cleartextTrafficPermitted="true">',
    '        <domain includeSubdomains="true">cbk0.google.com</domain>',
    '        <domain includeSubdomains="true">lh3.googleusercontent.com</domain>',
    '        <domain includeSubdomains="true">maps.googleapis.com</domain>',
    '    </domain-config>',
    '</network-security-config>',
]

with open(os.path.join(xml_dir, "network_security_config.xml"), "w") as f:
    f.write("\n".join(net_lines) + "\n")

with open(manifest_path, "r") as f:
    manifest = f.read()

if "networkSecurityConfig" not in manifest:
    manifest = manifest.replace(
        'android:usesCleartextTraffic="true"',
        'android:usesCleartextTraffic="true"\n        android:networkSecurityConfig="@xml/network_security_config"'
    )
    with open(manifest_path, "w") as f:
        f.write(manifest)

print("Added network_security_config.xml")
print("All patches applied successfully!")
