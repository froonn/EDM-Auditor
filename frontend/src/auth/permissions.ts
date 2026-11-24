/**
 * Effective permissions computed by the server from the union of all groups a user belongs to.
 * Screens check these permissions and never hard-code group names.
 */
export const PERMISSIONS = [
  "documents.upload",
  "documents.read_all",
  "documents.delete_own",
  "documents.delete_any",
  "audit.run",
  "reports.read",
  "reports.export",
  "resolutions.write",
  "legal_acts.read",
  "legal_acts.edit",
  "rules.read",
  "rules.edit",
  "document_types.read",
  "document_types.edit",
  "users.manage",
  "groups.manage",
] as const;

export type Permission = (typeof PERMISSIONS)[number];

const PERMISSION_SET: ReadonlySet<string> = new Set(PERMISSIONS);

export function isPermission(value: string): value is Permission {
  return PERMISSION_SET.has(value);
}
