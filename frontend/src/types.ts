export interface Speaker {
  id: number;
  speaker_key: string;
  display_name: string;
  notes: string;
  created_at: string;
}

export interface SessionInfo {
  id: number;
  speaker_id: number;
  started_at: string;
  ended_at: string | null;
  device_info: Record<string, unknown>;
  room_tone_dbfs: number | null;
  room_tone_status: string | null;
  notes: string;
  speaker: Speaker | null;
  recording_count: number;
  accepted_count: number;
}

export type Role = "admin" | "recorder";

export interface User {
  id: number;
  username: string;
  role: Role;
  display_name: string;
  active: boolean;
  speaker_id: number | null;
  dataset_id: number | null;
  created_at: string;
  last_login_at: string | null;
  speaker: Speaker | null;
  dataset_name: string | null;
}

export interface Dataset {
  id: number;
  slug: string;
  name: string;
  description: string;
  instructions: string;
  language: string;
  languages: string[];
  dialect: string;
  text_policy: string;
  status: string;
  target_sample_count: number;
  target_avg_duration_sec: number;
  created_at: string;
  script_count: number;
  accepted_count: number;
  accepted_duration_sec: number;
  recorder_count: number;
}

export interface RecorderContext {
  dataset: Dataset | null;
  speaker: Speaker | null;
  session_id: number | null;
  progress: { total: number; done: number; remaining: number };
  next_script: Script | null;
}

export interface Script {
  id: number;
  script_id: string;
  dataset_id: number | null;
  display_text: string;
  training_text: string;
  msa_equivalent: string | null;
  language: string;
  dialect: string;
  style: string;
  domain: string;
  tags: string[];
  length_bucket: string;
  word_count: number;
  char_count: number;
  status: string;
  active: boolean;
  priority: number;
  source: string;
  generation_batch: string | null;
  generation_model: string | null;
  notes: string;
  created_at: string;
  take_count: number;
}

export interface QcIssue {
  severity: "fail" | "warn" | "info";
  code: string;
  message: string;
  value?: number;
}

export interface Recording {
  id: number;
  script_pk: number;
  session_id: number;
  speaker_id: number;
  take_number: number;
  rel_path: string;
  sample_rate: number;
  channels: number;
  sample_format: string;
  duration_sec: number;
  size_bytes: number;
  qc_status: "passed" | "warning" | "failed";
  qc_issues: QcIssue[];
  qc_metrics: Record<string, number | string>;
  asr_status: string;
  asr_text: string | null;
  asr_cer: number | null;
  asr_wer: number | null;
  asr_detail: {
    normalized_ref?: string;
    normalized_hyp?: string;
    has_latin?: boolean;
    error?: string;
    thresholds?: { match: number; minor: number };
  };
  human_status: "pending" | "accepted" | "rejected";
  review_note: string;
  forced_save: boolean;
  final_text: string | null;
  text_edited: boolean;
  created_at: string;
  reviewed_at: string | null;
  script: Script | null;
}

export interface AppStatus {
  app: string;
  version: string;
  dataset_version: string;
  llm_configured: boolean;
  llm_model: string | null;
  asr_configured: boolean;
  asr_model: string | null;
  data_dir: string;
  scripts_total: number;
  recordings_total: number;
  accepted_count: number;
  accepted_duration_sec: number;
  active_session_id: number | null;
  enums: { styles: string[]; domains: string[]; dialects: string[]; languages: string[] };
  export_sample_rate: number;
}

export interface ScriptStats {
  total: number;
  by_status: Record<string, number>;
  by_style: Record<string, number>;
  by_domain: Record<string, number>;
  by_language: Record<string, number>;
  by_dialect: Record<string, number>;
  by_length: Record<string, number>;
  accepted_recordings: number;
  accepted_duration_sec: number;
}

export interface GenerateCandidate {
  ok: boolean;
  errors: string[];
  warnings: string[];
  computed: {
    display_text: string;
    training_text: string;
    msa_equivalent: string | null;
    language: string;
    style: string;
    domain: string;
    dialect: string;
    tags: string[];
    note: string;
    length_bucket: string;
    word_count: number;
    char_count: number;
  };
}

export interface ExportBatch {
  id: number;
  name: string;
  created_at: string;
  params: Record<string, unknown>;
  stats: {
    clips: number;
    total_duration_sec: number;
    total_duration_hms: string;
    by_style: Record<string, number>;
    by_domain: Record<string, number>;
    errors: string[];
  };
  rel_path: string;
  zip_rel_path: string;
  file_count: number;
  total_duration_sec: number;
  dataset_version: string;
  status: string;
  error: string;
}
