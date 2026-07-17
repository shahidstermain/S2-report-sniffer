import { useEffect } from "react";
import { normalizeTerminology } from "@/lib/terminology";

const NORMALIZED_ATTRIBUTES = ["aria-label", "placeholder", "title"];
const SKIP_SELECTOR = [
  "code",
  "pre",
  "script",
  "style",
  "textarea",
  "[contenteditable='true']",
  "[data-preserve-terminology='true']",
].join(",");

function shouldSkip(node) {
  const element = node?.nodeType === Node.ELEMENT_NODE
    ? node
    : node?.parentElement;
  return Boolean(element?.closest?.(SKIP_SELECTOR));
}

function normalizeTextNode(node) {
  if (!node?.nodeValue || shouldSkip(node)) return;
  const next = normalizeTerminology(node.nodeValue);
  if (next !== node.nodeValue) node.nodeValue = next;
}

function normalizeAttributes(element) {
  if (!(element instanceof Element) || shouldSkip(element)) return;
  for (const attribute of NORMALIZED_ATTRIBUTES) {
    const value = element.getAttribute(attribute);
    if (!value) continue;
    const next = normalizeTerminology(value);
    if (next !== value) element.setAttribute(attribute, next);
  }
}

function normalizeSubtree(root) {
  if (!root || shouldSkip(root)) return;

  if (root.nodeType === Node.TEXT_NODE) {
    normalizeTextNode(root);
    return;
  }

  if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_FRAGMENT_NODE) {
    return;
  }

  if (root.nodeType === Node.ELEMENT_NODE) normalizeAttributes(root);

  const textWalker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let textNode = textWalker.nextNode();
  while (textNode) {
    normalizeTextNode(textNode);
    textNode = textWalker.nextNode();
  }

  const elementWalker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
  let element = elementWalker.nextNode();
  while (element) {
    normalizeAttributes(element);
    element = elementWalker.nextNode();
  }
}

/**
 * Presentation-boundary compatibility layer.
 *
 * Older stored reports and stable backend checker IDs may still emit legacy
 * wording. This observer normalizes exact user-facing phrases after rendering
 * while deliberately skipping code, SQL/query text marked for preservation,
 * and editable content.
 */
export default function TerminologyNormalizer() {
  useEffect(() => {
    normalizeSubtree(document.body);

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === "characterData") {
          normalizeTextNode(mutation.target);
          continue;
        }

        if (mutation.type === "attributes") {
          normalizeAttributes(mutation.target);
          continue;
        }

        for (const node of mutation.addedNodes) normalizeSubtree(node);
      }
    });

    observer.observe(document.body, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
      attributeFilter: NORMALIZED_ATTRIBUTES,
    });

    return () => observer.disconnect();
  }, []);

  return null;
}
