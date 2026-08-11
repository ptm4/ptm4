import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { redirectLegacyHash } from './lib/legacyHash';
import { watchThemeAcrossTabs } from './lib/theme';
import './styles/tokens.css';
import './styles/app.css';
import './styles/board.css';
import './styles/pages.css';

// Old #hash bookmarks resolve before the router mounts.
redirectLegacyHash();
watchThemeAcrossTabs();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Homelab data is poll-based; each hook sets its own refetchInterval to match
      // the v1 cadence (30s live tiles, 5min reports…). Background tabs pause
      // automatically — the hand-rolled visibility timers of v1 are gone.
      staleTime: 15_000,
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
