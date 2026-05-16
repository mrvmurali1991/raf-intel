"use client";

/**
 * ProfileServerForm — thin Client Component wrapper that wires
 * useActionState to the updateProfile Server Action.
 *
 * This is the NEW preferred path for profile saves.
 * The legacy ProfileSection (axios PUT /api/auth/me) is kept as a fallback
 * and still renders; this form is inserted alongside it as the RSC pattern
 * demonstration.  Once fully validated, ProfileSection can be removed.
 *
 * TODO(migration): retire ProfileSection once Server Action path is proven stable.
 */

import { useActionState } from "react";
import { updateProfile, type UpdateProfileState } from "./actions";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { CheckCircle2, AlertCircle, Loader2 } from "lucide-react";

const initialState: UpdateProfileState = { status: "idle", message: "" };

const inputClasses =
  "h-10 rounded-xl border-border/60 bg-muted/30 transition-all duration-200 focus:bg-background focus:border-blue-500/50 focus:ring-2 focus:ring-blue-500/20 focus:shadow-[0_0_0_3px_rgba(59,130,246,0.1)] placeholder:text-muted-foreground/50";

const primaryBtnClasses =
  "h-10 rounded-xl font-semibold text-sm bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-700 hover:to-blue-600 shadow-lg shadow-blue-500/20 hover:shadow-blue-500/30 transition-all duration-200 btn-press";

interface Props {
  defaultFirstName?: string;
  defaultLastName?: string;
  defaultTitle?: string;
  defaultAvatarUrl?: string;
}

export function ProfileServerForm({
  defaultFirstName = "",
  defaultLastName = "",
  defaultTitle = "",
  defaultAvatarUrl = "",
}: Props) {
  const [state, formAction, isPending] = useActionState(updateProfile, initialState);

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-blue-500 dark:text-blue-400">
        <span className="inline-flex items-center rounded-full bg-blue-500/10 border border-blue-500/20 px-2 py-0.5">
          Server Action (RSC)
        </span>
      </div>

      <form action={formAction} className="space-y-5">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label
              htmlFor="sa-first-name"
              className="text-xs font-semibold uppercase tracking-wider text-muted-foreground"
            >
              First name
            </label>
            <Input
              id="sa-first-name"
              name="first_name"
              defaultValue={defaultFirstName}
              placeholder="First name"
              className={inputClasses}
              required
            />
          </div>
          <div className="space-y-1.5">
            <label
              htmlFor="sa-last-name"
              className="text-xs font-semibold uppercase tracking-wider text-muted-foreground"
            >
              Last name
            </label>
            <Input
              id="sa-last-name"
              name="last_name"
              defaultValue={defaultLastName}
              placeholder="Last name"
              className={inputClasses}
              required
            />
          </div>
        </div>

        <div className="space-y-1.5">
          <label
            htmlFor="sa-title"
            className="text-xs font-semibold uppercase tracking-wider text-muted-foreground"
          >
            Title / Credentials
          </label>
          <Input
            id="sa-title"
            name="title"
            defaultValue={defaultTitle}
            placeholder="e.g. MD, RN, CPC"
            className={inputClasses}
          />
        </div>

        <div className="space-y-1.5">
          <label
            htmlFor="sa-avatar-url"
            className="text-xs font-semibold uppercase tracking-wider text-muted-foreground"
          >
            Avatar URL
          </label>
          <Input
            id="sa-avatar-url"
            name="avatar_url"
            defaultValue={defaultAvatarUrl}
            placeholder="https://..."
            type="url"
            className={inputClasses}
          />
        </div>

        {state.status !== "idle" && (
          <div
            role={state.status === "error" ? "alert" : "status"}
            className={`flex items-center gap-2.5 rounded-xl p-3 text-sm border animate-scale-in ${
              state.status === "success"
                ? "bg-emerald-50 dark:bg-emerald-950/40 border-emerald-200 dark:border-emerald-800/60 text-emerald-700 dark:text-emerald-300"
                : "bg-red-50 dark:bg-red-950/40 border-red-200 dark:border-red-800/60 text-red-700 dark:text-red-300"
            }`}
          >
            {state.status === "success" ? (
              <CheckCircle2 className="h-4 w-4 shrink-0" />
            ) : (
              <AlertCircle className="h-4 w-4 shrink-0" />
            )}
            <span className="font-medium">{state.message}</span>
          </div>
        )}

        <div className="flex items-center gap-3 pt-1">
          <Button type="submit" disabled={isPending} className={primaryBtnClasses}>
            {isPending ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Saving...
              </>
            ) : (
              "Save Profile (Server Action)"
            )}
          </Button>
        </div>
      </form>
    </div>
  );
}
