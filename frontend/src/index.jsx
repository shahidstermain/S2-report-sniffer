import React from "react";
import ReactDOM from "react-dom/client";
import { initHostContext } from "@/lib/hostContext";
import "@/index.css";
import App from "@/App";

initHostContext();

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
