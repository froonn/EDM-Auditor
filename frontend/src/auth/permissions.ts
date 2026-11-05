/**
 * Actions that may later be limited by role. Screens check these permissions and never roles.
 * The mapping from roles to permissions is decided in the diploma project (docs/DIPLOMA.md).
 */
export const PERMISSIONS = [
  "documents.upload",
  "audit.run",
  "reports.read",
  "reports.export",
  "rules.edit",
  "legal_acts.edit",
  "document_types.edit",
] as const;

export type Permission = (typeof PERMISSIONS)[number];
