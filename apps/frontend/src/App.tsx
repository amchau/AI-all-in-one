import { useRef, useState } from "react";
import {
  ArrowRight,
  BadgeCheck,
  BookOpen,
  CircleAlert,
  FileText,
  LoaderCircle,
  RotateCcw,
  ShieldCheck,
} from "lucide-react";

import { createInvestigation } from "./api";
import type { ClaimsInvestigationResponse, InvestigationSource } from "./api";
import { investigationRequestSchema } from "./validation";
import type { ClaimsInvestigationRequest } from "./validation";

interface ClaimDraft {
  claim_id: string;
  guidance_as_of: string;
  narrative: string;
}

type ClaimField = keyof ClaimDraft;

const emptyDraft: ClaimDraft = {
  claim_id: "",
  guidance_as_of: "",
  narrative: "",
};

function SourceReferences({
  sourceIds,
  sources,
}: {
  sourceIds: string[];
  sources: InvestigationSource[];
}) {
  return (
    <ul className="source-references" aria-label="Supporting sources">
      {sourceIds.map((sourceId) => {
        const source = sources.find((item) => item.source_id === sourceId);
        return (
          <li key={sourceId}>
            <span>{source?.label ?? sourceId}</span>
          </li>
        );
      })}
    </ul>
  );
}

function RiskAdvisory({ result }: { result: ClaimsInvestigationResponse }) {
  const risk = result.risk_assessment;
  const statusLabel = risk.status === "unavailable"
    ? "Assessment unavailable"
    : risk.handler_triage_required
      ? "Handler triage required"
      : risk.priority_band === "priority_review"
        ? "Priority review"
        : "Routine review";
  const detail = risk.status === "unavailable"
    ? "The referral assessment could not be completed."
    : risk.triage_reason === "assessment_incomplete"
      ? "The available assessment is incomplete."
      : risk.triage_reason === "near_decision_threshold"
        ? "The assessment is near its review threshold."
        : "Advisory referral signal only; handler retains the claim decision.";

  return (
    <section className={`risk-advisory ${risk.status === "unavailable" ? "is-unavailable" : ""}`} aria-label="Risk referral advisory">
      <div className="risk-advisory-heading">
        <div>
          <p className="eyebrow">Separate advisory</p>
          <h3>{statusLabel}</h3>
        </div>
        <span className="advisory-tag">NOT A CLAIM DECISION</span>
      </div>
      <p>{detail}</p>
      {risk.model_version && <span className="risk-model-version">Model {risk.model_version}</span>}
    </section>
  );
}

function PolicyEvidenceStatus({ result }: { result: ClaimsInvestigationResponse }) {
  const status = result.policy_evidence_status;
  const message = status === "retrieved"
    ? "Policy evidence was retrieved and supplied to the investigation."
    : status === "insufficient_evidence"
      ? "Policy evidence search completed, but returned no matching clauses."
      : result.policy_evidence_unavailable_reason === "source_selection_failed"
        ? "Applicable policy sources could not be resolved for these dates."
        : "Policy evidence could not be retrieved.";

  return (
    <section
      className={`policy-evidence-status is-${status}`}
      aria-label="Policy evidence status"
      aria-live="polite"
    >
      <span className="status-mark" aria-hidden="true" />
      <div>
        <p className="eyebrow">Policy evidence</p>
        <p>{message}</p>
      </div>
    </section>
  );
}

function PolicyEvidence({ sources }: { sources: InvestigationSource[] }) {
  const policySources = sources.filter(
    (source) => source.source_type === "policy_evidence" && typeof source.facts.text === "string",
  );
  if (policySources.length === 0) return null;

  return (
    <section className="evidence-section" aria-label="Policy evidence">
      <div className="section-label">
        <span className="section-number">04</span>
        <h3>Policy evidence</h3>
      </div>
      <div className="evidence-list">
        {policySources.map((source) => (
          <article className="evidence-item" key={source.source_id}>
            <div className="evidence-ref">{source.source_id}</div>
            <div className="evidence-content">
              <h4>{source.label}</h4>
              <blockquote>{source.facts.text as string}</blockquote>
            </div>
            <FileText aria-hidden="true" className="evidence-icon" size={18} />
          </article>
        ))}
      </div>
    </section>
  );
}

function Brief({ result }: { result: ClaimsInvestigationResponse }) {
  const investigation = result.investigation;
  const answered = investigation.status === "answered";
  return (
    <div className="brief">
      <div className={`result-banner ${answered ? "is-answered" : "is-abstained"}`}>
        {answered ? <BadgeCheck aria-hidden="true" /> : <CircleAlert aria-hidden="true" />}
        <div>
          <p className="eyebrow">{answered ? "Evidence assembled" : "Evidence gap"}</p>
          <h3>{answered ? "Ready for handler review" : "Evidence is insufficient"}</h3>
        </div>
        <div className="result-meta">
          <span>{result.policy_id}</span>
          <span>{result.loss_date}</span>
        </div>
      </div>

      <RiskAdvisory result={result} />
      <PolicyEvidenceStatus result={result} />

      {answered && (
        <>
          <section className="summary-section" aria-labelledby="summary-title">
            <div className="section-label">
              <span className="section-number">01</span>
              <h3 id="summary-title">Brief summary</h3>
            </div>
            <p className="summary-copy">{investigation.summary}</p>
            <SourceReferences sourceIds={investigation.summary_source_ids} sources={investigation.sources} />
          </section>

          <section className="findings-section" aria-labelledby="findings-title">
            <div className="section-label">
              <span className="section-number">02</span>
              <h3 id="findings-title">Findings</h3>
            </div>
            <ol className="finding-list">
              {investigation.findings.map((finding, index) => (
                <li className="finding" key={`${finding.text}-${index}`}>
                  <span className="finding-index">{String(index + 1).padStart(2, "0")}</span>
                  <div>
                    <p>{finding.text}</p>
                    <SourceReferences sourceIds={finding.source_ids} sources={investigation.sources} />
                  </div>
                </li>
              ))}
            </ol>
          </section>
        </>
      )}

      {investigation.unresolved_questions.length > 0 && (
        <section className="questions-section" aria-labelledby="questions-title">
          <div className="section-label">
            <span className="section-number">03</span>
            <h3 id="questions-title">Unresolved questions</h3>
          </div>
          <ul>
            {investigation.unresolved_questions.map((question) => <li key={question}>{question}</li>)}
          </ul>
        </section>
      )}

      <PolicyEvidence sources={investigation.sources} />

      <footer className="brief-footer">
        <span>Evidence and referral are advisory · handler retains the claim decision</span>
        <span>{result.latency_ms.toLocaleString()} ms</span>
      </footer>
    </div>
  );
}

export default function App() {
  const requestSequence = useRef(0);
  const [draft, setDraft] = useState<ClaimDraft>(emptyDraft);
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<ClaimField, string>>>({});
  const [result, setResult] = useState<ClaimsInvestigationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function updateField(field: ClaimField, value: string): void {
    setDraft((current) => ({ ...current, [field]: value }));
    setFieldErrors((current) => ({ ...current, [field]: undefined }));
  }

  function clearForm(): void {
    requestSequence.current += 1;
    setDraft(emptyDraft);
    setFieldErrors({});
    setResult(null);
    setError(null);
    setLoading(false);
  }

  async function submit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const requestId = ++requestSequence.current;
    const payload = {
      ...draft,
      guidance_as_of: draft.guidance_as_of || undefined,
    };
    const parsed = investigationRequestSchema.safeParse(payload);
    if (!parsed.success) {
      const nextErrors: Partial<Record<ClaimField, string>> = {};
      for (const issue of parsed.error.issues) {
        const field = issue.path[0];
        if (typeof field === "string" && field in draft && !nextErrors[field as ClaimField]) {
          nextErrors[field as ClaimField] = issue.message;
        }
      }
      setFieldErrors(nextErrors);
      setResult(null);
      setError("Review the highlighted fields.");
      return;
    }

    setLoading(true);
    setResult(null);
    setError(null);
    try {
      const response = await createInvestigation(parsed.data as ClaimsInvestigationRequest);
      if (requestId === requestSequence.current) {
        setResult(response);
      }
    } catch (requestError: unknown) {
      if (requestId === requestSequence.current) {
        setError(
          requestError instanceof Error
            ? requestError.message
            : "The investigation service is unavailable. Try again later.",
        );
      }
    } finally {
      if (requestId === requestSequence.current) {
        setLoading(false);
      }
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Claims Evidence Desk home">
          <span className="brand-mark"><ShieldCheck aria-hidden="true" size={19} /></span>
          <span>Claims <strong>Evidence Desk</strong></span>
        </a>
        <div className="topbar-right">
          <span className="environment-tag"><span />LOCAL SYNTHETIC DATA</span>
          <span className="stage-tag">STAGE 06</span>
        </div>
      </header>

      <main className="workspace" id="top">
        <aside className="request-panel" aria-labelledby="request-title">
          <div className="panel-kicker"><span>01</span> INVESTIGATION</div>
          <div className="request-heading">
            <h1 id="request-title">New case brief</h1>
            <p>Claims operations <span>/</span> Evidence review</p>
          </div>

          <form className="claim-form" onSubmit={submit} noValidate>
            <div className="field-row">
              <label className="field">
                <span>Claim ID</span>
                <input
                  autoComplete="off"
                  disabled={loading}
                  maxLength={80}
                  name="claim_id"
                  value={draft.claim_id}
                  onChange={(event) => updateField("claim_id", event.target.value)}
                  aria-invalid={Boolean(fieldErrors.claim_id)}
                  aria-describedby={fieldErrors.claim_id ? "claim-id-error" : undefined}
                />
                {fieldErrors.claim_id && <small id="claim-id-error">{fieldErrors.claim_id}</small>}
              </label>
            </div>
            <div className="field-row">
              <label className="field">
                <span>Guidance date <em>OPTIONAL</em></span>
                <input
                  name="guidance_as_of"
                  disabled={loading}
                  type="date"
                  value={draft.guidance_as_of}
                  onChange={(event) => updateField("guidance_as_of", event.target.value)}
                  aria-invalid={Boolean(fieldErrors.guidance_as_of)}
                  aria-describedby={fieldErrors.guidance_as_of ? "guidance-date-error" : undefined}
                />
                {fieldErrors.guidance_as_of && <small id="guidance-date-error">{fieldErrors.guidance_as_of}</small>}
              </label>
            </div>
            <div className="field narrative-field">
              <label htmlFor="claim-narrative">Claim narrative</label>
              <textarea
                maxLength={1000}
                disabled={loading}
                id="claim-narrative"
                name="narrative"
                rows={5}
                value={draft.narrative}
                onChange={(event) => updateField("narrative", event.target.value)}
                aria-invalid={Boolean(fieldErrors.narrative)}
                aria-describedby={fieldErrors.narrative ? "narrative-error" : "narrative-count"}
              />
              {fieldErrors.narrative ? (
                <small id="narrative-error">{fieldErrors.narrative}</small>
              ) : (
                <small className="character-count" id="narrative-count">
                  {draft.narrative.length} / 1,000
                </small>
              )}
            </div>

            {error && <p className="form-alert" role="alert"><CircleAlert aria-hidden="true" size={16} />{error}</p>}

            <div className="form-actions">
              <button className="submit-button" disabled={loading} type="submit">
                {loading ? <LoaderCircle aria-hidden="true" className="spin" size={17} /> : <BookOpen aria-hidden="true" size={17} />}
                {loading ? "Preparing brief" : "Generate brief"}
                {!loading && <ArrowRight aria-hidden="true" className="button-arrow" size={16} />}
              </button>
              <button className="clear-button" onClick={clearForm} type="button" title="Clear form">
                <RotateCcw aria-hidden="true" size={15} />
                Clear
              </button>
            </div>
          </form>

          <div className="privacy-note">
            <ShieldCheck aria-hidden="true" size={16} />
            <span>Synthetic only. Narrative goes to hosted models (Groq/OpenRouter); the app does not save it.</span>
          </div>
        </aside>

        <section className="brief-panel" aria-labelledby="brief-panel-title" aria-live="polite">
          <div className="brief-panel-head">
            <div>
              <p className="panel-kicker"><span>02</span> EVIDENCE REVIEW</p>
              <h2 id="brief-panel-title">Investigation brief</h2>
            </div>
            {result && <span className="trace-label">TRACE {result.trace_id?.slice(0, 8) ?? "UNAVAILABLE"}</span>}
          </div>

          {loading ? (
            <div className="empty-state loading-state" role="status">
              <LoaderCircle aria-hidden="true" className="spin" size={25} />
              <p>Resolving applicable wording and evidence</p>
              <span>Usually takes a few seconds</span>
            </div>
          ) : error ? (
            <div className="empty-state error-state" role="status">
              <CircleAlert aria-hidden="true" size={25} />
              <p>Brief not available</p>
              <span>{error}</span>
            </div>
          ) : result ? (
            <Brief result={result} />
          ) : (
            <div className="empty-state">
              <div className="empty-mark"><BookOpen aria-hidden="true" size={23} /></div>
              <p>Waiting for a claim</p>
              <span>No evidence brief in this session.</span>
            </div>
          )}
        </section>
      </main>

      <footer className="page-footer">
        <span><ShieldCheck aria-hidden="true" size={13} /> HANDLER REVIEW REQUIRED</span>
        <span>CLAIMS EVIDENCE DESK <b>·</b> LOCAL LAB</span>
      </footer>
    </div>
  );
}