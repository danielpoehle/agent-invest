import sys
import os
import yaml
import yfinance as yf # NEU importiert für schnellen ETF Abruf
from datetime import datetime, timedelta

# FIX FÜR IMPORT-FEHLER: Fügt den src-Ordner zum Python-Suchpfad hinzu
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backend.backend_engine import QuantEngine
from backend.data_gatherer import DataGatherer
from backend.database import DatabaseManager
from agents.crew_setup import InvestmentCrew

def load_tickers():
    """Lädt die Ticker aus der globalen settings.yaml Datei."""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'settings.yaml')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print("⚠️ settings.yaml nicht gefunden! Nutze Fallback-Ticker.")
        return {"trading": {"tickers": ["AAPL", "MSFT", "NVDA", "ASML", "SAP"], "cash_parking_etfs": ["XEON.DE"]}}

def main():
    print("\n" + "="*50)
    print("🤖 KI INVESTMENT SYSTEM STARTET")
    print("="*50)
    
    # Datenbank initialisieren
    db = DatabaseManager(db_path="data/investment_system.db")

    # Prüfen, ob wir heute schon gelaufen sind (spart API Kosten!)
    if db.has_report_for_today():
        print("\n⚠️ ACHTUNG: Es existiert bereits ein Tagesbericht für heute in der Datenbank!")
        user_input = input("Möchtest du den Bericht überschreiben und die Agenten erneut kostenpflichtig starten? (j/n): ")
        if user_input.lower() != 'j':
            print("Abbruch. Das System wird beendet.")
            return
    
    # ---------------------------------------------------------
    # SCHRITT 1: QUANT ENGINE (Chart-Analyse & Signale)
    # ---------------------------------------------------------
    settings = load_tickers()
    tickers = settings.get('trading', {}).get('tickers', [])
    safe_etfs = settings.get('trading', {}).get('cash_parking_etfs', [])

    # Holen wir uns schnell die aktuellen Preise der sicheren ETFs (nur für heute)
    safe_haven_prices = {}
    if safe_etfs:
        print(f"Lade aktuelle Kurse für Cash-Parking ETFs: {safe_etfs}...")
        safe_data = yf.download(safe_etfs, period="1d", progress=False)
        # Fallback auf Adj Close falls Close fehlt
        col = 'Close' if 'Close' in safe_data.columns.get_level_values(0) else 'Adj Close'
        for etf in safe_etfs:
            try:
                # Pandas MultiIndex Navigation
                if len(safe_etfs) > 1:
                    price = float(safe_data[col][etf].iloc[-1])
                else:
                    price = float(safe_data[col].iloc[-1])
                safe_haven_prices[etf] = price
            except Exception as e:
                print(f"Konnte Preis für {etf} nicht laden.")


    print(f"\nÜberwache {len(tickers)} Ticker aus settings.yaml...")

    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=2*365)).strftime('%Y-%m-%d')
    
    engine = QuantEngine(tickers, start_date, end_date)
    engine.fetch_data()
    engine.run_strategy()
    
    signals = engine.get_current_signals()
    hot_list = signals['hot_watchlist']
    
    print(f"\nSignale für heute ({signals['date']}):")
    print(f"🔥 Hot: {hot_list}")
    print(f"🟡 Warm: {signals['warm_watchlist']}")

    # ---------------------------------------------------------
    # SCHRITT 2: DATA GATHERER (Makro & News)
    # ---------------------------------------------------------
    gatherer = DataGatherer()
    data_payload = gatherer.prepare_agent_payload(hot_list)
    
    signal_prices = {}
    for ticker in hot_list:
        if len(tickers) > 1:
            signal_prices[ticker] = float(engine.price[ticker].iloc[-1])
        else:
            signal_prices[ticker] = float(engine.price.iloc[-1])

    # ---------------------------------------------------------
    # SCHRITT 3: AKTUELLES PORTFOLIO AUS DATENBANK LADEN
    # ---------------------------------------------------------
    # Das Portfolio wird jetzt dynamisch aus der SQLite DB geladen!
    current_portfolio = db.get_portfolio_for_agent()
    print(f"\nPortfolio aus DB geladen: {current_portfolio['total_value']}€ (davon {current_portfolio['cash']}€ Cash)")

    # ---------------------------------------------------------
    # SCHRITT 4: KI AGENTEN CREW STARTEN
    # ---------------------------------------------------------
    try:
        crew = InvestmentCrew(data_payload, current_portfolio, signal_prices, safe_haven_prices)
        final_report_result = crew.run()
        report_text = str(final_report_result)
        
        # Bericht sicher in der Datenbank speichern
        db.save_daily_report(report_text, data_payload)
        print("\n✅ Bericht erfolgreich generiert und in SQLite-Datenbank gespeichert!")
        
        # Optional: Für das Terminal geben wir ihn auch noch mal aus
        print("\n" + "="*50)
        print("Tagesbericht Vorschau:")
        print("="*50)
        print(report_text[:1500] + "...\n(Bericht in DB abgelegt)")
        
    except Exception as e:
        print(f"\n❌ FEHLER BEIM AUSFÜHREN DER CREW: {e}")

if __name__ == "__main__":
    main()