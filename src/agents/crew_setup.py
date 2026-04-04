import os
import json
import yaml
from dotenv import load_dotenv
from typing import List, Optional
from pydantic import BaseModel, Field
from crewai import Agent, Task, Crew, Process, LLM


load_dotenv()

# ==========================================
# PYDANTIC MODELLE (Strukturierte Datenausgabe)
# ==========================================
# Diese Klassen zwingen die Agenten, strukturierte Daten (JSON) weiterzugeben.

class StockSentiment(BaseModel):
    ticker: str = Field(..., description="Das Ticker-Symbol der Aktie")
    sentiment_score: int = Field(..., description="Sentiment-Score von 1 bis 10 basierend auf den News")
    reasoning: str = Field(..., description="Kurze Begründung für den vergebenen Sentiment-Score")

class DataAnalysisOutput(BaseModel):
    market_regime: str = Field(..., description="Das aktuelle Markt-Regime: RISK_ON, RISK_OFF oder NEUTRAL")
    regime_reasoning: str = Field(..., description="Begründung für das gewählte Market Regime")
    stock_sentiments: List[StockSentiment] = Field(..., description="Liste der analysierten und bewerteten Aktien")

class TradeDecision(BaseModel):
    ticker: str = Field(..., description="Das Ticker-Symbol der Aktie")
    action: str = Field(..., description="Freigabe-Status: GO, NO-GO oder SCALED")
    suggested_size_eur: float = Field(..., description="Exakt berechnete Positionsgröße in Euro. 0 bei NO-GO.")
    stop_loss: float = Field(..., description="Vorgeschlagenes Stop-Loss Level")
    take_profit: Optional[float] = Field(None, description="Optionales Take-Profit Level")
    reasoning: str = Field(..., description="Begründung der Entscheidung inkl. Sektor-Limits und Risk-Limits")

class RiskEvaluationOutput(BaseModel):
    portfolio_health_status: str = Field(..., description="Kurze Einschätzung der aktuellen Portfolio-Gesundheit")
    allocation_advice: str = Field(..., description="Konkrete Empfehlung zur Cash/Aktien Allokation basierend auf dem Market Regime")
    trade_decisions: List[TradeDecision] = Field(..., description="Liste der finalen Trade-Entscheidungen für jede vorgeschlagene Aktie")

# ==========================================
# CREWAI SETUP
# ==========================================

class InvestmentCrew:
    def __init__(self, data_payload, current_portfolio, signal_prices):
        self.data_payload = data_payload
        self.current_portfolio = current_portfolio
        self.signal_prices = signal_prices
        
        # Konfigurationsdateien laden
        base_dir = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(base_dir, 'config', 'agent.yaml'), 'r', encoding='utf-8') as f:
            self.agents_config = yaml.safe_load(f)
            
        with open(os.path.join(base_dir, 'config', 'task.yaml'), 'r', encoding='utf-8') as f:
            self.tasks_config = yaml.safe_load(f)
        
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY wurde nicht in der .env Datei gefunden!")
            
        self.llm = LLM(
            #model="gemini/gemini-2.5-flash-lite", 
            model="gemini/gemini-2.5-flash",
            api_key=api_key,
            temperature=0.1 
        )

    def _create_agents(self):
        # **kwargs entpackt automatisch die Felder (role, goal, backstory) aus der YAML
        data_agent = Agent(
            **self.agents_config['data_agent'],
            verbose=True,
            allow_delegation=False,
            llm=self.llm
        )

        risk_agent = Agent(
            **self.agents_config['risk_agent'],
            verbose=True,
            allow_delegation=False,
            llm=self.llm
        )
        
        lead_agent = Agent(
            **self.agents_config['lead_agent'],
            verbose=True,
            allow_delegation=False,
            llm=self.llm
        )
        
        return data_agent, risk_agent, lead_agent

    def _create_tasks(self, data_agent, risk_agent, lead_agent):
        
        # Formatieren der Platzhalter in den YAML-Beschreibungen
        analyze_desc = self.tasks_config['analyze_data']['description'].format(
            data_payload=json.dumps(self.data_payload)
        )
        task_analyze_data = Task(
            description=analyze_desc,
            expected_output=self.tasks_config['analyze_data']['expected_output'],
            agent=data_agent,
            output_pydantic=DataAnalysisOutput # <--- HIER: Zwingt den Agenten in das Daten-Format!
        )

        evaluate_desc = self.tasks_config['evaluate_risk']['description'].format(
            current_portfolio=json.dumps(self.current_portfolio),
            signal_prices=json.dumps(self.signal_prices)
        )
        task_evaluate_risk = Task(
            description=evaluate_desc,
            expected_output=self.tasks_config['evaluate_risk']['expected_output'],
            agent=risk_agent,
            output_pydantic=RiskEvaluationOutput # <--- HIER: Zwingt den Agenten in das Daten-Format!
        )

        task_write_report = Task(
            description=self.tasks_config['write_report']['description'],
            expected_output=self.tasks_config['write_report']['expected_output'],
            agent=lead_agent
        )
        
        return [task_analyze_data, task_evaluate_risk, task_write_report]

    def run(self):
        data_agent, risk_agent, lead_agent = self._create_agents()
        tasks = self._create_tasks(data_agent, risk_agent, lead_agent)
        
        crew = Crew(
            agents=[data_agent, risk_agent, lead_agent],
            tasks=tasks,
            process=Process.sequential,
            verbose=True
        )
        
        print("Starte die KI-Agenten Crew...")
        return crew.kickoff()

if __name__ == "__main__":
    # Test-Daten
    mock_data_payload = {
        "macro_indicators": {"vix_current": 18.5, "macro_health_pre_check": "STABLE"},
        "hot_stocks_to_analyze": [{"ticker": "NVDA", "recent_news": [{"title": "Nvidia dominates AI"}]}]
    }
    
    mock_portfolio = {
        "total_value": 100000,
        "equities": [{"ticker": "MSFT", "sector": "Technology", "region": "US", "value": 45000}] 
    }
    
    # Der Risk Agent braucht aktuelle Preise für die Formel!
    mock_prices = {"NVDA": 130.50}
    
    try:
        crew = InvestmentCrew(mock_data_payload, mock_portfolio, mock_prices)
        print("\n" + "="*70)
        print(crew.run())
        
    except Exception as e:
        print(f"Fehler: {e}")