#!/usr/bin/env node
/**
 * One-shot cleanup: removes any auto-sync test patients (Chen lname, or
 * fname starting with Sarah<digits>) left over from a partial Playwright
 * run, plus their downstream RAF/auto-sync rows.
 */
import { execSync } from "node:child_process";

function ex(sql, db = "openemr") {
  try {
    return execSync(
      `docker exec raf-mysql mysql -uroot -proot ${db} -e ${JSON.stringify(sql)} 2>/dev/null`,
      { encoding: "utf8", timeout: 15_000 }
    );
  } catch (e) { return ""; }
}

const before = ex("SELECT COUNT(*) FROM patient_data WHERE lname='Chen' OR fname LIKE 'Sarah%';");
console.log("openemr cleanup before:", before.trim());
ex("DELETE FROM patient_data WHERE lname='Chen' OR fname LIKE 'Sarah%';");
const remaining = ex("SELECT COUNT(*) FROM patient_data WHERE lname='Chen' OR fname LIKE 'Sarah%';");
console.log("openemr cleanup after:", remaining.trim());
ex("DELETE rs FROM raf_scores rs WHERE rs.patient_id NOT IN (SELECT pid FROM openemr.patient_data);", "raf_intelligence");
ex("DELETE FROM auto_sync_failed_pids;", "raf_intelligence");
console.log("✓ cleanup done");
