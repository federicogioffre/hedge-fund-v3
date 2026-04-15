import { Header } from "./components/Header";
import { FundState } from "./components/FundState";
import { Positions } from "./components/Positions";
import { Ranking } from "./components/Ranking";
import { AnalyzeForm } from "./components/AnalyzeForm";
import { RebalancePanel } from "./components/RebalancePanel";

export default function App() {
  return (
    <div className="min-h-screen bg-bg text-slate-200">
      <Header />

      <main className="mx-auto max-w-7xl space-y-6 px-4 py-6">
        {/* Row 1: KPIs */}
        <FundState />

        {/* Row 2: Positions + Right column actions */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <Positions />
          </div>
          <div className="space-y-6">
            <AnalyzeForm />
            <RebalancePanel />
          </div>
        </div>

        {/* Row 3: Ranking */}
        <Ranking />

        <footer className="pt-4 text-center text-xs text-muted">
          Hedge Fund V7 · multi-agent research · paper/live trading · risk-guarded
        </footer>
      </main>
    </div>
  );
}
