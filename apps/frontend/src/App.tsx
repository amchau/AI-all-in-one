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
import type { ClaimsInvestigationResponse } from "./api";
import { investigationRequestSchema } from "./validation";
import type { ClaimsInvestigationRequest } from "./validation";

interface ClaimDraft {
  claim_id: string;
  policy_id: string;
  loss_date: string;
  guidance_as_of: string;
  narrative: string;
}

type ClaimField = keyof ClaimDraft;

const emptyDraft: ClaimDraft = {
  claim_id: "",
  policy_id: "",
  loss_date: "",
  guidance_as_of: "",
  narrative: "",
};

function evidenceAnchor(chunkId: string): string {
  return `evidence-${chunkId.replace(/[^A-Za-z0-9_-]/g, "-")}`;
}

function CitationLinks({
  citations,
}: {
  citations: ClaimsInvestigationResponse["summary_citations"];
}) {
  return (
    <span className="citation-links">
      {citations.map((citation) => (
        <a
          className="citation-link"
          href={`#${evidenceAnchor(citation.chunk_id)}`}
          key={`${citation.ref}-${citation.chunk_id}`}
          aria-label={`Open cited evidence ${citation.ref}`}
        >
          {citation.ref}<ArrowRight aria-hidden="true" size={12} />
        </a>
      ))}
    </span>
  );
}

function Brief({ result }: { result: ClaimsInvestigationResponse }) {
  const answered = result.status === "answered";
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

      {answered && (
        <>
          <section className="summary-section" aria-labelledby="summary-title">
            <div className="section-label">
              <span className="section-number">01</span>
              <h3 id="summary-title">Brief summary</h3>
            </div>
            <p className="summary-copy">{result.summary}</p>
            <CitationLinks citations={result.summary_citations} />
          </section>

          <section className="findings-section" aria-labelledby="findings-title">
            <div className="section-label">
              <span className="section-number">02</span>
              <h3 id="findings-title">Findings</h3>
            </div>
            <ol className="finding-list">
              {result.findings.map((finding, index) => (
                <li className="finding" key={`${finding.text}-${index}`}>
                  <span className="finding-index">{String(index + 1).padStart(2, "0")}</span>
                  <div>
                    <p>{finding.text}</p>
                    <CitationLinks citations={finding.citations} />
                  </div>
                </li>
              ))}
            </ol>
          </section>
        </>
      )}

      {result.unresolved_questions.length > 0 && (
        <section className="questions-section" aria-labelledby="questions-title">
          <div className="section-label">
            <span className="section-number">{answered ? "03" : "01"}</span>
            <h3 id="questions-title">Unresolved questions</h3>
          </div>
          <ul>
            {result.unresolved_questions.map((question) => <li key={question}>{question}</li>)}
          </ul>
        </section>
      )}

      {result.evidence.length > 0 && (
        <section className="evidence-section" aria-label="Cited evidence">
          <div className="section-label">
            <span className="section-number">04</span>
            <h3>Source evidence</h3>
          </div>
          <div className="evidence-list">
            {result.evidence.map((item) => (
              <article
                className="evidence-item"
                id={evidenceAnchor(item.chunk_id)}
                key={item.chunk_id}
              >
                <div className="evidence-ref">{item.ref}</div>
                <div className="evidence-content">
                  <h4>{item.title}</h4>
                  <p className="evidence-location">
                    {item.section ? `Section ${item.section}` : "Policy wording"}
                    {item.clause ? ` · Clause ${item.clause}` : ""}
                    {` · Page ${item.page}`}
                  </p>
                  <blockquote>{item.text}</blockquote>
                </div>
                <FileText aria-hidden="true" className="evidence-icon" size={18} />
              </article>
            ))}
          </div>
        </section>
      )}

      <footer className="brief-footer">
        <span>Evidence only · handler retains the claim decision</span>
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
          <span className="stage-tag">STAGE 03</span>
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
              <label className="field">
                <span>Policy ID</span>
                <input
                  autoComplete="off"
                  disabled={loading}
                  maxLength={80}
                  name="policy_id"
                  value={draft.policy_id}
                  onChange={(event) => updateField("policy_id", event.target.value)}
                  aria-invalid={Boolean(fieldErrors.policy_id)}
                  aria-describedby={fieldErrors.policy_id ? "policy-id-error" : undefined}
                />
                {fieldErrors.policy_id && <small id="policy-id-error">{fieldErrors.policy_id}</small>}
              </label>
            </div>
            <div className="field-row">
              <label className="field">
                <span>Loss date</span>
                <input
                  name="loss_date"
                  disabled={loading}
                  type="date"
                  value={draft.loss_date}
                  onChange={(event) => updateField("loss_date", event.target.value)}
                  aria-invalid={Boolean(fieldErrors.loss_date)}
                  aria-describedby={fieldErrors.loss_date ? "loss-date-error" : undefined}
                />
                {fieldErrors.loss_date && <small id="loss-date-error">{fieldErrors.loss_date}</small>}
              </label>
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