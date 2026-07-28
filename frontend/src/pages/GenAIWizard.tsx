import { useEffect, useMemo, useRef, useState } from "react";
import { get, post, streamPost } from "../api";
import { Chip, Modal, MultiSelect, Spinner } from "../components/widgets";
import { AppStatus, Dataset, GenerateCandidate } from "../types";

const DEFAULT_INSTRUCTIONS = `• Record in a quiet room with no echo, fans, or background voices.
• Keep a steady hand-width distance from the microphone.
• Read the sentence exactly as shown, in its natural language and dialect.
• Speak at a calm, even pace — don't rush the ends of sentences.
• If you stumble or mispronounce, just press Restart and read it again.
• Leave a short beat of silence before you start and after you finish.`;

const LANGUAGE_OPTIONS = [
  { value: "ar-AE", label: "Arabic", help: "Generate fully Arabic sentences only." },
  { value: "en-US", label: "English", help: "Generate fully English sentences only." },
  { value: "mixed", label: "Mixed", help: "Generate natural Arabic + English code-switched sentences." },
] as const;

const DIALECT_OPTIONS: Record<string, Array<{ value: string; label: string; help: string }>> = {
  "ar-AE": [
    { value: "emirati", label: "Emirati Arabic", help: "Natural UAE spoken Arabic." },
    { value: "msa", label: "Modern Standard Arabic", help: "Formal Arabic without dialectal wording." },
  ],
  "en-US": [
    { value: "english", label: "English", help: "Native English wording and phrasing." },
  ],
  mixed: [
    { value: "mixed", label: "Mixed Arabic + English", help: "Natural code-switching when it sounds realistic." },
  ],
};

function languageLabel(value: string): string {
  return LANGUAGE_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

function dialectOptionsFor(language: string) {
  return DIALECT_OPTIONS[language] ?? DIALECT_OPTIONS["ar-AE"];
}

function fmtHours(sec: number): string {
  const h = sec / 3600;
  if (h >= 1) return `${h.toFixed(1)} h`;
  return `${Math.round(sec / 60)} min`;
}

export default function GenAIWizard({
  status,
  dataset,
  onClose,
  onCreated,
}: {
  status: AppStatus | null;
  dataset?: Dataset | null;
  onClose: () => void;
  onCreated: (id: number) => void;
}) {
  const [step, setStep] = useState<"plan" | "review">("plan");
  const [plan, setPlan] = useState({
    name: dataset?.name ?? "",
    description: dataset?.description ?? "",
    dialect: dataset?.dialect ?? "emirati",
    languages: [dataset?.languages?.[0] ?? dataset?.language ?? "ar-AE"] as string[],
    text_policy: dataset?.text_policy ?? "",
    instructions: dataset?.instructions ?? DEFAULT_INSTRUCTIONS,
    target_sample_count: dataset?.target_sample_count || 200,
    avg_duration_sec: dataset?.target_avg_duration_sec || 6,
    styles: ["neutral"] as string[],
    domains: ["customer_support"] as string[],
    topics: "",
    brand_terms: "e&, du, eLife, 5G",
    generate_count: 30,
  });
  const [candidates, setCandidates] = useState<GenerateCandidate[] | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [generated, setGenerated] = useState(0);
  const [error, setError] = useState("");
  const [globalPolicy, setGlobalPolicy] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);
  useEffect(() => {
    get<{ text: string }>("/api/policy")
      .then((response) => setGlobalPolicy(response.text))
      .catch((e) => setError(e.message));
  }, []);

  const selectedLanguage = plan.languages[0] ?? "ar-AE";
  const dialectOptions = dialectOptionsFor(selectedLanguage);

  useEffect(() => {
    if (!dialectOptions.some((option) => option.value === plan.dialect)) {
      setPlan((current) => ({ ...current, dialect: dialectOptions[0].value }));
    }
  }, [dialectOptions, plan.dialect]);

  const projected = useMemo(
    () => plan.target_sample_count * plan.avg_duration_sec,
    [plan.target_sample_count, plan.avg_duration_sec]
  );
  const batchWords = Math.max(2, Math.round(plan.avg_duration_sec * 2.3));
  const llmReady = !!status?.llm_configured;
  const planValid =
    (!!dataset || !!plan.name.trim()) &&
    plan.target_sample_count > 0 &&
    plan.avg_duration_sec > 0 &&
    plan.generate_count > 0 &&
    plan.styles.length > 0 &&
    plan.languages.length > 0;

  const set = (patch: Partial<typeof plan>) => setPlan((p) => ({ ...p, ...patch }));

  const generate = async () => {
    if (!dataset && !plan.name.trim()) {
      setError("Give the dataset a name first.");
      return;
    }
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setBusy(true);
    setError("");
    setCandidates([]);
    setSelected(new Set());
    setGenerated(0);
    setStep("review");
    try {
      await streamPost<{
        type: "start" | "heartbeat" | "candidate" | "complete" | "batch_error" | "error";
        model?: string;
        candidate?: GenerateCandidate;
        index?: number;
        message?: string;
        failed_batches?: number;
        count?: number;
        requested?: number;
      }>(
        "/api/scripts/generate/stream",
        {
          count: plan.generate_count,
          styles: plan.styles,
          domains: plan.domains,
          languages: plan.languages,
          dialect: plan.dialect,
          policy_text: plan.text_policy,
          topics: plan.topics,
          brand_terms: plan.brand_terms,
          avg_duration_sec: plan.avg_duration_sec,
          batch_name: `${plan.name} · AI batch`,
        },
        (event) => {
          if (event.model) setModel(event.model);
          if (event.type === "candidate" && event.candidate) {
            setCandidates((current) => [...(current ?? []), event.candidate!]);
            setGenerated((current) => current + 1);
            if (event.candidate.ok) {
              setSelected((current) => {
                const next = new Set(current);
                next.add(event.index ?? current.size);
                return next;
              });
            }
          } else if (event.type === "batch_error") {
            setError((current) =>
              current
                ? `${current} One generation batch also failed: ${event.message}`
                : `One generation batch failed; the other batches are still running. ${event.message}`
            );
          } else if (event.type === "error") {
            setError(event.message || "Generation failed.");
          } else if (
            event.type === "complete" &&
            event.count !== undefined &&
            event.requested !== undefined &&
            event.count < event.requested
          ) {
            setError(
              `The model returned ${event.count} of ${event.requested} requested records. You can review these or regenerate.`
            );
          }
        },
        controller.signal
      );
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError((e as Error).message);
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setBusy(false);
    }
  };

  const saveCandidates = async () => {
    if (!candidates) return;
    setSaving(true);
    setError("");
    try {
      const ds = dataset ?? await post<Dataset>("/api/datasets", {
          name: plan.name,
          description: plan.description,
          instructions: plan.instructions,
          dialect: plan.dialect,
          languages: plan.languages,
          text_policy: plan.text_policy,
          target_sample_count: plan.target_sample_count,
          target_avg_duration_sec: plan.avg_duration_sec,
        });
      const items = [...selected].map((i) => {
        const c = candidates[i].computed;
        return {
          display_text: c.display_text,
          training_text: c.training_text,
          msa_equivalent: c.msa_equivalent,
          language: c.language,
          dialect: c.dialect,
          style: c.style,
          domain: c.domain,
          tags: c.tags,
          notes: c.note,
        };
      });
      await post(`/api/datasets/${ds.id}/import`, {
        items,
        source: "llm",
        generation_batch: `${plan.name} · AI batch`,
        generation_model: model,
      });
      onCreated(ds.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={dataset ? `Add AI scripts to ${dataset.name}` : "Create dataset with GenAI"} onClose={onClose} wide>
      {!llmReady && (
        <div className="banner warn">
          The LLM endpoint isn't configured. Set <code>AZURE_OPENAI_ENDPOINT</code>,{" "}
          <code>AZURE_OPENAI_API_KEY</code> and <code>LLM_DEPLOYMENT</code> in <code>.env</code>.
        </div>
      )}

      {step === "plan" && (
        <>
          {dataset && (
            <div className="banner info">
              New scripts will be reviewed first, then appended to <b>{dataset.name}</b>. Existing
              scripts and recordings will not be changed.
            </div>
          )}
          <div className="wizard-layout">
            <section className="wizard-section">
              <div className="wizard-section-head">
                <h4>Dataset Information</h4>
                <p className="muted small">Choose what type of dataset you want to create.</p>
              </div>
              <div className="form-grid">
                {!dataset && (
                  <label className="span2">
                    Dataset name
                    <input
                      className="input"
                      placeholder="Emirati Customer Support v1"
                      value={plan.name}
                      maxLength={200}
                      required
                      onChange={(e) => set({ name: e.target.value })}
                    />
                  </label>
                )}
                <div className="span2">
                  <div className="field-label">
                    Language
                    <div className="selection-grid">
                      {LANGUAGE_OPTIONS.map((option) => (
                        <button
                          key={option.value}
                          type="button"
                          className={`selection-card ${selectedLanguage === option.value ? "selected" : ""}`}
                          onClick={() => set({ languages: [option.value] })}
                        >
                          <span className="selection-title">{option.label}</span>
                          <span className="selection-help">{option.help}</span>
                        </button>
                      ))}
                    </div>
                    <span className="muted small">
                      {selectedLanguage === "ar-AE"
                        ? "Arabic datasets stay fully in Arabic. Any sentence with English words belongs in Mixed instead."
                        : selectedLanguage === "mixed"
                          ? "Use Mixed when you want intentional Arabic-English code-switching."
                          : "English datasets stay fully in English."}
                    </span>
                  </div>
                </div>
                <div className="span2">
                  <div className="field-label">
                    Dialect / Variant
                    <div className="selection-grid">
                      {dialectOptions.map((option) => (
                        <button
                          key={option.value}
                          type="button"
                          className={`selection-card ${plan.dialect === option.value ? "selected" : ""}`}
                          onClick={() => set({ dialect: option.value })}
                        >
                          <span className="selection-title">{option.label}</span>
                          <span className="selection-help">{option.help}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
                {!dataset && (
                  <label className="span2">
                    Description (optional)
                    <input className="input" placeholder="Goal of this dataset" value={plan.description} onChange={(e) => set({ description: e.target.value })} />
                  </label>
                )}
              </div>
            </section>

            <section className="wizard-section">
              <div className="wizard-section-head">
                <h4>Generation Settings</h4>
                <p className="muted small">Set the target volume and the first review batch.</p>
              </div>
              <div className="form-grid">
                {!dataset && (
                  <label>
                    Target samples
                    <input type="number" min={1} className="input" value={plan.target_sample_count} onChange={(e) => set({ target_sample_count: Math.max(1, Number(e.target.value) || 1) })} />
                  </label>
                )}
                <label>
                  Average duration per clip (sec)
                  <input type="number" min={1} max={60} className="input" value={plan.avg_duration_sec} onChange={(e) => set({ avg_duration_sec: Math.min(60, Math.max(1, Number(e.target.value) || 1)) })} />
                </label>
                <label>
                  Generate now (first batch)
                  <input type="number" min={1} max={100} className="input" value={plan.generate_count} onChange={(e) => set({ generate_count: Math.min(100, Math.max(1, Number(e.target.value) || 1)) })} />
                </label>
              </div>
            </section>
          </div>

          {!dataset && <div className="plan-summary">
            <div className="plan-metric">
              <div className="plan-value">{plan.target_sample_count.toLocaleString()}</div>
              <div className="muted small">target samples</div>
            </div>
            <div className="plan-x">×</div>
            <div className="plan-metric">
              <div className="plan-value">{plan.avg_duration_sec}s</div>
              <div className="muted small">avg / clip</div>
            </div>
            <div className="plan-x">=</div>
            <div className="plan-metric accent">
              <div className="plan-value">{fmtHours(projected)}</div>
              <div className="muted small">projected audio</div>
            </div>
            <div className="plan-note muted small">
              ≈ {batchWords} words per sentence at a natural pace
            </div>
          </div>}

          <div className="wizard-layout">
            <section className="wizard-section">
              <div className="wizard-section-head">
                <h4>AI Configuration</h4>
                <p className="muted small">Guide the generator without overloading the workflow.</p>
              </div>
              <div className="form-grid">
                <label className="span2">
                  Styles
                  <MultiSelect options={["neutral"]} value={plan.styles} onChange={(v) => set({ styles: v })} />
                  <span className="muted small">Neutral is the only style enabled for now.</span>
                </label>
                <label className="span2">
                  Brand / Product Terms
                  <input className="input" value={plan.brand_terms} onChange={(e) => set({ brand_terms: e.target.value })} />
                </label>
                <label className="span2">
                  Topic Seeds (optional)
                  <textarea className="input" dir="auto" rows={2} placeholder="Package activation, billing question, network coverage, roaming before travel…" value={plan.topics} onChange={(e) => set({ topics: e.target.value })} />
                </label>
              </div>
            </section>

            {!dataset && (
              <section className="wizard-section">
                <div className="wizard-section-head">
                  <h4>Recording</h4>
                  <p className="muted small">Instructions shown to recorders during collection.</p>
                </div>
                <div className="form-grid">
                  <label className="span2">
                    Recording instructions
                    <textarea className="input" rows={5} value={plan.instructions} onChange={(e) => set({ instructions: e.target.value })} />
                  </label>
                </div>
              </section>
            )}

            <section className="wizard-section">
              <div className="wizard-section-head">
                <h4>Advanced</h4>
                <p className="muted small">Optional policy controls for dataset-specific rules.</p>
              </div>
              <div className="form-grid">
                <div className="span2">
                  <details className="policy-preview">
                    <summary>View global text policy applied to this generation</summary>
                    <pre className="policy-text">{globalPolicy || "Loading…"}</pre>
                  </details>
                </div>
                {!dataset ? (
                  <label className="span2">
                    Dataset-specific policy
                    <textarea
                      className="input"
                      rows={4}
                      value={plan.text_policy}
                      placeholder="Add terminology, pronunciation, casing, or prohibited-content rules."
                      onChange={(event) => set({ text_policy: event.target.value })}
                    />
                  </label>
                ) : plan.text_policy ? (
                  <div className="span2 banner info small">
                    <b>Dataset policy additions:</b>
                    <pre className="guide-text">{plan.text_policy}</pre>
                  </div>
                ) : null}
              </div>
            </section>
          </div>

          {error && <div className="banner error">{error}</div>}
          <div className="row gap modal-actions">
            <button className="btn record" onClick={generate} disabled={busy || !llmReady || !planValid}>
              {busy ? <Spinner label="Generating with GPT-5.6-sol…" /> : `✨ Generate ${plan.generate_count} with GenAI`}
            </button>
            <button className="btn ghost" onClick={onClose}>Cancel</button>
            <span className="muted small">You'll review every sentence before anything is saved.</span>
          </div>
        </>
      )}

      {step === "review" && candidates && (
        <>
          <div className="row spread">
            <span className="muted small">
              {busy
                ? `Generating live: ${generated} of ${plan.generate_count} received`
                : `${selected.size} of ${candidates.length} selected`}
              {model && ` · generated by ${model}`}
              {!busy && " · uncheck any you don't want"}
            </span>
            <button className="link-btn" onClick={() => setStep("plan")} disabled={busy}>← back to plan</button>
          </div>
          {busy && (
            <div className="generation-live">
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${Math.min(100, (generated / plan.generate_count) * 100)}%` }} />
              </div>
              <div className="row spread small muted">
                <Spinner label={generated ? "More records are arriving…" : "The model is preparing the first records…"} />
                <button className="link-btn" onClick={() => abortRef.current?.abort()}>Stop</button>
              </div>
            </div>
          )}
          <div className="candidate-list">
            {candidates.map((c, i) => (
              <div key={i} className={`candidate ${c.ok ? "" : "error"}`}>
                <label className="row gap">
                  <input
                    type="checkbox"
                    disabled={!c.ok}
                    checked={selected.has(i)}
                    onChange={(e) => {
                      const next = new Set(selected);
                      if (e.target.checked) next.add(i);
                      else next.delete(i);
                      setSelected(next);
                    }}
                  />
                  <div className="grow">
                    <div className="arabic" dir="auto">{c.computed.display_text}</div>
                    {c.computed.training_text !== c.computed.display_text && (
                      <div className="arabic muted small" dir="auto">{c.computed.training_text}</div>
                    )}
                    <div className="row gap wrap" style={{ marginTop: 4 }}>
                      <Chip tone="accent">{languageLabel(c.computed.language)}</Chip>
                      <Chip>{c.computed.dialect}</Chip>
                      <Chip tone="accent">{c.computed.style}</Chip>
                      <Chip>{c.computed.domain}</Chip>
                      <Chip>{c.computed.length_bucket}</Chip>
                      {c.errors.map((e2, n) => (
                        <Chip key={`e${n}`} tone="bad">{e2}</Chip>
                      ))}
                      {c.warnings.map((w, n) => (
                        <Chip key={`w${n}`} tone="warn">{w}</Chip>
                      ))}
                    </div>
                  </div>
                </label>
              </div>
            ))}
          </div>
          {error && <div className="banner error">{error}</div>}
          <div className="row gap modal-actions">
            <button className="btn accept" onClick={saveCandidates} disabled={busy || saving || selected.size === 0}>
              {saving
                ? <Spinner label={dataset ? "Adding scripts…" : "Creating dataset…"} />
                : dataset
                  ? `Add ${selected.size} scripts to dataset`
                  : `Create dataset with ${selected.size} scripts`}
            </button>
            <button className="btn ghost" onClick={generate} disabled={busy || saving}>↺ Regenerate</button>
          </div>
        </>
      )}
    </Modal>
  );
}
