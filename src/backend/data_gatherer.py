import yfinance as yf
import json
from datetime import datetime

class DataGatherer:
    """
    Diese Klasse sammelt makroökonomische Indikatoren und aktienspezifische 
    Nachrichten und formatiert sie als strukturierten Input (JSON) für den KI-Agenten.
    """
    
    def __init__(self):
        pass
        
    def get_macro_data(self):
        """Holt aktuelle Marktdaten (VIX, Zinsen)."""
        print("Sammle Makro-Daten (VIX, Zinskurve)...")
        # ^VIX = Volatility Index
        # ^TNX = 10-Year US Treasury Yield
        # ^IRX = 13-Week US Treasury Bill (Kurzläufer)
        tickers = yf.Tickers('^VIX ^TNX ^IRX')
        
        try:
            # Wir nehmen den letzten Schlusskurs
            vix_close = tickers.tickers['^VIX'].history(period="1d")['Close'].iloc[-1]
            tnx_close = tickers.tickers['^TNX'].history(period="1d")['Close'].iloc[-1]
            irx_close = tickers.tickers['^IRX'].history(period="1d")['Close'].iloc[-1]
            
            # Zinsstrukturkurve (Langläufer minus Kurzläufer)
            # Invers (negativ) = Warnsignal
            yield_curve = tnx_close - irx_close
            
            return {
                "vix_current": round(vix_close, 2),
                "short_term_rate_3m": round(irx_close, 2),
                "yield_curve_10y_minus_3m": round(yield_curve, 2),
                # Kleine Vorab-Logik, die dem Agenten hilft
                "macro_health_pre_check": "WARNING" if vix_close > 25 else ("STABLE" if vix_close < 20 else "NEUTRAL")
            }
        except Exception as e:
            print(f"Fehler beim Abruf der Makro-Daten: {e}")
            return {}

    def get_stock_news(self, tickers, limit=6):
        """Holt die neuesten Nachrichten-Headlines inkl. Zusammenfassung und Datum für bestimmte Ticker."""
        print(f"Sammle die neuesten News für {len(tickers)} Ticker...")
        news_data = []
        
        for ticker in tickers:
            try:
                t = yf.Ticker(ticker)
                raw_news = t.news
                
                extracted_news = []
                for item in raw_news[:limit]:
                    # Standard-Struktur prüfen
                    title = item.get('title')
                    publisher = item.get('publisher')
                    link = item.get('link')
                    summary = item.get('summary')
                    
                    # Zeitstempel extrahieren und formatieren
                    publish_time = item.get('providerPublishTime')
                    formatted_time = "Unbekanntes Datum"
                    
                    # Alternative verschachtelte Struktur (häufig bei neueren Versionen)
                    if not title and 'content' in item:
                        content = item['content']
                        title = content.get('title')
                        provider = content.get('provider', {})
                        publisher = provider.get('displayName') if isinstance(provider, dict) else provider
                        summary = summary or content.get('summary')
                        
                        if not publish_time:
                            pub_date = content.get('pubDate')
                            if pub_date:
                                formatted_time = str(pub_date)
                                
                        # Versuche den Link aus der verschachtelten URL zu holen
                        canonical = content.get('canonicalUrl', {})
                        if isinstance(canonical, dict):
                            link = link or canonical.get('url')
                            
                    # Timestamp-Formatierung, falls es als Unix-Timestamp vorliegt
                    if publish_time and isinstance(publish_time, (int, float)):
                        try:
                            formatted_time = datetime.fromtimestamp(publish_time).strftime('%Y-%m-%d %H:%M:%S')
                        except Exception:
                            pass
                        
                    # Fallbacks, falls Datenfelder wirklich fehlen
                    title = title or "Kein Titel"
                    publisher = publisher or "Unbekannt"
                    summary = summary or "Keine Zusammenfassung verfügbar."
                    link = link or "Kein Link"
                    
                    # Anstelle eines einzelnen Strings übergeben wir ein detailreiches Dictionary
                    extracted_news.append({
                        "published_at": formatted_time,
                        "publisher": publisher,
                        "title": title,
                        "summary": summary,
                        "link": link
                    })
                    
                news_data.append({
                    "ticker": ticker,
                    "recent_news": extracted_news
                })
            except Exception as e:
                print(f"Fehler bei News für {ticker}: {e}")
                
        return news_data

    def prepare_agent_payload(self, hot_watchlist):
        """Baut das finale JSON für den KI-Agenten zusammen."""
        macro = self.get_macro_data()
        news = self.get_stock_news(hot_watchlist)
        
        payload = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "macro_indicators": macro,
            "hot_stocks_to_analyze": news
        }
        return payload

# ==========================================
# AUSFÜHRUNG / TESTLAUF
# ==========================================
if __name__ == "__main__":
    gatherer = DataGatherer()
    
    # Wir tun so, als hätte unsere QuantEngine (aus dem vorherigen Skript)
    # heute diese zwei Aktien auf die "Heiße Watchlist" gesetzt:
    test_hot_watchlist = ["AAPL", "MSFT", "NVDA", "ASML", "SAP", "TSLA", "META"]  
    
    # Daten sammeln und JSON bauen
    agent_input = gatherer.prepare_agent_payload(test_hot_watchlist)
    
    print("\n" + "="*70)
    print("JSON PAYLOAD FÜR DEN 'DATA & MACRO AGENTEN' (Übergabe an Gemini):")
    print("="*70)
    print(json.dumps(agent_input, indent=2, ensure_ascii=False))