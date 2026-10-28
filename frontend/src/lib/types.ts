export interface Account {
  id: number;
  name: string;
  institution: string | null;
  account_type: string;
  is_liability: boolean;
  currency: string;
  masked_identifier: string | null;
  opening_balance_minor: number | null;
  opening_date: string | null;
  opening_verification: "unknown" | "unverified" | "verified";
  opening_source: string | null;
  is_active: boolean;
  notes: string | null;
  default_parser: string | null;
  calculated_balance_minor: number | null;
  balance_status: "verified" | "unverified" | "estimated";
  coverage_start: string | null;
  coverage_end: string | null;
  last_statement_date: string | null;
  last_statement_balance_minor: number | null;
  last_import_at: string | null;
  reconciliation_status: string;
  statement_count: number;
  first_transaction_date: string | null;
  last_transaction_date: string | null;
  coverage_gaps?: { from: string; to: string }[];
  statements?: Statement[];
}

export interface Statement {
  id: number;
  account_id: number;
  account_name?: string;
  import_batch_id: number;
  start_date: string | null;
  end_date: string | null;
  reported_opening_minor: number | null;
  reported_closing_minor: number | null;
  calculated_closing_minor: number | null;
  discrepancy_minor: number | null;
  reconciliation_status: "reconciled" | "discrepancy" | "unverifiable";
  notes: string | null;
}

export interface Txn {
  id: number;
  account_id: number;
  account_name: string | null;
  transaction_date: string;
  posting_date: string | null;
  original_description: string;
  normalized_description: string;
  merchant: string | null;
  amount_minor: number;
  original_amount_minor: number;
  direction: "debit" | "credit";
  transaction_type: string | null;
  reference: string | null;
  balance_after_minor: number | null;
  category_id: number | null;
  category_name: string | null;
  category_source: string;
  tags: string[];
  notes: string | null;
  review_status: string;
  reconciliation_status: string;
  duplicate_status: string;
  source_row_reference: string | null;
  parser_name: string | null;
  is_manual: boolean;
  import_batch_id: number | null;
  reporting_parts?: { class: string; amount_minor: number }[];
}

export interface Category {
  id: number;
  name: string;
  parent_id: number | null;
  reporting_type: string;
  is_active: boolean;
  is_system: boolean;
  transaction_count: number;
}

export interface ImportRow {
  id: number;
  row_index: number;
  source_ref: string | null;
  raw: Record<string, unknown>;
  txn_date: string | null;
  posting_date: string | null;
  description: string | null;
  reference: string | null;
  debit_minor: number | null;
  credit_minor: number | null;
  amount_minor: number | null;
  balance_minor: number | null;
  include: boolean;
  include_override: boolean | null;
  status: "ok" | "warning" | "error";
  errors: string[];
  warnings: string[];
  duplicate_status: "none" | "exact" | "possible";
  duplicate_of_transaction_id: number | null;
  user_edited: boolean;
}

export interface Validation {
  row_count: number;
  error_rows: number;
  total_debits: string;
  total_credits: string;
  net_movement: string;
  opening_balance: string | null;
  closing_balance_reported: string | null;
  closing_balance_calculated: string | null;
  closing_difference: string | null;
  balance_check: "passed" | "failed" | "unverifiable";
  running_balance_check: "passed" | "failed" | "unavailable";
  running_balance_breaks: { row_index: number; expected: string; reported: string; difference: string }[];
  sign_hint: string | null;
  first_date: string | null;
  last_date: string | null;
  messages: string[];
}

export interface Batch {
  id: number;
  account_id: number | null;
  filename: string;
  file_type: string;
  file_size: number;
  has_file: boolean;
  parser_name: string | null;
  parser_version: string | null;
  parser_confidence: number | null;
  detected_statement_type: string | null;
  status: "preview" | "committed" | "failed" | "discarded" | "deleted";
  row_counts: Record<string, number>;
  warnings: string[];
  validation: Validation;
  statement_meta: {
    period_start?: string | null;
    period_end?: string | null;
    opening_balance_minor?: number | null;
    closing_balance_minor?: number | null;
    account_hint?: string | null;
    needs_mapping?: boolean;
    mapping_used?: Record<string, string> | null;
    header_columns?: string[];
    candidate_headers?: string[][];
    ignored_lines?: { ref: string; text: string; reason: string }[];
    ignored_line_count?: number;
    statement_type?: string;
    reprocess_summary?: Record<string, unknown>;
    account_suggested?: boolean;
  };
  extraction_info: Record<string, unknown> & { error_code?: string; is_scanned?: boolean; ocr_used?: boolean };
  repeat_of_batch_id: number | null;
  reprocess_of_batch_id: number | null;
  error_message: string | null;
  created_at: string;
  committed_at: string | null;
  rows?: ImportRow[];
  rows_total?: number;
}

export interface Relationship {
  id: number;
  source_transaction_id: number;
  related_transaction_id: number;
  relationship_type: string;
  matched_amount_minor: number | null;
  review_status: "suggested" | "approved" | "rejected" | "undone";
  score: number | null;
  matching_reason: { reasons?: string[]; amount_difference_minor?: number; days_apart?: number } | null;
  source: Txn | null;
  related: Txn | null;
}

export interface Paged<T> {
  total: number;
  items: T[];
}
