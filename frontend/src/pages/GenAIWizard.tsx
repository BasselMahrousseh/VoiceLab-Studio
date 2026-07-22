import { useMemo, useState } from "react";
import { post } from "../api";
import { Chip, Modal, MultiSelect, Spinner } from "../components/widgets";
import { AppStatus, Dataset, GenerateCandidate } from "../types";

const DEFAULT_INSTRUCTIONS = `• Record in a quiet room with no echo, fans, or background voices.
• Keep a steady hand-width distance from the microphone.
• Read the sentence exactly as shown, in natural Emirati dialect.
• Speak at a calm, even pace — don't rush the ends of sentences.
• If you stumble or mispronounce, just press Restart and read it again.
• Leave a short beat of silence before you start and after you finish.`;

const COVERAGE = ["numbers", "dates_times", "prices", "id_codes", "code_switch", "brands"];

function fmtHours(sec: number): string {
  const h = sec / 3600;
  if (h >= 1) return `${h.toFixed(1)} h`;
  return `${Math.round(sec / 60)} min`;
}

export default function GenAIWizard({
  status,
  onClose,
  onCreated,
}: {
  status: AppStatus | null;
  onClose: () => void;
  onCreated: (id: number) => void;
}) {
  const [step, setStep] = useState<"plan" | "review">("plan");
  const [plan, setPlan] = useState({
    name: "",
    description: "",
    dialect: "emirati",
    instructions: DEFAULT_INSTRUCTIONS,
    target_sample_count: 200,
    avg_duration_sec: 6,
    styles: ["neutral", "friendly"] as string[],
    domains: ["customer_support"] as string[],
    coverage: [] as string[],
    topics: "",
    brand_terms: "e&, du, eLife, 5G",
    generate_count: 30,
  });
  const [candidates, setCandidates] = useState<GenerateCandidate[] | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const projected = useMemo(
    () => plan.target_sample_count * plan.avg_duration_sec,
    [plan.target_sample_count, plan.avg_duration_sec]
  );
  const batchWords = Math.max(2, Math.round(plan.avg_duration_sec * 2.3));
  const llmReady = !!status?.llm_configured;

  const set = (patch: Partial<typeof plan>) => setPlan((p) => ({ ...p, ...patch }));

  const generate = async () => {
    if (!plan.name.trim()) {
      setError("Give the dataset a name first.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const resp = await post<{ model: string; candidates: GenerateCandidate[] }>(
        "/api/scripts/generate",
        {
          count: plan.generate_count,
          styles: plan.styles,
          domains: plan.domains,
          dialect: plan.dialect,
          coverage: plan.coverage,
          topics: plan.topics,
          brand_terms: plan.brand_terms,
          avg_duration_sec: plan.avg_duration_sec,
          batch_name: `${plan.name} · batch 1`,
        }
      );
      setCandidates(resp.candidates);
      setModel(resp.model);
      setSelected(new Set(resp.candidates.map((c, i) => (c.ok ? i : -1)).filter((i) => i >= 0)));
      setStep("review");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const createDataset = async () => {
    if (!candidates) return;
    setBusy(true);
    setError("");
    try {
      const ds = await post<Dataset>("/api/datasets", {
        name: plan.name,
        description: plan.description,
        instructions: plan.instructions,
        dialect: plan.dialect,
        target_sample_count: plan.target_sample_count,
        target_avg_duration_sec: plan.avg_duration_sec,
      });
      const items = [...selected].map((i) => {
        const c = candidates[i].computed;
        return {
          display_text: c.display_text,
          training_text: c.training_text,
          msa_equivalent: c.msa_equivalent,
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
        generation_batch: `${plan.name} · batch 1`,
        generation_model: model,
      });
      onCreated(ds.id);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <Modal title="Create dataset with GenAI" onClose={onClose} wide>
      {!llmReady && (
        <div className="banner warn">
          The LLM endpoint isn't configured. Set <code>AZURE_OPENAI_ENDPOINT</code>,{" "}
          <code>AZURE_OPENAI_API_KEY</code> and <code>LLM_DEPLOYMENT</code> in <code>.env</code>.
        </div>
      )}

      {step === "plan" && (
        <>
          <div className="form-grid">
            <label>
              Dataset name
              <input className="input" placeholder="Emirati Customer Support v1" value={plan.name} onChange={(e) => set({ name: e.target.value })} />
            </label>
            <label>
              Dialect
              <select className="input" value={plan.dialect} onChange={(e) => set({ dialect: e.target.value })}>
                {(status?.enums.dialects ?? ["emirati", "msa", "mixed"]).map((d) => (
                  <option key={d}>{d}</option>
                ))}
              </select>
            </label>
            <label className="span2">
              Description (optional)
              <input className="input" placeholder="Goal of this dataset" value={plan.description} onChange={(e) => set({ description: e.target.value })} />
            </label>

            <label>
              Target samples
              <input type="number" min={1} className="input" value={plan.target_sample_count} onChange={(e) => set({ target_sample_count: Number(e.target.value) })} />
            </label>
            <label>
              Avg. duration / clip (sec)
              <input type="number" min={1} max={60} className="input" value={plan.avg_duration_sec} onChange={(e) => set({ avg_duration_sec: Number(e.target.value) })} />
            </label>
          </div>

          <div className="plan-summary">
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
          </div>

          <div className="form-grid">
            <label className="span2">
              Styles (voice tone — the model distributes across these)
              <MultiSelect options={status?.enums.styles ?? []} value={plan.styles} onChange={(v) => set({ styles: v })} />
            </label>
            <label className="span2">
              Domains (topics / context)
              <MultiSelect options={status?.enums.domains ?? []} value={plan.domains} onChange={(v) => set({ domains: v })} />
            </label>
            <label className="span2">
              Special coverage (make sure these appear)
              <MultiSelect options={COVERAGE} value={plan.coverage} onChange={(v) => set({ coverage: v })} />
            </label>
            <label className="span2">
              Brand / product terms allowed
              <input className="input" value={plan.brand_terms} onChange={(e) => set({ brand_terms: e.target.value })} />
            </label>
            <label className="span2">
              Topic seeds (optional)
              <textarea className="input arabic" dir="rtl" rows={2} placeholder="تفعيل باقة، شكوى فاتورة، استفسار عن التغطية…" value={plan.topics} onChange={(e) => set({ topics: e.target.value })} />
            </label>
            <label className="span2">
              Recording instructions (shown to recorders)
              <textarea className="input" rows={5} value={plan.instructions} onChange={(e) => set({ instructions: e.target.value })} />
            </label>
            <label>
              Generate now (first batch)
              <input type="number" min={1} max={100} className="input" value={plan.generate_count} onChange={(e) => set({ generate_count: Math.min(100, Number(e.target.value)) })} />
            </label>
          </div>

          {error && <div className="banner error">{error}</div>}
          <div className="row gap" style={{ marginTop: 12 }}>
            <button className="btn record" onClick={generate} disabled={busy || !llmReady}>
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
              {selected.size} of {candidates.length} selected · generated by {model} · uncheck any you don't want
            </span>
            <button className="link-btn" onClick={() => setStep("plan")}>← back to plan</button>
          </div>
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
                    <div className="arabic" dir="rtl">{c.computed.display_text}</div>
                    {c.computed.training_text !== c.computed.display_text && (
                      <div className="arabic muted small" dir="rtl">{c.computed.training_text}</div>
                    )}
                    <div className="row gap wrap" style={{ marginTop: 4 }}>
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
          <div className="row gap" style={{ marginTop: 12 }}>
            <button className="btn accept" onClick={createDataset} disabled={busy || selected.size === 0}>
              {busy ? <Spinner label="Creating dataset…" /> : `Create dataset with ${selected.size} scripts`}
            </button>
            <button className="btn ghost" onClick={generate} disabled={busy}>↺ Regenerate</button>
          </div>
        </>
      )}
    </Modal>
  );
}
