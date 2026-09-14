import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { ModelProvenanceControl } from "./components/ModelProvenanceModal";
import "./styles.css";

const root = document.getElementById("root");
if (!root) throw new Error("SeaScan could not find its root application element.");
createRoot(root).render(
  <StrictMode><App /><ModelProvenanceControl /></StrictMode>,
);
