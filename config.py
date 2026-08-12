"""Ortam ayarlari - .env'den okur."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
KEEPA_API_KEY = os.getenv("KEEPA_API_KEY", "")
STRATEGY_MODEL = os.getenv("STRATEGY_MODEL", "claude-sonnet-4-6")
SUPERVISOR_MODEL = os.getenv("SUPERVISOR_MODEL", "claude-fable-5")
# Launch (sifir urun) keyword + strateji uretimi.
# Olculdu: opus-5 985sn / sonnet-4-6 83sn (12x hizli), keyword kalitesi esit.
# Maksimum kalite icin .env'e LAUNCH_MODEL=claude-opus-5 yazilabilir, ancak
# senkron istek 16 dakika surer; arayuz icin sonnet varsayilandir.
LAUNCH_MODEL = os.getenv("LAUNCH_MODEL", "claude-sonnet-4-6")

# AI cagrilarinda kullanilacak limitler
MAX_STRATEGY_TOKENS = 8000
# Launch AI: dusunen model kullanildigi icin bol timeout + token gerekir.
MAX_LAUNCH_TOKENS = int(os.getenv("MAX_LAUNCH_TOKENS", "8000"))
LAUNCH_AI_TIMEOUT = float(os.getenv("LAUNCH_AI_TIMEOUT", "300"))
MAX_SUPERVISOR_TOKENS = 4000
MAX_SUPERVISOR_RETRIES = 2

# Veri yeterliligi esikleri (AI ayrica kendi degerlendirmesini yapar)
MIN_CLICKS_FOR_STRATEGY = 50
MIN_DAYS_FOR_STRATEGY = 14

# Amazon Advertising API (opsiyonel). Kurulum: ADS_API_KURULUM.md
# Bu degerler .env'den okunur, koda yazilmaz.
ADS_CLIENT_ID = os.getenv("ADS_CLIENT_ID", "")
ADS_CLIENT_SECRET = os.getenv("ADS_CLIENT_SECRET", "")
ADS_REFRESH_TOKEN = os.getenv("ADS_REFRESH_TOKEN", "")
ADS_PROFILE_ID = os.getenv("ADS_PROFILE_ID", "")
ADS_REGION = os.getenv("ADS_REGION", "NA")
