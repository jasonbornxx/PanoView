"""
patch_android.py — PanoView Android patcher
Adds:
  - Share/view intent filters
  - Cleartext + network security config
  - Rewrites MainActivity.java with:
      * Share intent handler
      * JavascriptInterface so JS can call Android to save images to MediaStore (Gallery)
      * FIX #5: Back button via OnBackPressedDispatcher (replaces deprecated onBackPressed)
      * FIX #6: notifyTokenResult uses JSONObject for safe JS injection (no quote-injection risk)
      * FIX #1 (Android side): cancel() method on TokenFetcherBridge so JS can dismiss native sheet
      * currentTokenSheet field to track open sheet for cancel support
  - Generates flat launcher icons (adaptive + legacy) in all densities
"""

import os
import re
import struct
import zlib
import glob as _glob

# ═══════════════════════════════════════════════════════════════════════════
# 1. LOGO / ICON GENERATION
# ═══════════════════════════════════════════════════════════════════════════

def make_png(size):
    """Generate a flat PanoView icon as raw PNG bytes at `size` x `size`."""
    w = h = size
    bg   = (10,  10,  10,  255)
    ring = (0,   207, 255, 255)
    white = (255, 255, 255, 255)

    cx = cy = size / 2
    r  = size * 0.42
    rr = size * 0.30
    ir = size * 0.12
    ring_w = size * 0.06

    pixels = []
    for y in range(h):
        row = []
        for x in range(w):
            dx = x - cx
            dy = y - cy
            d  = (dx*dx + dy*dy) ** 0.5

            cr = size * 0.22
            rx = abs(dx) - (w/2 - cr)
            ry = abs(dy) - (h/2 - cr)
            if rx > 0 and ry > 0 and (rx*rx + ry*ry) > cr*cr:
                row.extend(bg)
                continue

            if r - ring_w <= d <= r:
                aa = min(1.0, (r - d) / 1.5) * min(1.0, (d - (r - ring_w)) / 1.5)
                c = blend(bg, ring, aa)
                row.extend(c)
                continue

            if d < r - ring_w:
                if d < ir:
                    aa = min(1.0, (ir - d) / 1.5)
                    c = blend(bg, white, aa)
                    row.extend(c)
                    continue
                if rr - ring_w*0.6 <= d <= rr:
                    aa = min(1.0, (rr - d) / 1.5) * min(1.0, (d - (rr - ring_w*0.6)) / 1.5)
                    c = blend(bg, ring, aa)
                    row.extend(c)
                    continue
                row.extend(bg)
                continue

            row.extend(bg)

        pixels.append(bytes(row))

    def chunk(tag, data):
        c = struct.pack('>I', len(data)) + tag + data
        return c + struct.pack('>I', zlib.crc32(c[4:]) & 0xFFFFFFFF)

    raw = b''
    for row in pixels:
        raw += b'\x00' + row

    idat = zlib.compress(raw, 9)

    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
    png += chunk(b'IDAT', idat)
    png += chunk(b'IEND', b'')
    return png


def blend(bg, fg, a):
    return tuple(int(b + (f - b) * a) for b, f in zip(bg, fg))


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

for density, size in DENSITIES.items():
    dir_path = f'android/app/src/main/res/{density}'
    fg_png = make_png(size)
    with open(os.path.join(dir_path, 'ic_launcher_foreground.png'), 'wb') as f:
        f.write(fg_png)

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

values_dir = 'android/app/src/main/res/values'
os.makedirs(values_dir, exist_ok=True)

LAUNCHER_BG_FILE = os.path.join(values_dir, 'ic_launcher_background.xml')
if os.path.exists(LAUNCHER_BG_FILE):
    os.remove(LAUNCHER_BG_FILE)
    print(f'Removed standalone {LAUNCHER_BG_FILE} (prevents duplicate resource)')

for xml_path in _glob.glob(os.path.join(values_dir, '*.xml')):
    if os.path.basename(xml_path) == 'colors.xml':
        continue
    with open(xml_path, 'r') as f:
        content = f.read()
    if 'ic_launcher_background' in content:
        cleaned = re.sub(
            r'\s*<color[^>]*name=["\']ic_launcher_background["\'][^/]*/?>.*?</color>',
            '', content, flags=re.DOTALL)
        cleaned = re.sub(
            r'\s*<color[^>]*name=["\']ic_launcher_background["\'][^>]*/>', '', cleaned)
        with open(xml_path, 'w') as f:
            f.write(cleaned)
        print(f'Removed ic_launcher_background from {xml_path}')

colors_path = os.path.join(values_dir, 'colors.xml')
if os.path.exists(colors_path):
    with open(colors_path, 'r') as f:
        colors = f.read()
    if 'ic_launcher_background' in colors:
        colors = re.sub(
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

if 'WRITE_EXTERNAL_STORAGE' not in manifest:
    manifest = manifest.replace(
        "<application",
        '<uses-permission android:name="android.permission.WRITE_EXTERNAL_STORAGE" android:maxSdkVersion="28" />\n'
        '    <uses-permission android:name="android.permission.READ_EXTERNAL_STORAGE" android:maxSdkVersion="32" />\n'
        '    <application'
    )
# Add INTERNET only if Capacitor hasn't already declared it (avoids duplicate warning)
if 'android.permission.INTERNET' not in manifest:
    manifest = manifest.replace(
        "<application",
        '<uses-permission android:name="android.permission.INTERNET" />\n'
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
#
# FIX #5: onBackPressed() deprecated → OnBackPressedDispatcher + callback
# FIX #6: notifyTokenResult uses JSONObject for safe token/error escaping
# FIX #1 (Android): cancel() on TokenFetcherBridge, currentTokenSheet field
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
        "import android.webkit.JavascriptInterface;\n"
        "import android.webkit.WebChromeClient;\n"
        "import android.webkit.WebSettings;\n"
        "import android.webkit.WebView;\n"
        "import android.webkit.WebViewClient;\n"
        "import android.widget.FrameLayout;\n"
        "import android.widget.ProgressBar;\n"
        "import android.widget.Toast;\n"
        "import androidx.activity.OnBackPressedCallback;\n"
        "import androidx.appcompat.app.AppCompatDialog;\n"
        "import com.getcapacitor.BridgeActivity;\n"
        "import java.io.File;\n"
        "import java.io.FileOutputStream;\n"
        "import java.io.OutputStream;\n"
        "import org.json.JSONObject;\n"
        "\n"
        "public class MainActivity extends BridgeActivity {\n"
        "\n"
        "    private static final String DESKTOP_UA =\n"
        "        \"Mozilla/5.0 (Windows NT 10.0; Win64; x64) \"\n"
        "        + \"AppleWebKit/537.36 (KHTML, like Gecko) \"\n"
        "        + \"Chrome/121.0.0.0 Safari/537.36\";\n"
        "\n"
        "    // FIX #1: Holds reference to open token sheet so cancel() can dismiss it\n"
        "    AppCompatDialog currentTokenSheet = null;\n"
        "\n"
        "    // ── 1. SAVE BRIDGE ────────────────────────────────────────────────────\n"
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
        "    // ── 2. TOKEN FETCHER ──────────────────────────────────────────────────\n"
        "    //\n"
        "    // Opens a bottom-sheet WebView with a desktop UA, polls the loaded URL\n"
        "    // every second for a !6s token, then calls back into JS via JSONObject.\n"
        "    //\n"
        "    // FIX #1: cancel() method lets JS dismiss this sheet (e.g. on timeout)\n"
        "    //\n"
        "    public class TokenFetcherBridge {\n"
        "        private final MainActivity activity;\n"
        "        TokenFetcherBridge(MainActivity a) { activity = a; }\n"
        "\n"
        "        @JavascriptInterface\n"
        "        public void fetch(String mapsUrl) {\n"
        "            activity.runOnUiThread(() -> activity.openTokenSheet(mapsUrl));\n"
        "        }\n"
        "\n"
        "        // FIX #1: Called from JS when user cancels or timeout fires.\n"
        "        // Dismisses the native sheet — triggers onDismissListener → notifyTokenResult(null, cancelled)\n"
        "        @JavascriptInterface\n"
        "        public void cancel() {\n"
        "            activity.runOnUiThread(() -> {\n"
        "                if (activity.currentTokenSheet != null\n"
        "                        && activity.currentTokenSheet.isShowing()) {\n"
        "                    activity.currentTokenSheet.dismiss();\n"
        "                }\n"
        "            });\n"
        "        }\n"
        "    }\n"
        "\n"
        "    @SuppressLint(\"SetJavaScriptEnabled\")\n"
        "    void openTokenSheet(String mapsUrl) {\n"
        "        AppCompatDialog sheet = new AppCompatDialog(this);\n"
        "        sheet.requestWindowFeature(Window.FEATURE_NO_TITLE);\n"
        "        sheet.setCancelable(true);\n"
        "\n"
        "        FrameLayout container = new FrameLayout(this);\n"
        "        container.setBackgroundColor(Color.parseColor(\"#0a0a0a\"));\n"
        "        int sheetH = (int)(getResources().getDisplayMetrics().heightPixels * 0.65);\n"
        "        container.setMinimumHeight(sheetH);\n"
        "\n"
        "        ProgressBar pb = new ProgressBar(this, null,\n"
        "            android.R.attr.progressBarStyleHorizontal);\n"
        "        pb.setIndeterminate(true);\n"
        "        FrameLayout.LayoutParams pbLp = new FrameLayout.LayoutParams(\n"
        "            ViewGroup.LayoutParams.MATCH_PARENT, 8);\n"
        "        pbLp.gravity = Gravity.TOP;\n"
        "        pb.setLayoutParams(pbLp);\n"
        "        container.addView(pb);\n"
        "\n"
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
        "        Window win = sheet.getWindow();\n"
        "        if (win != null) {\n"
        "            win.setLayout(ViewGroup.LayoutParams.MATCH_PARENT,\n"
        "                ViewGroup.LayoutParams.WRAP_CONTENT);\n"
        "            win.setGravity(Gravity.BOTTOM);\n"
        "            win.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));\n"
        "        }\n"
        "\n"
        "        final long[] deadline = {System.currentTimeMillis() + 15_000};\n"
        "        final String[] lastUrl = {mapsUrl};\n"
        "        final Handler handler = new Handler(Looper.getMainLooper());\n"
        "        final boolean[] found = {false};\n"
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
        "        Runnable[] pollRef = {null};\n"
        "        pollRef[0] = new Runnable() {\n"
        "            @Override public void run() {\n"
        "                if (found[0] || !sheet.isShowing()) return;\n"
        "\n"
        "                if (System.currentTimeMillis() > deadline[0]) {\n"
        "                    sheet.dismiss();\n"
        "                    notifyTokenResult(null, \"timeout\");\n"
        "                    return;\n"
        "                }\n"
        "\n"
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
        "                            String token = value\n"
        "                                .replaceAll(\"^\\\"\", \"\")\n"
        "                                .replaceAll(\"\\\"$\", \"\");\n"
        "                            notifyTokenResult(token, null);\n"
        "                        } else {\n"
        "                            handler.postDelayed(pollRef[0], 1000);\n"
        "                        }\n"
        "                    });\n"
        "            }\n"
        "        };\n"
        "\n"
        "        wv.loadUrl(mapsUrl);\n"
        "        // FIX #1: Store reference so cancel() can dismiss externally\n"
        "        currentTokenSheet = sheet;\n"
        "        handler.postDelayed(pollRef[0], 1500);\n"
        "        sheet.setOnDismissListener(d -> {\n"
        "            currentTokenSheet = null;  // clear ref on any dismiss\n"
        "            if (!found[0]) notifyTokenResult(null, \"cancelled\");\n"
        "        });\n"
        "        sheet.show();\n"
        "    }\n"
        "\n"
        "    // FIX #6: Use JSONObject to safely serialize token/error\n"
        "    // Previously used string concatenation with manual escaping — unsafe for\n"
        "    // URLs containing backticks, closing tags, or other JS-special characters.\n"
        "    private void notifyTokenResult(String token, String error) {\n"
        "        String js;\n"
        "        try {\n"
        "            if (token != null) {\n"
        "                JSONObject obj = new JSONObject();\n"
        "                obj.put(\"token\", token);\n"
        "                js = \"(function(){var d=\" + obj.toString()\n"
        "                   + \";window._panoTokenResult&&window._panoTokenResult(d.token,null);})()\";\n"
        "            } else {\n"
        "                JSONObject obj = new JSONObject();\n"
        "                obj.put(\"error\", error != null ? error : \"unknown\");\n"
        "                js = \"(function(){var d=\" + obj.toString()\n"
        "                   + \";window._panoTokenResult&&window._panoTokenResult(null,d.error);})()\";\n"
        "            }\n"
        "        } catch (Exception e) {\n"
        "            js = \"window._panoTokenResult&&window._panoTokenResult(null,'error');\";\n"
        "        }\n"
        "        // Must be final/effectively-final for use inside lambda\n"
        "        final String finalJs = js;\n"
        "        getBridge().getWebView().post(() ->\n"
        "            getBridge().getWebView().evaluateJavascript(finalJs, null));\n"
        "    }\n"
        "\n"
        "    // ── 3. LIFECYCLE ──────────────────────────────────────────────────────\n"
        "    @Override\n"
        "    protected void onCreate(Bundle savedInstanceState) {\n"
        "        super.onCreate(savedInstanceState);\n"
        "\n"
        "        // FIX #5: OnBackPressedDispatcher replaces deprecated onBackPressed().\n"
        "        // Navigates WebView history, exits only from the root page.\n"
        "        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {\n"
        "            @Override\n"
        "            public void handleOnBackPressed() {\n"
        "                WebView wv = getBridge().getWebView();\n"
        "                if (wv != null && wv.canGoBack()) {\n"
        "                    wv.goBack();\n"
        "                } else {\n"
        "                    setEnabled(false);\n"
        "                    getOnBackPressedDispatcher().onBackPressed();\n"
        "                }\n"
        "            }\n"
        "        });\n"
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
