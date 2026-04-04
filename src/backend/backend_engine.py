import yfinance as yf
import pandas as pd
import numpy as np
import vectorbt as vbt
import os
from datetime import datetime, timedelta

class QuantEngine:
    def __init__(self, tickers, start_date, end_date):
        self.tickers = tickers
        self.start_date = start_date
        self.end_date = end_date
        
        self.price = None
        self.high = None
        self.low = None
        
        self.entries = None
        self.exits = None
        self.warm_list = None
        
    def fetch_data(self):
        """Lädt historische Daten über yfinance herunter (mit täglichem Cache)."""
        cache_dir = "data"
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, "market_data_cache.pkl")
        today = datetime.now().strftime('%Y-%m-%d')

        # 1. Prüfe, ob wir heute schon Daten heruntergeladen haben
        if os.path.exists(cache_file):
            cache_time = datetime.fromtimestamp(os.path.getmtime(cache_file))
            if cache_time.strftime('%Y-%m-%d') == today:
                print("Lade historische Daten rasend schnell aus lokalem Cache...")
                data = pd.read_pickle(cache_file)
                self._process_data(data)
                return

        # 2. Wenn nicht (oder neuer Tag), lade frisch von Yahoo Finance.
        # HINWEIS ZUM CACHING: Wir laden absichtlich JEDEN TAG die kompletten 5 Jahre neu,
        # anstatt nur die fehlenden Tage anzuhängen. Der Grund: 
        # 1. Aktiensplits & Dividenden: yfinance passt historische Daten rückwirkend an. 
        #    Ein bloßes Anhängen würde bei einem Split (z.B. 1:10) zu falschen Crash-Signalen führen.
        # 2. Dynamische Ticker: Wenn du in der settings.yaml neue Ticker hinzufügst,
        #    brauchen diese ohnehin die vollen 5 Jahre Historie.
        print(f"Lade frische Daten von Yahoo Finance für {len(self.tickers)} Ticker von {self.start_date} bis {self.end_date}...")
        data = yf.download(self.tickers, start=self.start_date, end=self.end_date, progress=False, threads=False)
        
        # Speichere Daten für spätere Aufrufe am selben Tag
        data.to_pickle(cache_file)
        self._process_data(data)

    def _process_data(self, data):
        """Hilfsfunktion zum Zuweisen der heruntergeladenen oder gecachten Daten."""
        try:
            close_col = 'Close' if 'Close' in data.columns.get_level_values(0) else 'Adj Close'
            
            # WICHTIG: .ffill() (Forward Fill) füllt Feiertags-Lücken mit dem Vortageskurs.
            # Das verhindert, dass gemischte US/EU-Kalender die 200-Tage-Linie mit NaNs zerstören!
            if len(self.tickers) > 1:
                self.price = data[close_col].ffill()
                self.high = data['High'].ffill()
                self.low = data['Low'].ffill()
            else:
                self.price = data[[close_col]].rename(columns={close_col: self.tickers[0]}).ffill()
                self.high = data[['High']].rename(columns={'High': self.tickers[0]}).ffill()
                self.low = data[['Low']].rename(columns={'Low': self.tickers[0]}).ffill()
                
        except Exception as e:
            print(f"Fehler beim Extrahieren der Spalten. Verfügbare Spalten: {data.columns.get_level_values(0).unique()}")
            raise e
            
        print("Daten erfolgreich geladen und verarbeitet.")

    def run_strategy(self):
        """Berechnet die Minervini-Kriterien und den Pullback-Trigger."""
        print("Berechne Indikatoren und Signale...")
        
        sma_50 = vbt.MA.run(self.price, window=50).ma
        sma_50.columns = self.price.columns 
        
        sma_150 = vbt.MA.run(self.price, window=150).ma
        sma_150.columns = self.price.columns 
        
        sma_200 = vbt.MA.run(self.price, window=200).ma
        sma_200.columns = self.price.columns 
        
        sma_200_20d_ago = sma_200.shift(20)
        
        high_52w = self.high.rolling(window=252).max()
        low_52w = self.low.rolling(window=252).min()
        
        rsi = vbt.RSI.run(self.price, window=14).rsi
        rsi.columns = self.price.columns 
        
        # ==========================================
        # SIGNAL LOGIK: Minervini Trend Template
        # ==========================================
        c1 = self.price > sma_50
        c2 = (self.price > sma_150) & (self.price > sma_200)
        c3 = sma_150 > sma_200
        c4 = (sma_50 > sma_150) & (sma_50 > sma_200)
        c5 = sma_200 > sma_200_20d_ago

        # ANPASSUNG FÜR LARGE CAPS: 
        # 30% Abstand zum 52W-Tief ist für schwere DAX/S&P500 Werte oft zu streng. 
        # Wir lockern dies auf 20% (1.20), um starke, stetige Trends nicht auszuschließen.
        c6 = self.price >= (low_52w * 1.20) 

        c7 = self.price >= (high_52w * 0.75)
        
        self.warm_list = c1 & c2 & c3 & c4 & c5 & c6 & c7

        # ---------------------------------------------------------
        # DIAGNOSTIK: Wir loggen, woran die Aktien scheitern
        # ---------------------------------------------------------
        print("\n" + "-"*50)
        print("DIAGNOSTIK: Minervini Filter am letzten Handelstag")
        print("-" * 50)
        print(f"Total Tickers im Check : {len(self.tickers)}")
        print(f"C1 (Preis > SMA50)     : {c1.iloc[-1].sum()} Aktien")
        print(f"C2 (Preis > SMA200)    : {c2.iloc[-1].sum()} Aktien")
        print(f"C3 (SMA150 > SMA200)   : {c3.iloc[-1].sum()} Aktien")
        print(f"C4 (SMA50 > SMA150)    : {c4.iloc[-1].sum()} Aktien")
        print(f"C5 (SMA200 steigt)     : {c5.iloc[-1].sum()} Aktien")
        print(f"C6 (Preis > 1.20x Low) : {c6.iloc[-1].sum()} Aktien")
        print(f"C7 (Preis > 0.75x High): {c7.iloc[-1].sum()} Aktien")
        print(f"--> Überleben alle C1-C7 (WARM LIST) : {self.warm_list.iloc[-1].sum()} Aktien")
        print("-" * 50 + "\n")
        
        pullback_trigger = rsi < 40 
        self.entries = self.warm_list & pullback_trigger
        
        self.exits = self.price < sma_50
        
        print("Signale erfolgreich generiert.")

    def run_backtest(self, init_cash=100000, fees=0.001):
        """Führt einen Backtest der Strategie durch und gibt Statistiken pro Aktie aus."""
        print("\nStarte Backtest-Simulation...")
        portfolio = vbt.Portfolio.from_signals(
            self.price,
            self.entries,
            self.exits,
            init_cash=init_cash,
            fees=fees,
            freq='D'
        )
        
        print("\n" + "="*60)
        print("BACKTEST ERGEBNISSE (Pro Ticker)")
        print("="*60)
        
        results = pd.DataFrame({
            'Rendite [%]': portfolio.total_return() * 100,
            'Max Drawdown [%]': portfolio.max_drawdown() * 100,
            'Win Rate [%]': portfolio.trades.win_rate() * 100,
            'Anzahl Trades': portfolio.trades.count()
        })
        
        results.fillna(0, inplace=True)
        print(results.sort_values(by='Rendite [%]', ascending=False).round(2))
        return portfolio

    def get_current_signals(self):
        """Liefert die Signale des LETZTEN Handelstages."""
        latest_entries = self.entries.iloc[-1]
        latest_warm = self.warm_list.iloc[-1]
        latest_date = self.entries.index[-1].strftime('%Y-%m-%d')
        
        hot_stocks = latest_entries[latest_entries == True].index.tolist()
        warm_candidates = latest_warm[latest_warm == True].index.tolist()
        warm_stocks = [ticker for ticker in warm_candidates if ticker not in hot_stocks]
        
        return {
            "date": latest_date,
            "hot_watchlist": hot_stocks,
            "warm_watchlist": warm_stocks
        }

if __name__ == "__main__":
    test_tickers = [
        "AAPL", "MSFT", "NVDA", "ASML", "SAP", "TSLA", 
        "JNJ", "XOM", "JPM", "ALV.DE", "MUV2.DE"
    ]
    
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=5*365)).strftime('%Y-%m-%d')
    
    engine = QuantEngine(test_tickers, start_date, end_date)
    
    engine.fetch_data()
    engine.run_strategy()
    engine.run_backtest()
    
    today_signals = engine.get_current_signals()
    
    print("\n" + "="*60)
    print(f"AKTUELLE SIGNALE (Stand: {today_signals['date']})")
    print("="*60)
    print(f"🔥 HEISSE Watchlist (Kaufsignale): {today_signals['hot_watchlist']}")
    print(f"🟡 WARME Watchlist (Trend intakt): {today_signals['warm_watchlist']}")