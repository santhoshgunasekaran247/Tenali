import type { DeletionPreview } from "../types";

export const canDeleteTransactions = (role?: string | null) => role === "owner" || role === "admin";

export const confirmationMatches = (preview: DeletionPreview, typed: string) => typed.trim() === preview.confirm_text;

export const deletionTotal = (preview: DeletionPreview) => preview.deletes.reduce((sum, group) => sum + group.count, 0);

/** Step 1 may continue only when nothing blocks the deletion and critical children were explicitly included. */
export function reviewState(preview: DeletionPreview, acknowledged: boolean) {
  if (preview.blockers.length) return { ready: false, reason: "Resolve the blocking items first." };
  if (preview.critical.length && !preview.cascade) return { ready: false, reason: "Delete the linked records first, or choose to delete everything together." };
  if (!acknowledged) return { ready: false, reason: "Confirm that you have reviewed everything that will be deleted." };
  return { ready: preview.can_delete, reason: preview.can_delete ? "" : "This deletion is not allowed." };
}

export const signed = (value: number) => `${value > 0 ? "+" : ""}${Number(value).toLocaleString("en-IN", { maximumFractionDigits: 3 })}`;
