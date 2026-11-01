import { Link } from "react-router-dom";
import { WorkspaceSocialAccess } from "../components/WorkspaceSocialAccess";

export function NewWorkspacePage() {
  return <main className="access-page"><section className="access-panel"><h1>Create Another Workspace</h1>
    <p>Confirm your social identity for the new workspace. Existing workspace data and staff passwords remain separate.</p>
    <WorkspaceSocialAccess register /><Link to="/portal">Back to Workspace</Link>
  </section></main>;
}
