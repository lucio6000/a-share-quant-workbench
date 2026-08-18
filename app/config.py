import os

DATA_MODE = os.getenv("DATA_MODE", "demo").lower().strip()
IFIND_REFRESH_TOKEN = os.getenv("IFIND_REFRESH_TOKEN", "").strip()
IFIND_WATCHLIST = [x.strip() for x in os.getenv(
    "IFIND_WATCHLIST",
    "300750.SZ,600519.SH,000858.SZ,601318.SH,300033.SZ"
).split(",") if x.strip()]

IFIND_BASE_URL = "https://quantapi.51ifind.com/api/v1"
