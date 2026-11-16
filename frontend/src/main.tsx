import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./styles/global.css";

const container = document.getElementById("root");
if (!container) {
  throw new Error("root container missing");
}

const storedTheme = window.localStorage.getItem("mars.theme");
if (storedTheme === "dark" || storedTheme === "light") {
  document.documentElement.dataset.theme = storedTheme;
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
