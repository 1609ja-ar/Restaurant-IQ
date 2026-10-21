import { Link } from "react-router-dom";
import { EmptyState } from "../components/ui";

export default function NotFound() {
  return (
    <div className="card">
      <EmptyState title="Page not found" message="This page does not exist." action={<Link to="/" className="btn-primary">Back to Dashboard</Link>} />
    </div>
  );
}
