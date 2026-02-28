# PanoView — 360° Panorama Downloader

A mobile Android app (built with Capacitor) for downloading full-resolution 360° panoramas from Google Maps, Street View, and Google Earth links.

---

## Features

- **Street View tile stitching** — Downloads and stitches tiles at zoom levels Z1–Z5 (up to ~13K resolution) into a single equirectangular image
- **User 360° panoramas** — Downloads user-uploaded Photo Sphere / 360° images via direct lh3 URL or Android-assisted token fetching
- **Auto token fetching** — On Android, opens a background WebView to automatically extract the image token from user panoramas (no manual steps needed)
- **XMP + GPS metadata injection** — Saves output as a proper Photo Sphere JPEG with `GPano:*` XMP tags and EXIF GPS coordinates
- **360° preview** — In-app equirectangular preview using [Pannellum](https://pannellum.org/) before downloading
- **Bulk download** — Parse and download multiple URLs in one batch
- **Share intent** — Share a Maps/Earth URL directly from the Google Maps app or browser into PanoView
- **Gallery save** — Saves images directly to `Pictures/PanoView` via Android MediaStore (Android 10+) or legacy file system

---

## Supported URL Types

| Source | Example |
|---|---|
| Google Maps Street View | `https://www.google.com/maps/@lat,lng,3a,...` |
| Google Earth app links | `https://earth.app.goo.gl/...` |
| Direct pano IDs | `AF1Q...` / `CI...` / 22-char base IDs |
| Google Maps with `!1s` pano token | Full Maps URL with `data=!3m...!1s<id>` |
| User 360° with `!6s` lh3 token | Full Maps URL after Street View fully loads |

---

## Project Structure

```
panoview/
├── index.html              # Main app UI and all JavaScript logic
├── capacitor.config.json   # Capacitor app configuration
├── package.json            # npm dependencies
├── patch_android.py        # Android project patcher (icons, manifest, MainActivity)
└── .github/
    └── workflows/
        └── build.yml       # GitHub Actions CI — builds debug APK automatically
```

---

## How It Works

### Street View Panoramas

PanoView fetches tiles from `cbk0.google.com/cbk` using the pano ID and selected zoom level, draws them onto an HTML5 Canvas, then exports as JPEG with injected XMP Photo Sphere metadata and EXIF GPS.

Zoom levels and approximate resolutions:

| Zoom | Tiles (cols × rows) | Approximate resolution |
|---|---|---|
| Z1 | 2 × 1 | ~512px |
| Z2 | 4 × 2 | ~1K |
| Z3 | 8 × 4 | ~2K (default) |
| Z4 | 16 × 8 | ~4K |
| Z5 | 32 × 16 | ~13K |

Exact tile counts are fetched from the Street View metadata API for accuracy at Z5.

### User / Photo Sphere Panoramas

For user-uploaded panoramas (pano IDs starting with `CI...` or `AF1Q...`), PanoView attempts to fetch the full-res image from `lh3.googleusercontent.com`. If no direct URL is available:

1. **On Android (with bridge):** A background bottom-sheet WebView loads the Maps page with a desktop user-agent and polls the URL every second for a `!6s` lh3 token. Once found, it's passed back to the main WebView via `window._panoTokenResult()`.
2. **Manual fallback:** The app shows a "Step 2" flow — open Maps, wait for Street View to load, then paste the full URL back into the app.

---

## Building

### Prerequisites

- Node.js 18+
- Java 17
- Android SDK (API 33 + build-tools 33.0.2)

### Steps

```bash
# Install dependencies
npm install

# Prepare www folder
mkdir -p www && cp index.html www/index.html

# Add Android platform
npx cap add android

# Patch Android project (icons, manifest, MainActivity)
python3 patch_android.py

# Sync Capacitor
npx cap sync android

# Build debug APK
cd android && ./gradlew assembleDebug
```

The APK will be at `android/app/build/outputs/apk/debug/app-debug.apk`.

### CI (GitHub Actions)

Pushing to `main` automatically triggers `.github/workflows/build.yml`, which builds a debug APK and uploads it as an artifact (`PanoView-debug-apk`) retained for 30 days.

---

## Android Patches (`patch_android.py`)

The patcher runs automatically during the build and applies the following:

- **Launcher icons** — Generates flat PNG icons in all densities (mdpi → xxxhdpi) and adaptive icon XML for API 26+
- **AndroidManifest.xml** — Adds internet + storage permissions, cleartext traffic, network security config, and intent filters for `ACTION_SEND` (share) and `ACTION_VIEW` (Maps/Earth deep links)
- **MainActivity.java** — Rewrites the activity with:
  - Back button/gesture navigation through WebView history
  - `AndroidSave` JavaScript bridge — saves images to MediaStore / Gallery
  - `AndroidTokenFetcher` JavaScript bridge — bottom-sheet WebView token fetcher for user panoramas
  - Share intent handler (`handleSharedUrl`)
- **network_security_config.xml** — Permits cleartext traffic to `cbk0.google.com`, `lh3.googleusercontent.com`, and `maps.googleapis.com`

---

## JavaScript Bridges (Android ↔ WebView)

### `window.AndroidSave.saveImage(base64Data, filename)`

Called from JS to save a base64-encoded JPEG to the device gallery.

### `window.AndroidTokenFetcher.fetch(mapsUrl)`

Called from JS to open a background bottom-sheet WebView that loads the given Maps URL and polls for a `!6s` lh3 token. Result is delivered via:

```javascript
window._panoTokenResult(token, error)
// token: lh3 URL string on success
// error: 'timeout' | 'cancelled' | null
```

### `window.handleSharedUrl(url)`

Called by Android when a URL is shared into the app from another application.

---

## Output Format

All downloaded images are saved as JPEG with:

- **XMP Photo Sphere metadata** (`GPano:ProjectionType`, `GPano:FullPanoWidthPixels`, etc.) — recognized by Google Photos, Facebook, and most 360° viewers
- **EXIF GPS** (`GPSLatitude`, `GPSLongitude`) — embedded when coordinates are available from the source URL

Output filenames:
- Street View: `panoview_sv_<panoId_prefix>_z<zoom>.jpg`
- User panorama: `panoview_user_<panoId_prefix>.jpg`

---

## License

This project is provided as-is for personal use.
