import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { api, API_RESULT_EVENT, type ApiResult } from "../api";
import { nextSteps } from "../features/workflowGuide";
import { useNotifications } from "./Notifications";

export function WorkflowGuide() {
  const notifications = useNotifications();
  const navigate = useNavigate();
  const enabled = useRef(true);

  useEffect(() => {
    let active = true;
    const load = () => { void api.company().then(company => { if (active) enabled.current = company.workflow_guidance_enabled !== false; }).catch(() => {}); };
    load();
    window.addEventListener("company-updated", load);
    return () => { active = false; window.removeEventListener("company-updated", load); };
  }, []);

  useEffect(() => {
    if (!notifications) return;
    const onResult = (event: Event) => {
      if (!enabled.current) return;
      const guidance = nextSteps((event as CustomEvent<ApiResult>).detail);
      if (!guidance) return;
      const go = (path: string) => { notifications.remove("workflow-guide"); navigate(path); };
      notifications.show({
        id: "workflow-guide",
        tone: "workflow",
        content: <div className="workflow-notice">
          <p>{guidance.title}. Suggested next:</p>
          <ol>{guidance.steps.map(step => <li key={step.label}>{step.path ? <button type="button" onClick={() => go(step.path!)}>{step.label}</button> : step.label}</li>)}</ol>
          {guidance.note && <small>{guidance.note}</small>}
          <small>Turn these off in Company Setup → Operations Portal.</small>
        </div>,
      });
    };
    window.addEventListener(API_RESULT_EVENT, onResult);
    return () => window.removeEventListener(API_RESULT_EVENT, onResult);
  }, [notifications, navigate]);

  return null;
}
