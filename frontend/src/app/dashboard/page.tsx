import { redirect } from "next/navigation";

/** /dashboard → / (canonical dashboard route) */
export default function DashboardRedirect() {
  redirect("/");
}
