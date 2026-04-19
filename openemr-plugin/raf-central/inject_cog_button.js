/**
 * OpenEMR COG-button injector — drop-in userscript that adds a "RAF Central"
 * button to the patient chart sidebar and opens cog_launcher.php in a
 * right-hand iframe overlay for the currently-selected patient.
 *
 * Installation options (pick one):
 *
 *  A. Inline via OpenEMR "Site-Specific Scripts"
 *     Admin → Globals → Custom Scripts → Patient Summary Custom Script
 *     Paste this file's contents (no wrapper needed).
 *
 *  B. Extract-template override
 *     Copy to interface/patient_file/summary/js/raf-central.js and include
 *     it from demographics.php before the closing </body> tag:
 *         <script src="js/raf-central.js?v=<?=(int)($v_js_inc ?? 0)?>"></script>
 *
 *  C. Bookmarklet (for ad-hoc demo)
 *     Wrap the IIFE below in `javascript:(function(){…})();` and save as a
 *     bookmark. Click it on any patient chart page.
 *
 * Assumes OpenEMR exposes the current pid via `window.cpid` (standard since
 * 6.x) or a hidden <input name="pid"> on the summary page.
 */

(function () {
    "use strict";

    const BTN_ID = "raf-central-cog-btn";
    const PANEL_ID = "raf-central-cog-panel";

    // ------------------------------------------------------------------
    // Resolve the current patient id. OpenEMR sets window.cpid on the
    // summary page, but the pattern has drifted across versions — we
    // probe several known locations.
    // ------------------------------------------------------------------

    function currentPid() {
        if (typeof window.cpid === "number" && window.cpid > 0) return window.cpid;
        const hidden = document.querySelector('input[name="pid"], input[name="set_pid"]');
        if (hidden && hidden.value) return parseInt(hidden.value, 10) || 0;
        try {
            if (top && top.currentPatient && top.currentPatient.pid) {
                return parseInt(top.currentPatient.pid, 10) || 0;
            }
        } catch (e) { /* cross-origin — ignore */ }
        return 0;
    }

    // ------------------------------------------------------------------
    // Toggle the side-panel iframe. Lazy-injected so OpenEMR pages that
    // never click the button pay zero cost.
    // ------------------------------------------------------------------

    function toggle(pid) {
        if (!pid) {
            alert("RAF Central: no patient selected.");
            return;
        }
        let panel = document.getElementById(PANEL_ID);
        if (panel) {
            panel.remove();
            return;
        }
        panel = document.createElement("div");
        panel.id = PANEL_ID;
        Object.assign(panel.style, {
            position: "fixed",
            top: "0",
            right: "0",
            width: "min(480px, 42vw)",
            height: "100vh",
            zIndex: "2147483647",
            boxShadow: "-8px 0 24px rgba(15, 23, 42, 0.35)",
            background: "#0f172a",
            border: "0",
            transform: "translateX(100%)",
            transition: "transform 0.2s ease-out",
        });

        const header = document.createElement("div");
        Object.assign(header.style, {
            height: "40px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "0 12px",
            background: "#0b1220",
            color: "#e2e8f0",
            font: "600 13px system-ui",
            letterSpacing: "0.3px",
        });
        const title = document.createElement("span");
        title.textContent = "RAF Central \u00B7 Patient " + pid;
        const closeBtn = document.createElement("button");
        closeBtn.type = "button";
        closeBtn.setAttribute("aria-label", "Close");
        closeBtn.textContent = "\u00D7";
        Object.assign(closeBtn.style, {
            background: "transparent",
            border: "0",
            color: "#94a3b8",
            fontSize: "18px",
            cursor: "pointer",
        });
        closeBtn.addEventListener("click", function () {
            panel.remove();
        });
        header.appendChild(title);
        header.appendChild(closeBtn);

        const iframe = document.createElement("iframe");
        iframe.src = "../modules/raf-central/cog_launcher.php?pid=" + encodeURIComponent(String(pid));
        iframe.title = "RAF Central panel";
        iframe.allow = "clipboard-read; clipboard-write";
        Object.assign(iframe.style, {
            width: "100%",
            height: "calc(100% - 40px)",
            border: "0",
        });

        panel.appendChild(header);
        panel.appendChild(iframe);
        document.body.appendChild(panel);
        requestAnimationFrame(function () {
            panel.style.transform = "translateX(0)";
        });
    }

    // ------------------------------------------------------------------
    // Inject the sidebar button. Floating bottom-right so it works on
    // whatever OpenEMR skin the user has active.
    // ------------------------------------------------------------------

    function injectButton() {
        if (document.getElementById(BTN_ID)) return;

        const btn = document.createElement("button");
        btn.id = BTN_ID;
        btn.type = "button";
        btn.textContent = "RAF Central";
        Object.assign(btn.style, {
            position: "fixed",
            bottom: "24px",
            right: "24px",
            zIndex: "2147483646",
            padding: "10px 16px",
            borderRadius: "999px",
            background: "linear-gradient(135deg,#2563eb,#7c3aed)",
            color: "#fff",
            border: "0",
            font: "600 13px system-ui",
            boxShadow: "0 6px 16px rgba(37, 99, 235, 0.35)",
            cursor: "pointer",
            letterSpacing: "0.3px",
        });
        btn.addEventListener("click", function () {
            toggle(currentPid());
        });
        document.body.appendChild(btn);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", injectButton);
    } else {
        injectButton();
    }
})();
