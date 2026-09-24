import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { RendererErrorBoundary } from './components/RendererErrorBoundary';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RendererErrorBoundary>
      <App />
    </RendererErrorBoundary>
  </React.StrictMode>,
);
