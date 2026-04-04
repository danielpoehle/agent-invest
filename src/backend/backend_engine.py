import pandas as pd
import numpy as np
import vectorbt as vbt
import yfinance as yf

# ==========================================
# 1. PARAMETER FÜR DIE STRATEGIE
# ==========================================
TICKERS = ["AAPL", "MSFT", "NVDA", "ASML", "SAP", "TSLA", "META"] 
START_DATE = "2014-01-01" 
END_DATE = "2024-01-01"

# ==========================================
# 2. DATENBESCHAFFUNG 
# ==========================================
print(f"Lade Daten für {len(TICKERS)} Ticker...")
data = yf.download(TICKERS, start=START_DATE, end=END_DATE)

# Sicherer Zugriff auf die Kurs-Spalten (Fallback für neuere yfinance Versionen)
close_col = 'Close' if 'Close' in data.columns.get_level_values(0) else 'Adj Close'
price = data[close_col]
high = data['High']
low = data['Low']

# ==========================================
# 3. INDIKATOREN BERECHNEN (Vektorisiert)
# ==========================================
print("Berechne technische Indikatoren...")

# Gleitende Durchschnitte (inkl. Korrektur der Spaltennamen für Pandas/Vectorbt)
sma_50 = vbt.MA.run(price, window=50).ma
sma_50.columns = price.columns

sma_150 = vbt.MA.run(price, window=150).ma
sma_150.columns = price.columns

sma_200 = vbt.MA.run(price, window=200).ma
sma_200.columns = price.columns

# SMA 200 Trend (Ist der SMA 200 höher als vor 20 Handelstagen / ~4 Wochen?)
sma_200_20d_ago = sma_200.shift(20)

# 52-Wochen Hoch und Tief (252 Handelstage)
high_52w = high.rolling(window=252).max()
low_52w = low.rolling(window=252).min()

# Pullback Indikator (inkl. Korrektur der Spaltennamen)
rsi = vbt.RSI.run(price, window=14).rsi
rsi.columns = price.columns

# ==========================================
# 4. SIGNAL-GENERIERUNG (Logik)
# ==========================================

# --- SCHRITT 1: DIE 7 "MINERVINI" TREND-KRITERIEN (Warme Watchlist) ---
c1 = price > sma_50
c2 = (price > sma_150) & (price > sma_200)
c3 = sma_150 > sma_200
c4 = (sma_50 > sma_150) & (sma_50 > sma_200)
c5 = sma_200 > sma_200_20d_ago # SMA200 steigt seit 4 Wochen
c6 = price >= (low_52w * 1.30) # Mind. 30% über 52W-Tief
c7 = price >= (high_52w * 0.75) # Max. 25% unter 52W-Hoch

# Alle Kriterien müssen erfüllt sein für den "Trend-Modus"
trend_template_active = c1 & c2 & c3 & c4 & c5 & c6 & c7

# --- SCHRITT 2: DER PULLBACK TRIGGER (Heiße Watchlist) ---
# Wir suchen nach einem Rücksetzer innerhalb dieses starken Trends
pullback_trigger = rsi < 40 

# KAUFSIGNAL: Trend Template ist erfüllt UND wir haben einen Pullback
entries = trend_template_active & pullback_trigger

# VERKAUFSIGNAL: Wenn die Struktur bricht (Kurs fällt unter SMA 50)
exits = price < sma_50

# ==========================================
# 5. BACKTEST AUSFÜHREN
# ==========================================
print("Führe Backtest durch...")
portfolio = vbt.Portfolio.from_signals(
    price, 
    entries, 
    exits, 
    init_cash=10000, 
    fees=0.001, 
    freq='D' 
)

print("\n--- BACKTEST ERGEBNISSE ---")
# Generiere Tabelle pro Ticker, um NaN-Fehler durch fehlende Trades zu vermeiden
results = pd.DataFrame({
    'Rendite [%]': portfolio.total_return() * 100,
    'Max Drawdown [%]': portfolio.max_drawdown() * 100,
    'Win Rate [%]': portfolio.trades.win_rate() * 100,
    'Anzahl Trades': portfolio.trades.count()
})

results.fillna(0, inplace=True)
print(results.sort_values(by='Rendite [%]', ascending=False).round(2))


# ==========================================
# 6. GESAMT-PORTFOLIO & BENCHMARK VERGLEICH
# ==========================================
print("\nLade Benchmark-Daten (MSCI World ETF - URTH)...")
# URTH ist der Ticker für den iShares MSCI World ETF
benchmark_data = yf.download(["URTH"], start=START_DATE, end=END_DATE, progress=False)

bench_close_col = 'Close' if 'Close' in benchmark_data.columns.get_level_values(0) else 'Adj Close'
benchmark_price = benchmark_data[bench_close_col]

# Absicherung, falls es als DataFrame geliefert wird
if isinstance(benchmark_price, pd.DataFrame):
    benchmark_price = benchmark_price.squeeze()

# Buy & Hold Return des Benchmarks berechnen
benchmark_return = (benchmark_price.iloc[-1] / benchmark_price.iloc[0] - 1) * 100

# Gesamtes Startkapital (10.000 pro Ticker)
total_start_value = 10000 * len(TICKERS)
# Summe aller Endwerte der Einzelportfolios (Equity Curve am letzten Tag)
total_end_value = portfolio.value().iloc[-1].sum()
total_portfolio_return = ((total_end_value / total_start_value) - 1) * 100

print("\n" + "="*60)
print("GESAMTPORTFOLIO VS. BENCHMARK (MSCI World)")
print("="*60)
print(f"Startkapital Gesamt:       {total_start_value:,.2f} €")
print(f"Endkapital Gesamt:         {total_end_value:,.2f} €")
print(f"Gesamtrendite Strategie:   {total_portfolio_return:.2f} %")
print(f"Buy & Hold MSCI World:     {float(benchmark_return):.2f} %")
print("="*60)

# In der Produktion würde das System nun ausgeben:
# "Folgende Aktien sind heute HEISS (Kaufsignal): [Liste]"
# "Folgende Aktien sind WARM (Trend Template erfüllt, warten auf Pullback): [Liste]"