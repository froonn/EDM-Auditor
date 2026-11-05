import { describe, expect, it } from "vitest";

import type { Finding, Report } from "@/api/types";

import { toReportView } from "./reportModel";

function finding(overrides: Partial<Finding>): Finding {
  return {
    id: 1,
    rule_id: 1,
    legal_act_id: 1,
    severity: "high",
    description: "Норма",
    start_char: 0,
    end_char: 4,
    quote: "Срок",
    recommendation: null,
    finding_key: null,
    ...overrides,
  };
}

function report(overrides: Partial<Report>): Report {
  return {
    id: 1,
    document_id: 1,
    total_findings: 0,
    critical_count: 0,
    high_count: 0,
    medium_count: 0,
    low_count: 0,
    summary: {},
    created_at: "2026-11-05T09:00:00",
    findings: [],
    neural_status: "completed",
    ...overrides,
  };
}

describe("toReportView", () => {
  it("joins the model analysis by finding_key and prefers its recommendation", () => {
    const view = toReportView(
      report({
        findings: [
          finding({ id: 1, finding_key: "a", recommendation: "Из правила" }),
          finding({ id: 2, start_char: 10, end_char: 12, recommendation: "Из правила" }),
        ],
        neural_analyses: [
          { finding_key: "a", explanation: "Срок меньше", recommendation: "Увеличьте срок", confidence: 1, legal_basis: [] },
        ],
      }),
    );
    expect(view.findings.map((item) => [item.finding.id, item.analysis?.explanation, item.recommendation])).toEqual([
      [1, "Срок меньше", "Увеличьте срок"],
      [2, undefined, "Из правила"],
    ]);
  });

  it("orders findings by position and puts those without one last", () => {
    const view = toReportView(
      report({
        findings: [
          finding({ id: 1, start_char: null, end_char: null }),
          finding({ id: 2, start_char: 20, end_char: 25 }),
          finding({ id: 3, start_char: 5, end_char: 8 }),
        ],
      }),
    );
    expect(view.findings.map((item) => [item.finding.id, item.positioned])).toEqual([
      [3, true],
      [2, true],
      [1, false],
    ]);
  });

  it("reads the summary and the selection defensively", () => {
    const view = toReportView(
      report({
        summary: {
          neural: { general_summary: "Найдено два нарушения." },
          rejected_candidates: [{ rule_code: "R1", quote: "7 дней", reason: "Это длительность поездки" }, "broken"],
          diagnostics: [{ rule_code: "R2", message: "invalid regex" }],
        },
        selection: {
          selection_mode: "automatic",
          applied_legal_acts: [{ id: 1, code: "ACT", title: "Положение" }],
          applied_rule_ids: [1, 2, 3],
        },
      }),
    );
    expect(view.generalSummary).toBe("Найдено два нарушения.");
    expect(view.rejected).toEqual([{ ruleCode: "R1", quote: "7 дней", reason: "Это длительность поездки" }]);
    expect(view.diagnostics).toEqual([{ ruleCode: "R2", message: "invalid regex" }]);
    expect(view.selection).toEqual({
      mode: "automatic",
      legalActs: [{ id: 1, code: "ACT", title: "Положение" }],
      appliedRuleCount: 3,
    });
  });

  it("accepts an old report without summary fields", () => {
    const view = toReportView(report({ summary: {}, selection: null }));
    expect(view).toMatchObject({ generalSummary: undefined, rejected: [], diagnostics: [], selection: null, passedRules: null });
  });

  it("lists applied rules without findings as passed", () => {
    const reason = (rule_id: number, rule_code: string, selected = true) => ({
      rule_id,
      rule_code,
      name: `Правило ${rule_code}`,
      legal_act_id: 1,
      selected,
    });
    const view = toReportView(
      report({
        findings: [finding({ rule_id: 1, rule_code: "R1" }), finding({ id: 2, rule_id: null, rule_code: "R2" })],
        summary: {
          diagnostics: [{ rule_code: "R3", message: "invalid regex" }],
          rejected_candidates: [{ rule_code: "R4", quote: "7 дней", reason: "длительность поездки" }],
        },
        selection: {
          applied_legal_acts: [{ id: 1, code: "ACT", title: "Положение" }],
          selection_reasons: [
            reason(1, "R1"),
            reason(2, "R2"),
            reason(3, "R3"),
            reason(4, "R4"),
            reason(5, "R5"),
            reason(6, "R6", false),
          ],
        },
      }),
    );
    expect(view.passedRules).toEqual([
      {
        ruleId: 4,
        ruleCode: "R4",
        name: "Правило R4",
        legalAct: "Положение (ACT)",
        rejected: [{ ruleCode: "R4", quote: "7 дней", reason: "длительность поездки" }],
      },
      { ruleId: 5, ruleCode: "R5", name: "Правило R5", legalAct: "Положение (ACT)", rejected: [] },
    ]);
  });
});
