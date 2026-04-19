<?php
/**
 * RAF Central — OpenEMR patient-chart sidebar launcher.
 *
 * Renders a full-height iframe that hosts the RAF Central panel for the
 * currently-selected patient. It mints a short-lived HMAC-signed JWT and
 * hands it to the iframe so the embed route can exchange it for a real RAF
 * session without the user ever typing credentials.
 *
 * Install:
 *   1. Drop this folder into the OpenEMR root (e.g. /var/www/localhost/htdocs/openemr/interface/modules/raf-central/).
 *   2. Configure:
 *        - RAF_EMBED_SECRET : shared HMAC secret (must match backend OPENEMR_EMBED_SECRET)
 *        - RAF_FRONTEND_URL : https URL of the RAF Intelligence frontend (e.g. https://raf.example.com)
 *        - RAF_USER_EMAIL   : the RAF user whose scope the iframe will run under
 *        - RAF_TENANT_ID    : (optional) tenant id; omit for single-tenant
 *      All via the OpenEMR admin panel (Administration → Globals → Custom) or
 *      a site-specific config file.
 *   3. Add a link from the patient chart:
 *        interface/patient_file/summary/demographics.php
 *      → append a sidebar button that opens this script in an iframe or
 *        popout window with the current patient pid.
 *
 * Query string:
 *   ?pid=<openemr_patient_id>    required
 *   ?year=<YYYY>                 optional — pins the panel to a specific RAF year
 *
 * Security notes:
 *   - The embed token's TTL is 5 minutes. If the user parks the chart tab
 *     that long and re-opens, the iframe performs a silent refresh using the
 *     httpOnly cookie the exchange set on first load.
 *   - The HMAC secret must only be configured server-side. Never emit it
 *     into HTML/JS.
 *   - This file runs inside the OpenEMR session, so we can safely trust
 *     `$_SESSION['authUser']` for audit purposes.
 */

require_once(__DIR__ . "/../../globals.php");

use OpenEMR\Common\Csrf\CsrfUtils;
use OpenEMR\Common\Logging\SystemLogger;

// ---------------------------------------------------------------------------
// Configuration — pulled from OpenEMR globals or env. Fail loudly if missing.
// ---------------------------------------------------------------------------

function raf_env(string $key, ?string $fallback = null): string
{
    // Prefer OpenEMR-managed globals, fall back to process env, finally the
    // caller-supplied default. Empty strings count as "not set".
    $val = $GLOBALS[$key] ?? getenv($key) ?: "";
    if ($val === "" || $val === false) {
        if ($fallback !== null) return $fallback;
        http_response_code(500);
        echo "<h1>RAF Central not configured</h1>";
        echo "<p>Missing configuration: <code>" . htmlspecialchars($key) . "</code></p>";
        echo "<p>Set it in OpenEMR Globals or as an environment variable.</p>";
        exit;
    }
    return (string)$val;
}

$raf_secret       = raf_env("RAF_EMBED_SECRET");
$raf_frontend_url = rtrim(raf_env("RAF_FRONTEND_URL"), "/");
$raf_user_email   = raf_env("RAF_USER_EMAIL");
$raf_tenant_id    = raf_env("RAF_TENANT_ID", "");

// ---------------------------------------------------------------------------
// Input — patient id comes from the chart's current selection.
// ---------------------------------------------------------------------------

$pid  = isset($_GET["pid"])  ? (int)$_GET["pid"]  : 0;
$year = isset($_GET["year"]) ? (int)$_GET["year"] : 0;

if ($pid <= 0) {
    http_response_code(400);
    echo "<p>Missing or invalid pid.</p>";
    exit;
}

// ---------------------------------------------------------------------------
// Mint the embed JWT. We inline the HS256 signer so this file has zero
// composer dependencies beyond OpenEMR itself — drop-in install.
// ---------------------------------------------------------------------------

function b64url(string $bytes): string
{
    return rtrim(strtr(base64_encode($bytes), "+/", "-_"), "=");
}

function mint_embed_token(
    string $secret,
    string $subEmail,
    int $pid,
    string $tenantId,
    int $ttlSeconds = 300
): string {
    $now = time();
    $header  = ["typ" => "JWT", "alg" => "HS256"];
    $payload = [
        "sub"  => $subEmail,
        "pid"  => $pid,
        "iat"  => $now,
        "exp"  => $now + max(30, min($ttlSeconds, 600)),
        "type" => "embed",
    ];
    if ($tenantId !== "") {
        $payload["tenant_id"] = $tenantId;
    }
    $h = b64url(json_encode($header, JSON_UNESCAPED_SLASHES));
    $p = b64url(json_encode($payload, JSON_UNESCAPED_SLASHES));
    $sig = b64url(hash_hmac("sha256", "$h.$p", $secret, true));
    return "$h.$p.$sig";
}

$embed_token = mint_embed_token(
    $raf_secret,
    $raf_user_email,
    $pid,
    $raf_tenant_id,
    300
);

$iframe_src = sprintf(
    "%s/embed/raf-central/%d?t=%s%s",
    $raf_frontend_url,
    $pid,
    rawurlencode($embed_token),
    $year > 0 ? "&year=" . $year : ""
);

// Log the launch in the OpenEMR system log for audit/compliance.
try {
    (new SystemLogger())->info(
        "RAF Central iframe launched",
        [
            "pid" => $pid,
            "user" => $_SESSION["authUser"] ?? "unknown",
            "tenant_id" => $raf_tenant_id,
        ]
    );
} catch (\Throwable $e) {
    // Don't fail the render on audit log issues.
}

?><!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>RAF Central</title>
    <style>
        html, body { margin: 0; padding: 0; height: 100%; background: #0f172a; }
        iframe { border: 0; width: 100%; height: 100%; display: block; }
        .wrap { height: 100%; display: flex; flex-direction: column; }
        .bar {
            flex: 0 0 32px; background: #0b1220; color: #cbd5e1;
            font: 12px system-ui; display: flex; align-items: center;
            padding: 0 10px; justify-content: space-between;
        }
        .bar .title { font-weight: 600; letter-spacing: 0.3px; }
        .bar a { color: #60a5fa; text-decoration: none; }
    </style>
</head>
<body>
    <div class="wrap">
        <div class="bar">
            <span class="title">RAF Central · Patient <?php echo (int)$pid; ?></span>
            <a href="<?php echo htmlspecialchars($raf_frontend_url, ENT_QUOTES); ?>/patients/<?php echo (int)$pid; ?>" target="_blank" rel="noopener">
                Open full page ↗
            </a>
        </div>
        <iframe
            src="<?php echo htmlspecialchars($iframe_src, ENT_QUOTES); ?>"
            allow="clipboard-read; clipboard-write"
            referrerpolicy="no-referrer-when-downgrade"
            title="RAF Central panel"
        ></iframe>
    </div>
</body>
</html>
