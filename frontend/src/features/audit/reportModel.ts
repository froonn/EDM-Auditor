import type { Finding, NeuralAnalysis, Report } from "@/api/types";

import { hasPosition, severityRank } from "./highlight";

/** `summary` and `selection` are free-form objects in OpenAPI, so every field is checked here. */
type Json = Record<string, unknown>;

const isObject = (value: unknown): value is Json =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): string | undefined =>
  typeof value === "string" && value.trim() ? value : undefined;
const integer = (value: unknown): number | undefined => (Number.isInteger(value) ? (value as number) : undefined);
const objects = (value: unknown): Json[] => (Array.isArray(value) ? value.filter(isObject) : []);

export interface RejectedCandidate {
  ruleCode: string | undefined;
  quote: string | undefined;
  reason: string | undefined;
}

export interface Diagnostic {
  ruleCode: string | undefined;
  message: string | undefined;
}

export interface PassedRule {
  ruleId: number | undefined;
  ruleCode: string | undefined;
  name: string | undefined;
  legalAct: string | undefined;
  /** Candidates the check found, but the model decided that the norm was kept. */
  rejected: RejectedCandidate[];
}

export interface AppliedSelection {
  mode: string | undefined;
  legalActs: { id: number | undefined; code: string | undefined; title: string | undefined }[];
  appliedRuleCount: number;
}

export interface ReportView {
  generalSummary: string | undefined;
  rejected: RejectedCandidate[];
  diagnostics: Diagnostic[];
  selection: AppliedSelection | null;
  findings: FindingView[];
  /** Applied rules without findings; `null` for reports saved before the selection was stored. */
  passedRules: PassedRule[] | null;
}

export interface FindingView {
  finding: Finding;
  analysis: NeuralAnalysis | undefined;
  /** The model's recommendation, or the one written in a manual rule. */
  recommendation: string | undefined;
  positioned: boolean;
}

export function toReportView(report: Report): ReportView {
  const summary = isObject(report.summary) ? report.summary : {};
  const neural = isObject(summary.neural) ? summary.neural : {};
  const analyses = new Map((report.neural_analyses ?? []).map((item) => [item.finding_key, item]));

  const findings = report.findings
    .map((finding): FindingView => {
      const analysis = finding.finding_key ? analyses.get(finding.finding_key) : undefined;
      return {
        finding,
        analysis,
        recommendation: text(analysis?.recommendation) ?? text(finding.recommendation),
        positioned: hasPosition({ start: finding.start_char, end: finding.end_char }),
      };
    })
    .sort(compareFindings);

  return {
    findings,
    generalSummary: text(neural.general_summary),
    rejected: objects(summary.rejected_candidates).map((item) => ({
      ruleCode: text(item.rule_code),
      quote: text(item.quote),
      reason: text(item.reason),
    })),
    diagnostics: objects(summary.diagnostics).map((item) => ({
      ruleCode: text(item.rule_code),
      message: text(item.message),
    })),
    selection: toSelection(report.selection),
    passedRules: toPassedRules(report),
  };
}

/**
 * Applied rules minus those with findings and those that could not be evaluated. Rules are matched
 * by code as well, because the rule itself may have been deleted since the audit.
 */
function toPassedRules(report: Report): PassedRule[] | null {
  const selection = isObject(report.selection) ? report.selection : null;
  if (!selection || !Array.isArray(selection.selection_reasons)) return null;
  const summary = isObject(report.summary) ? report.summary : {};
  const violatedIds = new Set(report.findings.map((item) => item.rule_id).filter((id) => id !== null && id !== undefined));
  const violatedCodes = new Set(report.findings.map((item) => item.rule_code).filter(Boolean));
  const failedCodes = new Set(objects(summary.diagnostics).map((item) => text(item.rule_code)));
  const rejected = objects(summary.rejected_candidates).map((item) => ({
    ruleCode: text(item.rule_code),
    quote: text(item.quote),
    reason: text(item.reason),
  }));
  const acts = new Map(
    objects(selection.applied_legal_acts).map((act) => [integer(act.id), [text(act.title), text(act.code) && `(${text(act.code)})`].filter(Boolean).join(" ")]),
  );
  return objects(selection.selection_reasons)
    .filter((item) => item.selected === true)
    .map((item) => ({
      ruleId: integer(item.rule_id),
      ruleCode: text(item.rule_code),
      name: text(item.name),
      legalAct: acts.get(integer(item.legal_act_id)) || undefined,
      rejected: rejected.filter((candidate) => candidate.ruleCode !== undefined && candidate.ruleCode === text(item.rule_code)),
    }))
    .filter(
      (rule) =>
        !(rule.ruleId !== undefined && violatedIds.has(rule.ruleId)) &&
        !(rule.ruleCode !== undefined && (violatedCodes.has(rule.ruleCode) || failedCodes.has(rule.ruleCode))),
    );
}

function toSelection(value: unknown): AppliedSelection | null {
  if (!isObject(value)) return null;
  return {
    mode: text(value.selection_mode),
    legalActs: objects(value.applied_legal_acts).map((act) => ({
      id: integer(act.id),
      code: text(act.code),
      title: text(act.title),
    })),
    appliedRuleCount: Array.isArray(value.applied_rule_ids) ? value.applied_rule_ids.length : 0,
  };
}

/** Findings follow the document; those without a position go last. */
function compareFindings(a: FindingView, b: FindingView): number {
  if (a.positioned !== b.positioned) return a.positioned ? -1 : 1;
  const byPosition = (a.finding.start_char ?? 0) - (b.finding.start_char ?? 0);
  return byPosition || severityRank(a.finding.severity) - severityRank(b.finding.severity) || a.finding.id - b.finding.id;
}
