"""
patch_android.py — PanoView Android patcher
Adds:
  - Share/view intent filters
  - Cleartext + network security config
  - Rewrites MainActivity.java with:
      * Share intent handler
      * JavascriptInterface so JS can call Android to save images to MediaStore (Gallery)
      * Back button / gesture fix (navigates WebView history, exits only from root)
      * TokenFetcher WebView for CI... panoramas (bottom-sheet, desktop UA, polls for !6s token)
  - Generates flat launcher icons (adaptive + legacy) in all densities
"""

import os
import re
import base64
import struct
import zlib

# ═══════════════════════════════════════════════════════════════════════════
# 1. LOGO / ICON GENERATION
#    Flat design: dark background (#0a0a0a), cyan circle (#00cfff), white lens
#    Written as minimal PNG from scratch (no PIL dependency)
# ═══════════════════════════════════════════════════════════════════════════

def make_png(size):
    """Generate a flat PanoView icon as raw PNG bytes at `size` x `size`."""
    w = h = size
    bg      = (10,  10,  10,  255)   # #0a0a0a
    ring    = (0,   207, 255, 255)   # #00cfff
    lens_bg = (0,   207, 255, 40)    # faint cyan fill
    white   = (255, 255, 255, 255)

    cx = cy = size / 2
    r  = size * 0.42   # outer circle radius
    rr = size * 0.30   # inner (lens) radius
    ir = size * 0.12   # pupil radius
    ring_w = size * 0.06

    pixels = []
    for y in range(h):
        row = []
        for x in range(w):
            dx = x - cx
            dy = y - cy
            d  = (dx*dx + dy*dy) ** 0.5

            # rounded-rect clip (icon shape) — distance to corner
            cr = size * 0.22          # corner radius
            rx = abs(dx) - (w/2 - cr)
            ry = abs(dy) - (h/2 - cr)
            if rx > 0 and ry > 0 and (rx*rx + ry*ry) > cr*cr:
                row.extend(bg)         # outside icon shape → background
                continue

            # Ring (thick circle)
            if r - ring_w <= d <= r:
                aa = min(1.0, (r - d) / 1.5) * min(1.0, (d - (r - ring_w)) / 1.5)
                c = blend(bg, ring, aa)
                row.extend(c)
                continue

            # Lens fill (inside ring)
            if d < r - ring_w:
                # pupil dot
                if d < ir:
                    aa = min(1.0, (ir - d) / 1.5)
                    c = blend(bg, white, aa)
                    row.extend(c)
                    continue
                # iris ring
                if rr - ring_w*0.6 <= d <= rr:
                    aa = min(1.0, (rr - d) / 1.5) * min(1.0, (d - (rr - ring_w*0.6)) / 1.5)
                    c = blend(bg, ring, aa)
                    row.extend(c)
                    continue
                row.extend(bg)
                continue

            row.extend(bg)

        pixels.append(bytes(row))

    # Encode PNG
    def chunk(tag, data):
        c = struct.pack('>I', len(data)) + tag + data
        return c + struct.pack('>I', zlib.crc32(c[4:]) & 0xFFFFFFFF)

    raw = b''
    for row in pixels:
        raw += b'\x00' + row          # filter type None per row

    idat = zlib.compress(raw, 9)

    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
    png += chunk(b'IDAT', idat)
    png += chunk(b'IEND', b'')
    return png


def blend(bg, fg, a):
    return tuple(int(b + (f - b) * a) for b, f in zip(bg, fg))


# Density → size mapping
DENSITIES = {
    'mipmap-mdpi':    48,
    'mipmap-hdpi':    72,
    'mipmap-xhdpi':   96,
    'mipmap-xxhdpi':  144,
    'mipmap-xxxhdpi': 192,
}

for density, size in DENSITIES.items():
    dir_path = f'android/app/src/main/res/{density}'
    os.makedirs(dir_path, exist_ok=True)
    png_bytes = make_png(size)
    with open(os.path.join(dir_path, 'ic_launcher.png'), 'wb') as f:
        f.write(png_bytes)
    with open(os.path.join(dir_path, 'ic_launcher_round.png'), 'wb') as f:
        f.write(png_bytes)
    print(f'Generated {density}/ic_launcher.png ({size}x{size})')

# Adaptive icon foreground (just the lens symbol, larger, transparent bg)
for density, size in DENSITIES.items():
    dir_path = f'android/app/src/main/res/{density}'
    fg_png = make_png(size)           # same icon works as foreground on white bg
    with open(os.path.join(dir_path, 'ic_launcher_foreground.png'), 'wb') as f:
        f.write(fg_png)

# Adaptive icon XML (API 26+)
mipmap_anydpi = 'android/app/src/main/res/mipmap-anydpi-v26'
os.makedirs(mipmap_anydpi, exist_ok=True)
for name in ('ic_launcher.xml', 'ic_launcher_round.xml'):
    with open(os.path.join(mipmap_anydpi, name), 'w') as f:
        f.write(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
            '    <background android:drawable="@color/ic_launcher_background" />\n'
            '    <foreground android:drawable="@mipmap/ic_launcher_foreground" />\n'
            '</adaptive-icon>\n'
        )

# Color resource for adaptive icon background
# Capacitor sometimes ships a standalone ic_launcher_background.xml in values/
# which causes a "Duplicate resources" build error when colors.xml also defines
# the same color name.  Strategy:
#   1. Delete any standalone ic_launcher_background.xml
#   2. Remove the color entry from any other values XML that already has it
#   3. Ensure colors.xml owns the single definition (overwritten to our dark value)
values_dir = 'android/app/src/main/res/values'
os.makedirs(values_dir, exist_ok=True)

LAUNCHER_BG_FILE = os.path.join(values_dir, 'ic_launcher_background.xml')
if os.path.exists(LAUNCHER_BG_FILE):
    os.remove(LAUNCHER_BG_FILE)
    print(f'Removed standalone {LAUNCHER_BG_FILE} (prevents duplicate resource)')

# Strip any existing ic_launcher_background color entry from every other XML in values/
import glob, re as _re
for xml_path in glob.glob(os.path.join(values_dir, '*.xml')):
    if os.path.basename(xml_path) == 'colors.xml':
        continue  # We'll handle colors.xml separately below
    with open(xml_path, 'r') as f:
        content = f.read()
    if 'ic_launcher_background' in content:
        cleaned = _re.sub(
            r'\s*<color[^>]*name=["\']ic_launcher_background["\'][^/]*/?>.*?</color>',
            '', content, flags=_re.DOTALL)
        cleaned = _re.sub(
            r'\s*<color[^>]*name=["\']ic_launcher_background["\'][^>]*/>', '', cleaned)
        with open(xml_path, 'w') as f:
            f.write(cleaned)
        print(f'Removed ic_launcher_background from {xml_path}')

# Now write/update colors.xml with our value (overwrites whatever was there for this key)
colors_path = os.path.join(values_dir, 'colors.xml')
if os.path.exists(colors_path):
    with open(colors_path, 'r') as f:
        colors = f.read()
    if 'ic_launcher_background' in colors:
        # Update the existing entry to our dark value
        colors = _re.sub(
            r'(<color[^>]*name=["\']ic_launcher_background["\'][^>]*>)[^<]*(</color>)',
            r'\g<1>#0A0A0A\g<2>', colors)
    else:
        colors = colors.replace(
            '</resources>',
            '    <color name="ic_launcher_background">#0A0A0A</color>\n</resources>')
    with open(colors_path, 'w') as f:
        f.write(colors)
else:
    with open(colors_path, 'w') as f:
        f.write(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<resources>\n'
            '    <color name="ic_launcher_background">#0A0A0A</color>\n'
            '</resources>\n'
        )

print('Generated adaptive icons')


# ═══════════════════════════════════════════════════════════════════════════
# 2. Patch AndroidManifest.xml
# ═══════════════════════════════════════════════════════════════════════════

manifest_path = "android/app/src/main/AndroidManifest.xml"

with open(manifest_path, "r") as f:
    manifest = f.read()

# Permissions
if 'WRITE_EXTERNAL_STORAGE' not in manifest:
    manifest = manifest.replace(
        "<application",
        '<uses-permission android:name="android.permission.WRITE_EXTERNAL_STORAGE" android:maxSdkVersion="28" />\n'
        '    <uses-permission android:name="android.permission.READ_EXTERNAL_STORAGE" android:maxSdkVersion="32" />\n'
        '    <uses-permission android:name="android.permission.INTERNET" />\n'
        '    <application'
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


# ═══════════════════════════════════════════════════════════════════════════
# 3. Rewrite MainActivity.java
#    - Back button / gesture: navigates WebView history, exits only from root
#    - Share intent handler
#    - AndroidSave bridge (save to MediaStore / Gallery)
#    - AndroidTokenFetcher bridge (bottom-sheet WebView for !6s token)
# ═══════════════════════════════════════════════════════════════════════════

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
    java = (
        "package " + package_name + ";\n"
        "\n"
        "import android.annotation.SuppressLint;\n"
        "import android.content.ContentValues;\n"
        "import android.content.Context;\n"
        "import android.content.Intent;\n"
        "import android.graphics.Color;\n"
        "import android.graphics.drawable.ColorDrawable;\n"
        "import android.net.Uri;\n"
        "import android.os.Build;\n"
        "import android.os.Bundle;\n"
        "import android.os.Environment;\n"
        "import android.os.Handler;\n"
        "import android.os.Looper;\n"
        "import android.provider.MediaStore;\n"
        "import android.util.Base64;\n"
        "import android.view.Gravity;\n"
        "import android.view.View;\n"
        "import android.view.ViewGroup;\n"
        "import android.view.Window;\n"
        "import android.view.WindowManager;\n"
        "import android.webkit.JavascriptInterface;\n"
        "import android.webkit.WebChromeClient;\n"
        "import android.webkit.WebSettings;\n"
        "import android.webkit.WebView;\n"
        "import android.webkit.WebViewClient;\n"
        "import android.widget.FrameLayout;\n"
        "import android.widget.ProgressBar;\n"
        "import android.widget.Toast;\n"
        "import androidx.appcompat.app.AppCompatDialog;\n"
        "import com.getcapacitor.BridgeActivity;\n"
        "import java.io.File;\n"
        "import java.io.FileOutputStream;\n"
        "import java.io.OutputStream;\n"
        "\n"
        "public class MainActivity extends BridgeActivity {\n"
        "\n"
        "    private static final String DESKTOP_UA =\n"
        "        \"Mozilla/5.0 (Windows NT 10.0; Win64; x64) \"\n"
        "        + \"AppleWebKit/537.36 (KHTML, like Gecko) \"\n"
        "        + \"Chrome/121.0.0.0 Safari/537.36\";\n"
        "\n"
        "    // ── 1. BACK BUTTON / GESTURE ──────────────────────────────────────────\n"
        "    @Override\n"
        "    public void onBackPressed() {\n"
        "        WebView wv = getBridge().getWebView();\n"
        "        if (wv != null && wv.canGoBack()) {\n"
        "            wv.goBack();\n"
        "        } else {\n"
        "            super.onBackPressed();\n"
        "        }\n"
        "    }\n"
        "\n"
        "    // ── 2. SAVE BRIDGE ────────────────────────────────────────────────────\n"
        "    public class SaveBridge {\n"
        "        private final Context ctx;\n"
        "        SaveBridge(Context c) { ctx = c; }\n"
        "\n"
        "        @JavascriptInterface\n"
        "        public void saveImage(String base64Data, String filename) {\n"
        "            try {\n"
        "                String b64 = base64Data.contains(\",\")\n"
        "                    ? base64Data.split(\",\")[1] : base64Data;\n"
        "                byte[] bytes = Base64.decode(b64, Base64.DEFAULT);\n"
        "\n"
        "                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {\n"
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
        "                    File dir = new File(\n"
        "                        Environment.getExternalStoragePublicDirectory(\n"
        "                            Environment.DIRECTORY_PICTURES), \"PanoView\");\n"
        "                    dir.mkdirs();\n"
        "                    File file = new File(dir, filename);\n"
        "                    FileOutputStream fos = new FileOutputStream(file);\n"
        "                    fos.write(bytes);\n"
        "                    fos.close();\n"
        "                    ctx.sendBroadcast(new Intent(\n"
        "                        Intent.ACTION_MEDIA_SCANNER_SCAN_FILE,\n"
        "                        Uri.fromFile(file)));\n"
        "                }\n"
        "                ((MainActivity) ctx).runOnUiThread(() ->\n"
        "                    Toast.makeText(ctx, \"Saved to Pictures/PanoView\",\n"
        "                        Toast.LENGTH_LONG).show());\n"
        "            } catch (Exception e) {\n"
        "                e.printStackTrace();\n"
        "                ((MainActivity) ctx).runOnUiThread(() ->\n"
        "                    Toast.makeText(ctx, \"Save failed: \" + e.getMessage(),\n"
        "                        Toast.LENGTH_LONG).show());\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "\n"
        "    // ── 3. TOKEN FETCHER ──────────────────────────────────────────────────\n"
        "    //\n"
        "    // Opens a bottom-sheet WebView with a desktop UA, polls the loaded URL\n"
        "    // every second for a !6s token, then calls back into JS with the result.\n"
        "    //\n"
        "    public class TokenFetcherBridge {\n"
        "        private final MainActivity activity;\n"
        "        TokenFetcherBridge(MainActivity a) { activity = a; }\n"
        "\n"
        "        @JavascriptInterface\n"
        "        public void fetch(String mapsUrl) {\n"
        "            activity.runOnUiThread(() -> activity.openTokenSheet(mapsUrl));\n"
        "        }\n"
        "    }\n"
        "\n"
        "    @SuppressLint(\"SetJavaScriptEnabled\")\n"
        "    void openTokenSheet(String mapsUrl) {\n"
        "        // Build bottom-sheet dialog\n"
        "        AppCompatDialog sheet = new AppCompatDialog(this);\n"
        "        sheet.requestWindowFeature(Window.FEATURE_NO_TITLE);\n"
        "        sheet.setCancelable(true);\n"
        "\n"
        "        // Container\n"
        "        FrameLayout container = new FrameLayout(this);\n"
        "        container.setBackgroundColor(Color.parseColor(\"#0a0a0a\"));\n"
        "        int sheetH = (int)(getResources().getDisplayMetrics().heightPixels * 0.65);\n"
        "        container.setMinimumHeight(sheetH);\n"
        "\n"
        "        // Progress bar\n"
        "        ProgressBar pb = new ProgressBar(this, null,\n"
        "            android.R.attr.progressBarStyleHorizontal);\n"
        "        pb.setIndeterminate(true);\n"
        "        FrameLayout.LayoutParams pbLp = new FrameLayout.LayoutParams(\n"
        "            ViewGroup.LayoutParams.MATCH_PARENT, 8);\n"
        "        pbLp.gravity = Gravity.TOP;\n"
        "        pb.setLayoutParams(pbLp);\n"
        "        container.addView(pb);\n"
        "\n"
        "        // Inner WebView\n"
        "        WebView wv = new WebView(this);\n"
        "        WebSettings ws = wv.getSettings();\n"
        "        ws.setJavaScriptEnabled(true);\n"
        "        ws.setDomStorageEnabled(true);\n"
        "        ws.setUserAgentString(DESKTOP_UA);\n"
        "        ws.setLoadWithOverviewMode(true);\n"
        "        ws.setUseWideViewPort(true);\n"
        "        ws.setSupportZoom(true);\n"
        "        ws.setBuiltInZoomControls(true);\n"
        "        ws.setDisplayZoomControls(false);\n"
        "        FrameLayout.LayoutParams wvLp = new FrameLayout.LayoutParams(\n"
        "            ViewGroup.LayoutParams.MATCH_PARENT,\n"
        "            ViewGroup.LayoutParams.MATCH_PARENT);\n"
        "        wvLp.topMargin = 8;\n"
        "        wv.setLayoutParams(wvLp);\n"
        "        container.addView(wv);\n"
        "\n"
        "        sheet.setContentView(container);\n"
        "\n"
        "        // Position at bottom\n"
        "        Window win = sheet.getWindow();\n"
        "        if (win != null) {\n"
        "            win.setLayout(ViewGroup.LayoutParams.MATCH_PARENT,\n"
        "                ViewGroup.LayoutParams.WRAP_CONTENT);\n"
        "            win.setGravity(Gravity.BOTTOM);\n"
        "            win.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));\n"
        "        }\n"
        "\n"
        "        // Polling state\n"
        "        final long[] deadline = {System.currentTimeMillis() + 15_000};\n"
        "        final String[] lastUrl = {mapsUrl};\n"
        "        final Handler handler = new Handler(Looper.getMainLooper());\n"
        "        final boolean[] found = {false};\n"
        "\n"
        "        // Extract !6s token from a URL string\n"
        "        // Returns null if not present\n"
        "        // We'll do this in a small JS snippet evaluated against the token WebView\n"
        "\n"
        "        wv.setWebViewClient(new WebViewClient() {\n"
        "            @Override\n"
        "            public void onPageFinished(WebView view, String url) {\n"
        "                lastUrl[0] = url;\n"
        "                pb.setVisibility(View.GONE);\n"
        "            }\n"
        "            @Override\n"
        "            public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {\n"
        "                lastUrl[0] = url;\n"
        "                pb.setVisibility(View.VISIBLE);\n"
        "            }\n"
        "        });\n"
        "\n"
        "        wv.setWebChromeClient(new WebChromeClient());\n"
        "\n"
        "        // Polling runnable\n"
        "        Runnable[] pollRef = {null};\n"
        "        pollRef[0] = new Runnable() {\n"
        "            @Override public void run() {\n"
        "                if (found[0] || !sheet.isShowing()) return;\n"
        "\n"
        "                if (System.currentTimeMillis() > deadline[0]) {\n"
        "                    // Timeout — notify JS\n"
        "                    sheet.dismiss();\n"
        "                    notifyTokenResult(null, \"timeout\");\n"
        "                    return;\n"
        "                }\n"
        "\n"
        "                // Evaluate JS to extract !6s token from current document URL\n"
        "                wv.evaluateJavascript(\n"
        "                    \"(function(){\" +\n"
        "                    \"  var u=window.location.href;\" +\n"
        "                    \"  var m=u.match(/!6s(https?:[^!]+lh3\\\\.googleusercontent\\\\.com[^!]+)/);\" +\n"
        "                    \"  if(m){try{return decodeURIComponent(m[1]);}catch(e){return m[1];}}\" +\n"
        "                    \"  return null;\" +\n"
        "                    \"})()\",\n"
        "                    value -> {\n"
        "                        if (value != null && !value.equals(\"null\")\n"
        "                                && !value.isEmpty()) {\n"
        "                            found[0] = true;\n"
        "                            sheet.dismiss();\n"
        "                            // Strip surrounding JS string quotes\n"
        "                            String token = value.replaceAll(\"^\\\"\", \"\").replaceAll(\"\\\"$\", \"\");\n"
        "                            notifyTokenResult(token, null);\n"
        "                        } else {\n"
        "                            // Not yet — poll again in 1s\n"
        "                            handler.postDelayed(pollRef[0], 1000);\n"
        "                        }\n"
        "                    });\n"
        "            }\n"
        "        };\n"
        "\n"
        "        wv.loadUrl(mapsUrl);\n"
        "        handler.postDelayed(pollRef[0], 1500); // start polling after 1.5s\n"
        "        sheet.setOnDismissListener(d -> {\n"
        "            if (!found[0]) notifyTokenResult(null, \"cancelled\");\n"
        "        });\n"
        "        sheet.show();\n"
        "    }\n"
        "\n"
        "    private void notifyTokenResult(String token, String error) {\n"
        "        String js;\n"
        "        if (token != null) {\n"
        "            String safe = token.replace(\"\\\\\", \"\\\\\\\\\").replace(\"'\", \"\\\\'\");\n"
        "            js = \"window._panoTokenResult && window._panoTokenResult('\" + safe + \"', null);\";\n"
        "        } else {\n"
        "            js = \"window._panoTokenResult && window._panoTokenResult(null, '\" + error + \"');\";\n"
        "        }\n"
        "        getBridge().getWebView().post(() ->\n"
        "            getBridge().getWebView().evaluateJavascript(js, null));\n"
        "    }\n"
        "\n"
        "    // ── 4. LIFECYCLE ──────────────────────────────────────────────────────\n"
        "    @Override\n"
        "    protected void onCreate(Bundle savedInstanceState) {\n"
        "        super.onCreate(savedInstanceState);\n"
        "\n"
        "        WebView wv = getBridge().getWebView();\n"
        "        wv.addJavascriptInterface(new SaveBridge(this), \"AndroidSave\");\n"
        "        wv.addJavascriptInterface(new TokenFetcherBridge(this), \"AndroidTokenFetcher\");\n"
        "\n"
        "        wv.postDelayed(() -> handleIncomingIntent(getIntent()), 2000);\n"
        "    }\n"
        "\n"
        "    @Override\n"
        "    protected void onNewIntent(Intent intent) {\n"
        "        super.onNewIntent(intent);\n"
        "        setIntent(intent);\n"
        "        getBridge().getWebView().postDelayed(\n"
        "            () -> handleIncomingIntent(intent), 500);\n"
        "    }\n"
        "\n"
        "    private void handleIncomingIntent(Intent intent) {\n"
        "        if (intent == null) return;\n"
        "        String action = intent.getAction();\n"
        "        String sharedUrl = null;\n"
        "        if (Intent.ACTION_SEND.equals(action)\n"
        "                && android.content.ClipDescription.MIMETYPE_TEXT_PLAIN\n"
        "                        .equals(intent.getType())) {\n"
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
        "        getBridge().getWebView().post(() ->\n"
        "            getBridge().getWebView().evaluateJavascript(js, null));\n"
        "    }\n"
        "}\n"
    )

    with open(main_act_path, "w") as f:
        f.write(java)
    print("Rewrote " + main_act_path)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Network security config
# ═══════════════════════════════════════════════════════════════════════════

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
