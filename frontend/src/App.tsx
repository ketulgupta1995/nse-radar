import { RouterProvider, createBrowserRouter } from "react-router-dom";
import Layout from "./components/Layout";
import { PageError } from "./pages/NotFound";
import { routes } from "./routes";

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: routes.map((r) => ({ path: r.path, element: r.element, errorElement: <PageError /> })),
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
