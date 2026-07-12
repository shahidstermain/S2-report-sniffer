import * as React from "react";

interface BrowserRouterProps {
  children: React.ReactNode;
}

function BrowserRouter({ children }: BrowserRouterProps) {
  return React.createElement(React.Fragment, null, children);
}

interface RoutesProps {
  children: React.ReactNode;
}

function Routes({ children }: RoutesProps) {
  return React.createElement(React.Fragment, null, children);
}

interface RouteProps {
  element: React.ReactNode;
}

function Route({ element }: RouteProps) {
  return React.createElement(React.Fragment, null, element);
}

interface LinkProps extends React.AnchorHTMLAttributes<HTMLAnchorElement> {
  to: string | object;
  children: React.ReactNode;
}

function Link({ children, to, ...rest }: LinkProps) {
  return React.createElement(
    "a",
    { href: typeof to === "string" ? to : "#", ...rest },
    children
  );
}

type NavigateFn = (path: string) => void;

function useNavigate(): NavigateFn {
  return () => {};
}

function useParams(): Record<string, string> {
  return {};
}

export { BrowserRouter, Routes, Route, Link, useNavigate, useParams };
