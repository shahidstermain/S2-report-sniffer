const React = require('react');

function BrowserRouter({ children }) {
  return React.createElement(React.Fragment, null, children);
}

function Routes({ children }) {
  return React.createElement(React.Fragment, null, children);
}

function Route({ element }) {
  return React.createElement(React.Fragment, null, element);
}

function Link({ children, to, ...rest }) {
  return React.createElement('a', { href: typeof to === 'string' ? to : '#', ...rest }, children);
}

function useNavigate() {
  return () => {};
}

function useParams() {
  return {};
}

module.exports = {
  BrowserRouter,
  Routes,
  Route,
  Link,
  useNavigate,
  useParams,
};

