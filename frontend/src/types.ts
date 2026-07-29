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
  room_tone_dbfs: number | null;
  room_tone_status: string | null;
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

export interface Insight {
  code: string;
  level: "success" | "warn" | "info" | string;
  message: string;
}

export interface Achievement {
  code: string;
  icon: string;
  title: string;
  earned: boolean;
  detail: string;
}

export interface TrendPoint {
  current: number | null;
  previous: number | null;
  delta: number | null;
  direction: "improving" | "stable" | "declining" | string;
}

export interface LeaderboardRow {
  user_id: number;
  display_name: string;
  username: string;
  dataset_id: number | null;
  dataset_name: string | null;
  assigned?: number;
  completed?: number;
  remaining?: number;
  skipped?: number;
  accepted: number;
  acceptance_rate: number;
  avg_qc_score: number | null;
  avg_time_per_script_sec: number | null;
  hours_recorded: number;
  current_streak: number;
  total_recordings: number;
}

export interface SessionSummary {
  session_id: number;
  started_at?: string;
  ended_at?: string | null;
  session_duration_sec: number;
  recorded_clips: number;
  accepted_clips: number;
  pending_clips: number;
  rejected_clips?: number;
  avg_recording_time_sec: number | null;
  avg_loudness_lufs: number | null;
  clipping_events: number;
  words_recorded: number;
  characters_recorded: number;
  estimated_speech_duration_sec: number;
  room_tone_dbfs: number | null;
  room_tone_status: string | null;
  device_info?: Record<string, unknown>;
}

export interface PerformanceDashboard {
  profile: {
    user_id: number;
    username: string;
    display_name: string;
    active: boolean;
    joined_at: string | null;
    last_login_at: string | null;
    last_active_at: string | null;
    speaker_id: number | null;
    speaker_key: string | null;
    dataset_id: number | null;
    dataset_name: string | null;
    dataset_language: string | null;
    dataset_dialect: string | null;
    status: string;
    recording_device: string | null;
    browser: string | null;
    microphone: string | null;
    device_info: Record<string, unknown>;
  };
  progress: {
    assigned: number;
    completed: number;
    remaining: number;
    skipped?: number;
    percent: number;
    estimated_remaining_sec: number | null;
  };
  quality: {
    accepted: number;
    pending: number;
    rejected: number;
    total: number;
    acceptance_rate: number;
    rerecord_rate: number;
  };
  activity: {
    today: number;
    yesterday: number;
    this_week: number;
    this_month: number;
    recording_streak: number;
    longest_streak: number;
    avg_recordings_per_day: number;
    recordings_today: number;
  };
  productivity: {
    avg_recording_duration_sec: number | null;
    avg_qc_score: number | null;
    avg_asr_confidence: number | null;
    avg_time_per_script_sec: number | null;
    fastest_recording_sec: number | null;
    longest_recording_sec: number | null;
    hours_recorded: number;
    total_speech_duration_sec: number;
  };
  audio_quality: {
    avg_loudness_lufs: number | null;
    avg_peak_dbfs: number | null;
    avg_noise_floor_dbfs: number | null;
    avg_rms_dbfs: number | null;
    clipping_count: number;
    avg_silence_pct: number | null;
    avg_snr_db: number | null;
    avg_speech_ratio: number | null;
    microphone_consistency: string;
    signal_quality: string;
  };
  insights: Insight[];
  ai_insights: string[];
  achievements: Achievement[];
  session_summary: SessionSummary | null;
  kpis: Record<string, number | null>;
  trends: Record<string, TrendPoint>;
  charts: {
    daily_recordings: { date: string; count: number }[];
    weekly_productivity: { week: string; count: number }[];
    accepted_vs_rejected: { accepted: number; rejected: number; pending: number };
    qc_score_over_time: { date: string; avg_qc_score: number }[];
    hour_heatmap: { weekday: number; hour: number; count: number }[];
    duration_histogram: { bucket: string; count: number }[];
    dataset_contribution: { domain: string; count: number }[];
    activity_calendar: { date: string; count: number }[];
  };
  filters: Record<string, unknown>;
}
