"""Ortam ayarlari - .env'den okur."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
KEEPA_API_KEY = os.getenv("KEEPA_API_KEY", "")
STRATEGY_MODEL = os.getenv("STRATEGY_MODEL", "claude-sonnet-4-6")
SUPERVISOR_MODEL = os.getenv("SUPERVISOR_MODEL", "claude-fable-5")

# AI cagrilarinda kullanilacak limitler
MAX_STRATEGY_TOKENS = 8000
MAX_SUPERVISOR_TOKENS = 4000
MAX_SUPERVISOR_RETRIES = 2

# Veri yeterliligi esikleri (AI ayrica kendi degerlendirmesini yapar)
MIN_CLICKS_FOR_STRATEGY = 50
MIN_DAYS_FOR_STRATEGY = 14
