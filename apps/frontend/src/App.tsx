import { useEffect, useRef, useState } from "react";
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

import {
  createClaimsWorkflow,
  createInvestigation,
  getClaimsWorkflow,
  resumeClaimsWorkflow,
  submitClaimsWorkflowDisposition,
} from "./api";
import type {
  ClaimsInvestigationResponse,
  ClaimsWorkflowDisposition,
  ClaimsWorkflowStatus,
  InvestigationSource,
} from "./api";
import { investigationRequestSchema } from "./validation";
import type { ClaimsInvestigationRequest } from "./validation";

interface ClaimDraft {
  claim_id: string;
  guidance_as_of: string;
  narrative: string;
}

const workflowStorageKey = "claims-workflow-id";

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

function workflowStateLabel(state: ClaimsWorkflowStatus["state"]): string {
  switch (state) {
    case "created": return "Queued for investigation";
    case "investigating": return "Investigation in progress";
    case "awaiting_human_review": return "Awaiting handler review";
    case "needs_more_information": return "More information requested";
    case "completed": return "Workflow completed";
    case "failed": return "Workflow unavailable";
    case "cancelled": return "Workflow stopped";
  }
}

function WorkflowPanel({
  workflow,
  loading,
  actionPending,
  error,
  onDisposition,
  onResume,
}: {
  workflow: ClaimsWorkflowStatus | null;
  loading: boolean;
  actionPending: boolean;
  error: string | null;
  onDisposition: (disposition: ClaimsWorkflowDisposition, reason: string) => Promise<void>;
  onResume: (reason: string, updatedNarrative: string) => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const [updatedNarrative, setUpdatedNarrative] = useState("");
  const result = workflow?.result;
  const investigation = result?.investigation;

  return (
    <section className="brief-panel workflow-panel" aria-labelledby="workflow-panel-title" aria-live="polite">
      <div className="brief-panel-head">
        <div>
          <p className="panel-kicker"><span>02</span> GOVERNED WORKFLOW</p>
          <h2 id="workflow-panel-title">Human review</h2>
        </div>
        {workflow && <span className="trace-label">ID {workflow.workflow_id.slice(0, 8)}</span>}
      </div>

      {loading && !workflow ? (
        <div className="empty-state loading-state" role="status">
          <LoaderCircle aria-hidden="true" className="spin" size={25} />
          <p>Loading persisted workflow</p>
        </div>
      ) : !workflow ? (
        <div className="empty-state">
          <div className="empty-mark"><BadgeCheck aria-hidden="true" size={23} /></div>
          <p>Waiting for a workflow</p>
          <span>Create one or load a saved workflow ID.</span>
        </div>
      ) : (
        <div className="workflow-content">
          <div className={`workflow-state is-${workflow.state}`} role="status">
            <span className="status-mark" aria-hidden="true" />
            <div>
              <p className="eyebrow">{workflow.claim_id}</p>
              <h3>{workflowStateLabel(workflow.state)}</h3>
              {workflow.error_code && <p>{workflow.error_code === "worker_interrupted"
                ? "The worker stopped during investigation. No automatic retry was made."
                : "The investigation could not be completed. No automatic retry was made."}</p>}
            </div>
          </div>

          {investigation && (
            <>
              <div className="workflow-summary">
                <p className="eyebrow">Investigation summary</p>
                {investigation.summary ? <p>{investigation.summary}</p> : <p>Evidence is insufficient.</p>}
                {investigation.findings.length > 0 && (
                  <ul>
                    {investigation.findings.map((finding, index) => (
                      <li key={`${finding.text}-${index}`}>
                        {finding.text}
                        <small>{finding.source_ids.join(", ")}</small>
                      </li>
                    ))}
                  </ul>
                )}
                {investigation.unresolved_questions.length > 0 && (
                  <div className="workflow-questions">
                    <p className="eyebrow">Unresolved questions</p>
                    <ul>{investigation.unresolved_questions.map((item) => <li key={item}>{item}</li>)}</ul>
                  </div>
                )}
                {investigation.sources.length > 0 && (
                  <div className="workflow-source-list">
                    <p className="eyebrow">Source references</p>
                    <ul>{investigation.sources.map((source) => (
                      <li key={source.source_id}>{source.source_type} <small>{source.source_id}</small></li>
                    ))}</ul>
                  </div>
                )}
              </div>
              <section className="risk-advisory" aria-label="Risk referral advisory">
                <div className="risk-advisory-heading">
                  <div><p className="eyebrow">Separate advisory</p><h3>Risk referral</h3></div>
                  <span className="advisory-tag">NOT A CLAIM DECISION</span>
                </div>
                <p>{result?.risk_assessment.status === "unavailable"
                  ? "Assessment unavailable."
                  : result?.risk_assessment.handler_triage_required
                    ? "Handler triage required."
                    : result?.risk_assessment.priority_band === "priority_review"
                      ? "Priority review."
                      : "Routine review."}</p>
              </section>
            </>
          )}

          {workflow.state === "awaiting_human_review" && (
            <section className="workflow-decision" aria-label="Human disposition">
              <label className="field">
                <span>Review reason</span>
                <textarea
                  rows={2}
                  maxLength={300}
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                />
              </label>
              <div className="workflow-actions">
                <button className="submit-button" disabled={actionPending || reason.trim().length === 0} onClick={() => void onDisposition("continue", reason)} type="button">
                  Continue workflow <ArrowRight aria-hidden="true" size={16} />
                </button>
                <button className="clear-button" disabled={actionPending || reason.trim().length === 0} onClick={() => void onDisposition("request_info", reason)} type="button">
                  Request information
                </button>
                <button className="clear-button" disabled={actionPending || reason.trim().length === 0} onClick={() => void onDisposition("stop", reason)} type="button">
                  Stop workflow
                </button>
              </div>
              <p className="workflow-boundary">Disposition changes workflow state only. It is not a claim or coverage decision.</p>
            </section>
          )}

          {workflow.state === "needs_more_information" && (
            <section className="workflow-decision" aria-label="Resume workflow">
              <label className="field">
                <span>Resume reason</span>
                <input maxLength={300} value={reason} onChange={(event) => setReason(event.target.value)} />
              </label>
              <label className="field">
                <span>Updated investigation narrative</span>
                <textarea
                  rows={3}
                  maxLength={1000}
                  value={updatedNarrative}
                  onChange={(event) => setUpdatedNarrative(event.target.value)}
                />
              </label>
              <button
                className="submit-button"
                disabled={actionPending || reason.trim().length === 0 || updatedNarrative.trim().length < 5}
                onClick={() => void onResume(reason, updatedNarrative)}
                type="button"
              >Resume investigation <RotateCcw aria-hidden="true" size={16} /></button>
            </section>
          )}

          <section className="workflow-history" aria-label="Workflow history">
            <p className="eyebrow">Transition history</p>
            <ol>
              {workflow.history.map((event) => (
                <li key={event.event_id}>
                  <span>{workflowStateLabel(event.state)}</span>
                  <small>{event.actor_id} · {event.reason}</small>
                </li>
              ))}
            </ol>
          </section>
        </div>
      )}
      {error && <p className="form-alert workflow-error" role="alert"><CircleAlert aria-hidden="true" size={16} />{error}</p>}
    </section>
  );
}

export default function App() {
  const requestSequence = useRef(0);
  const autoLoadStarted = useRef(false);
  const [view, setView] = useState<"investigation" | "workflow">("investigation");
  const [draft, setDraft] = useState<ClaimDraft>(emptyDraft);
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<ClaimField, string>>>({});
  const [result, setResult] = useState<ClaimsInvestigationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [workflow, setWorkflow] = useState<ClaimsWorkflowStatus | null>(null);
  const [storedWorkflowId] = useState(
    () => window.localStorage.getItem(workflowStorageKey) ?? "",
  );
  const [workflowIdInput, setWorkflowIdInput] = useState(
    () => window.localStorage.getItem(workflowStorageKey) ?? "",
  );
  const [workflowError, setWorkflowError] = useState<string | null>(null);
  const [workflowActionPending, setWorkflowActionPending] = useState(false);

  useEffect(() => {
    const workflowId = storedWorkflowId.trim();
    if (view !== "workflow" || workflow || !workflowId || autoLoadStarted.current) return;
    autoLoadStarted.current = true;
    let active = true;
    setWorkflowActionPending(true);
    void getClaimsWorkflow(workflowId)
      .then((loaded) => {
        if (active) {
          setWorkflow(loaded);
          setWorkflowIdInput(loaded.workflow_id);
        }
      })
      .catch((requestError: unknown) => {
        if (active) {
          setWorkflowError(
            requestError instanceof Error
              ? requestError.message
              : "The workflow service is unavailable. Try again later.",
          );
        }
      })
      .finally(() => {
        if (active) setWorkflowActionPending(false);
      });
    return () => {
      active = false;
    };
  }, [view, workflow, storedWorkflowId]);

  useEffect(() => {
    if (
      view !== "workflow"
      || !workflow
      || (workflow.state !== "created" && workflow.state !== "investigating")
    ) {
      return;
    }
    const workflowId = workflow.workflow_id;
    const poll = () => {
      void getClaimsWorkflow(workflowId)
        .then((nextWorkflow) => {
          setWorkflow((current) =>
            current?.workflow_id === workflowId && nextWorkflow.version >= current.version
              ? nextWorkflow
              : current,
          );
        })
        .catch((requestError: unknown) => {
          setWorkflowError(
            requestError instanceof Error
              ? requestError.message
              : "The workflow service is unavailable. Try again later.",
          );
        });
    };
    const interval = window.setInterval(poll, 1200);
    return () => window.clearInterval(interval);
  }, [view, workflow?.workflow_id, workflow?.state, workflow?.version]);

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
    setWorkflow(null);
    setWorkflowIdInput("");
    setWorkflowError(null);
    autoLoadStarted.current = true;
    window.localStorage.removeItem(workflowStorageKey);
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

    if (view === "workflow") {
      setLoading(true);
      setWorkflow(null);
      setWorkflowError(null);
      try {
        const created = await createClaimsWorkflow(parsed.data as ClaimsInvestigationRequest);
        const current = await getClaimsWorkflow(created.workflow_id);
        if (requestId === requestSequence.current) {
          setWorkflowIdInput(current.workflow_id);
          setWorkflow(current);
          window.localStorage.setItem(workflowStorageKey, current.workflow_id);
        }
      } catch (requestError: unknown) {
        if (requestId === requestSequence.current) {
          setWorkflowError(
            requestError instanceof Error
              ? requestError.message
              : "The workflow service is unavailable. Try again later.",
          );
        }
      } finally {
        if (requestId === requestSequence.current) setLoading(false);
      }
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

  async function loadWorkflow(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const workflowId = workflowIdInput.trim();
    setWorkflowError(null);
    setWorkflowActionPending(true);
    try {
      const loaded = await getClaimsWorkflow(workflowId);
      setWorkflow(loaded);
      setWorkflowIdInput(loaded.workflow_id);
      window.localStorage.setItem(workflowStorageKey, loaded.workflow_id);
    } catch (requestError: unknown) {
      setWorkflow(null);
      setWorkflowError(
        requestError instanceof Error
          ? requestError.message
          : "The workflow service is unavailable. Try again later.",
      );
    } finally {
      setWorkflowActionPending(false);
    }
  }

  async function submitDisposition(
    disposition: ClaimsWorkflowDisposition,
    reason: string,
  ): Promise<void> {
    if (!workflow) return;
    setWorkflowError(null);
    setWorkflowActionPending(true);
    try {
      const updated = await submitClaimsWorkflowDisposition(workflow.workflow_id, {
        disposition,
        expected_version: workflow.version,
        actor_id: "synthetic-handler-1",
        reason,
        idempotency_key: crypto.randomUUID(),
      });
      setWorkflow(updated);
    } catch (requestError: unknown) {
      setWorkflowError(
        requestError instanceof Error
          ? requestError.message
          : "The workflow service is unavailable. Try again later.",
      );
    } finally {
      setWorkflowActionPending(false);
    }
  }

  async function resumeWorkflow(reason: string, updatedNarrative: string): Promise<void> {
    if (!workflow) return;
    setWorkflowError(null);
    setWorkflowActionPending(true);
    try {
      const updated = await resumeClaimsWorkflow(workflow.workflow_id, {
        expected_version: workflow.version,
        actor_id: "synthetic-handler-1",
        reason,
        updated_narrative: updatedNarrative,
        idempotency_key: crypto.randomUUID(),
      });
      setWorkflow(updated);
    } catch (requestError: unknown) {
      setWorkflowError(
        requestError instanceof Error
          ? requestError.message
          : "The workflow service is unavailable. Try again later.",
      );
    } finally {
      setWorkflowActionPending(false);
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
          <span className="stage-tag">{view === "workflow" ? "STAGE 07" : "STAGE 06"}</span>
        </div>
      </header>

      <main className="workspace" id="top">
        <aside className="request-panel" aria-labelledby="request-title">
          <div className="panel-kicker"><span>01</span> {view === "workflow" ? "APPROVAL WORKFLOW" : "INVESTIGATION"}</div>
          <div className="request-heading">
            <h1 id="request-title">{view === "workflow" ? "Start review workflow" : "New case brief"}</h1>
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
                {loading
                  ? (view === "workflow" ? "Creating workflow" : "Preparing brief")
                  : (view === "workflow" ? "Create workflow" : "Generate brief")}
                {!loading && <ArrowRight aria-hidden="true" className="button-arrow" size={16} />}
              </button>
              <button className="clear-button" onClick={clearForm} type="button" title="Clear form">
                <RotateCcw aria-hidden="true" size={15} />
                Clear
              </button>
            </div>
          </form>

          <div className="view-switch" role="tablist" aria-label="Claims work mode">
            <button
              aria-selected={view === "investigation"}
              onClick={() => setView("investigation")}
              role="tab"
              type="button"
            >Investigation</button>
            <button
              aria-selected={view === "workflow"}
              onClick={() => setView("workflow")}
              role="tab"
              type="button"
            >Approval workflow</button>
          </div>

          {view === "workflow" && (
            <form className="workflow-load-form" onSubmit={loadWorkflow}>
              <label className="field">
                <span>Load saved workflow</span>
                <input
                  autoComplete="off"
                  value={workflowIdInput}
                  onChange={(event) => setWorkflowIdInput(event.target.value)}
                  placeholder="Workflow ID"
                />
              </label>
              <button className="clear-button" disabled={workflowActionPending || !workflowIdInput.trim()} type="submit">
                Load
              </button>
            </form>
          )}

          <div className="privacy-note">
            <ShieldCheck aria-hidden="true" size={16} />
            <span>{view === "workflow"
              ? "Synthetic only. Workflow narrative is retained with the local workflow; audit and telemetry exclude it."
              : "Synthetic only. Narrative goes to hosted models (Groq/OpenRouter); the app does not save it."}</span>
          </div>
        </aside>

        {view === "workflow" && (
          <WorkflowPanel
            workflow={workflow}
            loading={loading || workflowActionPending}
            actionPending={workflowActionPending}
            error={workflowError}
            onDisposition={submitDisposition}
            onResume={resumeWorkflow}
          />
        )}

        <section hidden={view === "workflow"} className="brief-panel" aria-labelledby="brief-panel-title" aria-live="polite">
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