import { Routes, Route } from 'react-router-dom';
import { Sidebar } from './components/Sidebar';
import { Topbar } from './components/Topbar';
import { Toasts } from './components/Toasts';
import { CmdK } from './components/CmdK';
import { PageStub } from './components/PageStub';
import BoardPage from './pages/Board';
import LinksPage from './pages/Links';
import LogsPage from './pages/Logs';
import ReportsPage from './pages/Reports';
import SecurityPage from './pages/Security';
import CockpitPage from './pages/Cockpit';
import BotsPage from './pages/Bots';
import LlmPage from './pages/Llm';
import LeetifyPage from './pages/Leetify';
import TrendsPage from './pages/Trends';
import UpdatesPage from './pages/Updates';
import ContainersPage from './pages/Containers';
import PiholePage from './pages/Pihole';
import DataFlowPage from './pages/DataFlow';

export default function App() {
  return (
    <>
      <div className="wallpaper" aria-hidden />
      <div className="shell">
        <Sidebar />
        <div className="main">
          <Topbar />
          <div className="content">
            <Routes>
              <Route path="/" element={<BoardPage slug="home" />} />
              <Route path="/dashboard" element={<BoardPage slug="dashboard" />} />
              <Route path="/b/:slug" element={<BoardPage />} />
              <Route path="/cockpit" element={<CockpitPage />} />
              <Route path="/reports" element={<ReportsPage />} />
              <Route path="/security" element={<SecurityPage />} />
              <Route path="/bots" element={<BotsPage />} />
              <Route path="/leetify" element={<LeetifyPage />} />
              <Route path="/llm" element={<LlmPage />} />
              <Route path="/links" element={<LinksPage />} />
              <Route path="/logs" element={<LogsPage />} />
              <Route path="/trends" element={<TrendsPage />} />
              <Route path="/updates" element={<UpdatesPage />} />
              <Route path="/containers" element={<ContainersPage />} />
              <Route path="/pihole" element={<PiholePage />} />
              <Route path="/data" element={<DataFlowPage />} />
              <Route path="/settings" element={<PageStub title="Settings" phase="P4 — board engine" />} />
              <Route path="*" element={<PageStub title="Not found" phase="404" />} />
            </Routes>
          </div>
        </div>
      </div>
      <Toasts />
      <CmdK />
    </>
  );
}
