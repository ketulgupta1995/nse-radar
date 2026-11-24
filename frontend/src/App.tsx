import { RouterProvider, createBrowserRouter } from "react-router-dom";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import { PageError } from "./pages/NotFound";
import { routes } from "./routes";

const router = createBrowserRouter([
  { path: "/login", element: <Login /> }, // outside the shell, not in the nav (SPEC §17.5)
  {
    element: <Layout />,
    children: routes.map((r) => ({ path: r.path, element: r.element, errorElement: <PageError /> })),
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
