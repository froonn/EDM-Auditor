import type { DocumentDetail, DocumentItem, DocumentType, Finding, Report } from "@/api/types";

export const DOCUMENT_TYPES: DocumentType[] = [
  { code: "remote_work_agreement", name: "Соглашение о дистанционной работе", description: "", is_active: true },
  { code: "payroll_order", name: "Приказ о выплатах", description: "", is_active: true },
];

export function documentItem(overrides: Partial<DocumentItem> = {}): DocumentItem {
  return {
    id: 1,
    title: "remote_work_agreement",
    file_type: "txt",
    status: "audited",
    classified_type: "remote_work_agreement",
    classification_status: "classified",
    classification_confidence: 1,
    classification_source: "llm",
    confirmed_document_types: ["remote_work_agreement"],
    candidate_document_types: [{ code: "remote_work_agreement", confidence: 1 }],
    needs_configuration: false,
    created_at: "2026-11-05T09:01:07.540440",
    latest_report: null,
    ...overrides,
  };
}

export const DOCUMENT_TEXT =
  "Соглашение 😀 о дистанционной работе.\n\nУведомление направлено за 4 дня.\nКомпенсация 35 рублей.";

export function documentDetail(overrides: Partial<DocumentDetail> = {}): DocumentDetail {
  return { ...documentItem(), text: DOCUMENT_TEXT, ...overrides };
}

/** Offsets in code points, as the API counts them. */
export function offsetsOf(text: string, fragment: string): { start_char: number; end_char: number } {
  const unit = text.indexOf(fragment);
  const start = [...text.slice(0, unit)].length;
  return { start_char: start, end_char: start + [...fragment].length };
}

export function finding(overrides: Partial<Finding> = {}): Finding {
  return {
    id: 1,
    rule_id: 1,
    legal_act_id: 1,
    severity: "high",
    description: "Уведомление не позднее 10 календарных дней.",
    start_char: 0,
    end_char: 1,
    quote: null,
    recommendation: null,
    finding_key: null,
    rule_code: "ACT-1",
    rule_name: "Срок уведомления",
    legal_act_code: "ACT-REMOTE",
    legal_act_title: "Положение о дистанционной работе",
    // Legal acts wrap lines in the middle of a sentence; the quote keeps the break.
    norm_quote: "Работодатель обязан уведомить не позднее\n\n10 календарных дней.",
    ...overrides,
  };
}

export function report(overrides: Partial<Report> = {}): Report {
  const notice = offsetsOf(DOCUMENT_TEXT, "4 дня");
  const money = offsetsOf(DOCUMENT_TEXT, "35 рублей");
  return {
    id: 10,
    document_id: 1,
    total_findings: 3,
    critical_count: 0,
    high_count: 1,
    medium_count: 1,
    low_count: 1,
    summary: {
      neural: { general_summary: "Найдено два нарушения срока и суммы." },
      rejected_candidates: [{ rule_code: "ACT-3", quote: "01.03.2027", reason: "Это дата, а не срок" }],
      diagnostics: [],
    },
    created_at: "2026-11-05T10:00:00",
    neural_status: "completed",
    findings: [
      finding({ id: 1, ...notice, quote: "4 дня", finding_key: "k1" }),
      finding({
        id: 2,
        severity: "medium",
        ...money,
        quote: "35 рублей",
        rule_name: "Размер компенсации",
        description: "Компенсация не меньше 50 рублей.",
        finding_key: "k2",
      }),
      finding({ id: 3, severity: "low", start_char: null, end_char: null, rule_name: "Подпись сторон" }),
    ],
    neural_analyses: [
      { finding_key: "k1", explanation: "Уведомили за 4 дня вместо 10.", recommendation: "Уведомляйте за 10 дней.", confidence: 1, legal_basis: [] },
      { finding_key: "k2", explanation: "35 меньше 50.", recommendation: "Повысьте компенсацию.", confidence: 1, legal_basis: [] },
    ],
    selection: {
      selection_mode: "automatic",
      applied_legal_acts: [{ id: 1, code: "ACT-REMOTE", title: "Положение" }],
      applied_rule_ids: [1, 4],
      selection_reasons: [
        { rule_id: 1, rule_code: "ACT-1", name: "Срок уведомления", legal_act_id: 1, selected: true },
        { rule_id: 4, rule_code: "ACT-4", name: "Обязательная подпись", legal_act_id: 1, selected: true },
        { rule_id: 5, rule_code: "ACT-5", name: "Командировка", legal_act_id: 1, selected: false },
      ],
    },
    ...overrides,
  };
}
