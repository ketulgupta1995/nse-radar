import { Link, isRouteErrorResponse, useLocation, useRouteError } from "react-router-dom";

export default function NotFound() {
  const { pathname } = useLocation();
  return (
    <div>
      <h1>Page not found</h1>
      <p className="muted">There is no page at {pathname}.</p>
      <p>
        <Link to="/">Go to the Dashboard</Link>
      </p>
    </div>
  );
}

/** Shown inside the normal layout when a page throws, so the menu stays usable. */
export function PageError() {
  const err = useRouteError();
  const detail = isRouteErrorResponse(err)
    ? `${err.status} ${err.statusText}`
    : err instanceof Error
      ? err.message
      : String(err);
  return (
    <div>
      <h1>Something went wrong on this page</h1>
      <p className="muted">{detail}</p>
      <p>
        <button type="button" onClick={() => window.location.reload()}>
          Reload the page
        </button>{" "}
        or <Link to="/">go to the Dashboard</Link>.
      </p>
    </div>
  );
}
