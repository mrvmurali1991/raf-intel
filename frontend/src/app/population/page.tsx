import { redirect } from "next/navigation";

/** /population → /population/heatmap (canonical population route) */
export default function PopulationRedirect() {
  redirect("/population/heatmap");
}
