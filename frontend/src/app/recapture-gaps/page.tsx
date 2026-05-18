import { redirect } from "next/navigation";

/** /recapture-gaps → /recapture (canonical recapture route) */
export default function RecaptureGapsRedirect() {
  redirect("/recapture");
}
