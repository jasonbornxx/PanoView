"""
patch_android.py — PanoView Android patcher
Adds:
  - Share/view intent filters
  - Cleartext + network security config
  - Rewrites MainActivity.java with:
      * Share intent handler
      * JavascriptInterface so JS can call Android to save images to MediaStore (Gallery)
"""

import os
import re

# ── Patch AndroidManifest.xml ─────────────────────────────────────────────
manifest_path = "android/app/src/main/AndroidManifest.xml"

with open(manifest_path, "r") as f:
    manifest = f.read()

# Add WRITE_EXTERNAL_STORAGE permission (needed on Android < 10)
if 'WRITE_EXTERNAL_STORAGE' not in manifest:
    manifest = manifest.replace(
        "<application",
        '<uses-permission android:name="android.permission.WRITE_EXTERNAL_STORAGE" android:maxSdkVersion="28" />\n    <uses-permission android:name="android.permission.READ_EXTERNAL_STORAGE" android:maxSdkVersion="32" />\n    <application'
    )

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


# ── Rewrite MainActivity.java ─────────────────────────────────────────────
main_act_path = None
package_name = "com.panoview.app"

for root, dirs, files in os.walk("android/app/src/main/java"):
    for fname in files:
        if fname == "MainActivity.java":
            main_act_path = os.path.join(root, fname)
            with open(main_act_path, "r") as f:
                content = f.read()
            m = re.search(r"^package\s+([\w.]+);", content, re.MULTILINE)
            if m:
                package_name = m.group(1)
            break

if not main_act_path:
    print("WARNING: MainActivity.java not found")
else:
    # Write using os.write with bytes to have 100% control — no Python escape surprises
    java = (
        "package " + package_name + ";\n"
        "\n"
        "import android.content.ContentValues;\n"
        "import android.content.Context;\n"
        "import android.content.Intent;\n"
        "import android.net.Uri;\n"
        "import android.os.Build;\n"
        "import android.os.Bundle;\n"
        "import android.os.Environment;\n"
        "import android.provider.MediaStore;\n"
        "import android.util.Base64;\n"
        "import android.webkit.JavascriptInterface;\n"
        "import android.webkit.WebView;\n"
        "import android.widget.Toast;\n"
        "import com.getcapacitor.BridgeActivity;\n"
        "import java.io.File;\n"
        "import java.io.FileOutputStream;\n"
        "import java.io.OutputStream;\n"
        "\n"
        "public class MainActivity extends BridgeActivity {\n"
        "\n"
        "    // ── Android save bridge exposed to JavaScript ──\n"
        "    public class SaveBridge {\n"
        "        private final Context ctx;\n"
        "        SaveBridge(Context c) { ctx = c; }\n"
        "\n"
        "        @JavascriptInterface\n"
        "        public void saveImage(String base64Data, String filename) {\n"
        "            try {\n"
        "                // Strip data:image/jpeg;base64, prefix if present\n"
        "                String b64 = base64Data.contains(\",\")\n"
        "                    ? base64Data.split(\",\")[1] : base64Data;\n"
        "                byte[] bytes = Base64.decode(b64, Base64.DEFAULT);\n"
        "\n"
        "                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {\n"
        "                    // Android 10+ — use MediaStore (saves to Pictures/PanoView)\n"
        "                    ContentValues cv = new ContentValues();\n"
        "                    cv.put(MediaStore.Images.Media.DISPLAY_NAME, filename);\n"
        "                    cv.put(MediaStore.Images.Media.MIME_TYPE, \"image/jpeg\");\n"
        "                    cv.put(MediaStore.Images.Media.RELATIVE_PATH,\n"
        "                        Environment.DIRECTORY_PICTURES + \"/PanoView\");\n"
        "                    Uri uri = ctx.getContentResolver().insert(\n"
        "                        MediaStore.Images.Media.EXTERNAL_CONTENT_URI, cv);\n"
        "                    if (uri != null) {\n"
        "                        OutputStream os = ctx.getContentResolver().openOutputStream(uri);\n"
        "                        os.write(bytes);\n"
        "                        os.close();\n"
        "                    }\n"
        "                } else {\n"
        "                    // Android 9 and below — write to Pictures/PanoView directly\n"
        "                    File dir = new File(\n"
        "                        Environment.getExternalStoragePublicDirectory(\n"
        "                            Environment.DIRECTORY_PICTURES), \"PanoView\");\n"
        "                    dir.mkdirs();\n"
        "                    File file = new File(dir, filename);\n"
        "                    FileOutputStream fos = new FileOutputStream(file);\n"
        "                    fos.write(bytes);\n"
        "                    fos.close();\n"
        "                    // Notify gallery\n"
        "                    ctx.sendBroadcast(new Intent(\n"
        "                        Intent.ACTION_MEDIA_SCANNER_SCAN_FILE,\n"
        "                        Uri.fromFile(file)));\n"
        "                }\n"
        "\n"
        "                // Show success toast on UI thread\n"
        "                ((MainActivity)ctx).runOnUiThread(new Runnable() {\n"
        "                    public void run() {\n"
        "                        Toast.makeText(ctx,\n"
        "                            \"Saved to Pictures/PanoView\", Toast.LENGTH_LONG).show();\n"
        "                    }\n"
        "                });\n"
        "\n"
        "            } catch (Exception e) {\n"
        "                e.printStackTrace();\n"
        "                ((MainActivity)ctx).runOnUiThread(new Runnable() {\n"
        "                    public void run() {\n"
        "                        Toast.makeText(ctx,\n"
        "                            \"Save failed: \" + e.getMessage(), Toast.LENGTH_LONG).show();\n"
        "                    }\n"
        "                });\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "\n"
        "    @Override\n"
        "    protected void onCreate(Bundle savedInstanceState) {\n"
        "        super.onCreate(savedInstanceState);\n"
        "\n"
        "        // Inject the save bridge into the WebView\n"
        "        WebView wv = getBridge().getWebView();\n"
        "        wv.addJavascriptInterface(new SaveBridge(this), \"AndroidSave\");\n"
        "\n"
        "        // Handle share intent after WebView loads\n"
        "        wv.postDelayed(new Runnable() {\n"
        "            public void run() { handleIncomingIntent(getIntent()); }\n"
        "        }, 2000);\n"
        "    }\n"
        "\n"
        "    @Override\n"
        "    protected void onNewIntent(Intent intent) {\n"
        "        super.onNewIntent(intent);\n"
        "        setIntent(intent);\n"
        "        getBridge().getWebView().postDelayed(new Runnable() {\n"
        "            public void run() { handleIncomingIntent(intent); }\n"
        "        }, 500);\n"
        "    }\n"
        "\n"
        "    private void handleIncomingIntent(Intent intent) {\n"
        "        if (intent == null) return;\n"
        "        String action = intent.getAction();\n"
        "        String sharedUrl = null;\n"
        "        if (Intent.ACTION_SEND.equals(action)\n"
        "                && android.content.ClipDescription.MIMETYPE_TEXT_PLAIN.equals(intent.getType())) {\n"
        "            sharedUrl = intent.getStringExtra(Intent.EXTRA_TEXT);\n"
        "        } else if (Intent.ACTION_VIEW.equals(action) && intent.getData() != null) {\n"
        "            sharedUrl = intent.getData().toString();\n"
        "        }\n"
        "        if (sharedUrl == null) return;\n"
        "        final String encoded = Uri.encode(sharedUrl);\n"
        "        final String js =\n"
        "            \"if(window.handleSharedUrl){\"\n"
        "            + \"window.handleSharedUrl(decodeURIComponent('\" + encoded + \"'))\"\n"
        "            + \"}\";\n"
        "        getBridge().getWebView().post(new Runnable() {\n"
        "            public void run() {\n"
        "                getBridge().getWebView().evaluateJavascript(js, null);\n"
        "            }\n"
        "        });\n"
        "    }\n"
        "}\n"
    )

    with open(main_act_path, "w") as f:
        f.write(java)
    print("Rewrote " + main_act_path)


# ── Add network_security_config.xml ──────────────────────────────────────
xml_dir = "android/app/src/main/res/xml"
os.makedirs(xml_dir, exist_ok=True)

net_xml = "\n".join([
    '<?xml version="1.0" encoding="utf-8"?>',
    '<network-security-config>',
    '    <base-config cleartextTrafficPermitted="true">',
    '        <trust-anchors><certificates src="system" /></trust-anchors>',
    '    </base-config>',
    '    <domain-config cleartextTrafficPermitted="true">',
    '        <domain includeSubdomains="true">cbk0.google.com</domain>',
    '        <domain includeSubdomains="true">lh3.googleusercontent.com</domain>',
    '        <domain includeSubdomains="true">maps.googleapis.com</domain>',
    '    </domain-config>',
    '</network-security-config>',
]) + "\n"

with open(os.path.join(xml_dir, "network_security_config.xml"), "w") as f:
    f.write(net_xml)

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
print("All patches applied!")
