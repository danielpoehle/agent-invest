import yfinance as yf
import pandas as pd
import numpy as np
import vectorbt as vbt
from datetime import datetime, timedelta

class QuantEngine:
    """
    Diese Klasse ist die zentrale Backend-Engine. Sie lädt Daten, 
    berechnet technische Indikatoren, führt Backtests durch und 
    generiert die täglichen Watchlists für die KI-Agenten.
    """
    
    def __init__(self, tickers, start_date, end_date):
        self.tickers = tickers
        self.start_date = start_date
        self.end_date = end_date
        
        # Leere Platzhalter für die Daten
        self.price = None
        self.high = None
        self.low = None
        
        # Ergebnisse
        self.entries = None
        self.exits = None
        self.warm_list = None
        
    def fetch_data(self):
        """Lädt historische Daten über yfinance herunter."""
        print(f"Lade Daten für {len(self.tickers)} Ticker von {self.start_date} bis {self.end_date}...")
        
        # Download (Gruppiert nach Ticker, dann OHLCV)
        data = yf.download(self.tickers, start=self.start_date, end=self.end_date, progress=False)
        
        # Wir extrahieren die für uns wichtigen Spalten
        # Hinweis: Bei einem einzelnen Ticker ist die Struktur leicht anders, 
        # wir gehen hier von mehreren Tickern aus.
        if len(self.tickers) > 1:
            self.price = data['Close'] # yfinance hat 'Adj Close' oft durch 'Close' ersetzt bzw. wir nehmen den Standard
            self.high = data['High']
            self.low = data['Low']
        else:
            # Fallback für nur einen Ticker
            self.price = data[['Close']].rename(columns={'Close': self.tickers[0]})
            self.high = data[['High']].rename(columns={'High': self.tickers[0]})
            self.low = data[['Low']].rename(columns={'Low': self.tickers[0]})
            
        print("Daten erfolgreich geladen.")

    def run_strategy(self):
        """Berechnet die Minervini-Kriterien und den Pullback-Trigger."""
        print("Berechne Indikatoren und Signale...")
        
        # 1. Gleitende Durchschnitte berechnen
        sma_50 = vbt.MA.run(self.price, window=50).ma
        sma_150 = vbt.MA.run(self.price, window=150).ma
        sma_200 = vbt.MA.run(self.price, window=200).ma
        
        # 2. SMA 200 Trend (Ist der SMA 200 höher als vor 20 Tagen?)
        sma_200_20d_ago = sma_200.shift(20)
        
        # 3. 52-Wochen Hoch/Tief (Ein Jahr hat ca. 252 Handelstage)
        high_52w = self.high.rolling(window=252).max()
        low_52w = self.low.rolling(window=252).min()
        
        # 4. RSI für den Pullback
        rsi = vbt.RSI.run(self.price, window=14).rsi
        
        # ==========================================
        # SIGNAL LOGIK: Minervini Trend Template
        # ==========================================
        c1 = self.price > sma_50
        c2 = (self.price > sma_150) & (self.price > sma_200)
        c3 = sma_150 > sma_200
        c4 = (sma_50 > sma_150) & (sma_50 > sma_200)
        c5 = sma_200 > sma_200_20d_ago
        c6 = self.price >= (low_52w * 1.30)
        c7 = self.price >= (high_52w * 0.75)
        
        # Die Warme Watchlist: Alle Minervini-Kriterien sind erfüllt
        self.warm_list = c1 & c2 & c3 & c4 & c5 & c6 & c7
        
        # Die Heiße Watchlist: Trend ist intakt UND wir haben einen Pullback
        pullback_trigger = rsi < 40 
        self.entries = self.warm_list & pullback_trigger
        
        # Ausstieg: Wenn die Struktur bricht (Fällt unter SMA 50)
        self.exits = self.price < sma_50
        
        print("Signale erfolgreich generiert.")

    def run_backtest(self, init_cash=100000, fees=0.001):
        """Führt einen Backtest der Strategie durch und gibt Statistiken aus."""
        print("\nStarte Backtest-Simulation...")
        portfolio = vbt.Portfolio.from_signals(
            self.price,
            self.entries,
            self.exits,
            init_cash=init_cash,
            fees=fees,
            freq='D'
        )
        print("\n" + "="*40)
        print("BACKTEST ERGEBNISSE (Zusammenfassung)")
        print("="*40)
        # Zeige nur die wichtigsten Metriken, um die Konsole nicht zu überfluten
        stats = portfolio.stats()
        print(stats[['Start Value', 'End Value', 'Total Return [%]', 'Max Drawdown [%]', 'Win Rate [%]']])
        return portfolio

    def get_current_signals(self):
        """
        Diese Funktion ist für die KI-Agenten gedacht. 
        Sie liefert die Signale des LETZTEN Handelstages.
        """
        # Hole die allerletzte Zeile (den heutigen/gestrigen Handelstag)
        latest_entries = self.entries.iloc[-1]
        latest_warm = self.warm_list.iloc[-1]
        latest_date = self.entries.index[-1].strftime('%Y-%m-%d')
        
        hot_stocks = latest_entries[latest_entries == True].index.tolist()
        
        # Warme Aktien sind solche, die das Trend-Template erfüllen, aber HEUTE keinen Entry-Trigger (RSI) haben
        warm_candidates = latest_warm[latest_warm == True].index.tolist()
        warm_stocks = [ticker for ticker in warm_candidates if ticker not in hot_stocks]
        
        return {
            "date": latest_date,
            "hot_watchlist": hot_stocks,
            "warm_watchlist": warm_stocks
        }

# ==========================================
# AUSFÜHRUNG / TESTLAUF
# ==========================================
if __name__ == "__main__":
    # Eine Mischung aus starken Sektoren und Regionen
    test_tickers = [
        "AAPL", "MSFT", "NVDA", "ASML", "SAP", "TSLA", 
        "JNJ", "XOM", "JPM", "ALV.DE", "MUV2.DE"
    ]
    
    # Historie der letzten 5 Jahre für einen schnellen Test
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=5*365)).strftime('%Y-%m-%d')
    
    # 1. Engine initialisieren
    engine = QuantEngine(test_tickers, start_date, end_date)
    
    # 2. Daten laden und Strategie berechnen
    engine.fetch_data()
    engine.run_strategy()
    
    # 3. Backtest ausführen (Optional, um zu sehen wie es historisch lief)
    engine.run_backtest()
    
    # 4. Scanner-Ergebnisse für den KI-Agenten abrufen
    today_signals = engine.get_current_signals()
    
    print("\n" + "="*40)
    print(f"AKTUELLE SIGNALE (Stand: {today_signals['date']})")
    print("="*40)
    print(f"🔥 HEISSE Watchlist (Kaufsignale): {today_signals['hot_watchlist']}")
    print(f"🟡 WARME Watchlist (Trend intakt): {today_signals['warm_watchlist']}")
    print("\n--> Diese JSON-Struktur wird im nächsten Schritt an den 'Data & Macro Agent' übergeben!")