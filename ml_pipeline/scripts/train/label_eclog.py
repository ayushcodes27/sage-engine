import pandas as pd
import numpy as np
from pathlib import Path
import re
from scipy.stats import entropy
import time
from urllib.parse import urlsplit
import warnings
warnings.filterwarnings("ignore")

# ── Paths ────────────────────────────────────────────────────────────────────
# Use path relative to this script so it runs reliably from anywhere
BASE_DIR = Path(__file__).resolve().parents[2] / "data"
INPUT_FILE = BASE_DIR / "eclog_1day.csv"
OUTPUT_FILE = BASE_DIR / "eclog_weak_labeled.csv"

# ── Constants & Patterns ─────────────────────────────────────────────────────
# Tier 1 - High confidence bot
BOT_UA_PATTERNS = re.compile(
    r"(SemrushBot|Googlebot|bingbot|MJ12bot|AhrefsBot|DotBot|YandexBot|"
    r"Baiduspider|PetalBot|SeznamBot|crawler|spider|bot\.html)", 
    re.IGNORECASE
)

# Tier 2 - Medium confidence bot (programmatic / short)
PROGRAMMATIC_UA_PATTERNS = re.compile(
    r"(Go-http-client|python-requests|curl/|wget/|Java/|libwww-perl|Scrapy)",
    re.IGNORECASE
)

# Tier 3 - High confidence human (standard browsers without bot markers)
BROWSER_UA_PATTERNS = re.compile(
    r"(Mozilla/5\.0.*(Chrome|Firefox|Safari|Edge|Opera))",
    re.IGNORECASE
)

STATIC_ASSET_EXTS = ('.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.woff', '.woff2', '.ttf', '.svg', '.webp')
CART_KEYWORDS = ('koszyk', 'platnosc', 'zamowienie', 'checkout', 'cart', 'payment')

def get_label_and_confidence(ua):
    if pd.isna(ua):
        return 'unknown', 'none'
    
    ua = str(ua).strip()
    if len(ua) < 10 or ua == '-':
        return 'unknown', 'none'
        
    if BOT_UA_PATTERNS.search(ua):
        return 'bot', 'high'
        
    if PROGRAMMATIC_UA_PATTERNS.search(ua):
        return 'bot', 'medium'
        
    if BROWSER_UA_PATTERNS.search(ua):
        return 'human', 'high'
        
    return 'unknown', 'none'

def extract_path(uri):
    """Extracts and canonicalizes the path portion from a URI."""
    if pd.isna(uri):
        return "/"

    value = str(uri).strip()
    path = urlsplit(value).path or "/"
    path = re.sub(r"/+", "/", path)
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return path.lower() or "/"

def is_static_asset(uri_path):
    if pd.isna(uri_path): return False
    return uri_path.startswith('/static/') or uri_path.endswith(STATIC_ASSET_EXTS)

def is_cart_uri(uri_path):
    if pd.isna(uri_path): return False
    return any(kw in uri_path for kw in CART_KEYWORDS)

def compute_entropy(series):
    counts = series.value_counts()
    if len(counts) <= 1:
        return 0.0
    return float(entropy(counts, base=np.e))

def extract_path(uri):
    """Extracts and canonicalizes the path portion from a URI."""
    if pd.isna(uri):
        return "/"

    value = str(uri).strip()
    path = urlsplit(value).path or "/"
    path = re.sub(r"/+", "/", path).rstrip("/")
    return path.lower() or "/"

def process_data():
    print("=== 1. LOADING RAW ECLog DATA ===")
    df = pd.read_csv(INPUT_FILE)
    print(f"Loaded {len(df)} rows.")

    print("\n=== 2. APPLYING WEAK-SUPERVISION LABELS ===")
    labels_conf = df['UserAgent'].apply(get_label_and_confidence)
    df['req_label'] = labels_conf.apply(lambda x: x[0])
    df['req_confidence'] = labels_conf.apply(lambda x: x[1])
    
    print("\nLabel Distribution (Row Level):")
    print(df['req_label'].value_counts())
    print("\nConfidence Breakdown:")
    print(df.groupby(['req_label', 'req_confidence']).size())

    print("\n=== 3. INACTIVITY-BASED SESSIONIZATION ===")
    # Convert .NET ticks (100ns intervals since 0001-01-01) to seconds
    # 637116156000000000 ticks -> 63711615600 seconds. 
    df['TimeSec'] = df['TimeStamp'] / 10_000_000.0
    df = df.sort_values(by=['IpId', 'TimeSec']).reset_index(drop=True)
    
    # Calculate time gaps between consecutive requests for the same IP
    df['time_gap'] = df.groupby('IpId')['TimeSec'].diff().fillna(0)
    
    # New session starts if gap > 300 seconds (5 minutes)
    df['new_session'] = (df['time_gap'] > 300).astype(int)
    
    # Cumulative sum of new_session per IP creates a unique session index per IP
    df['session_idx'] = df.groupby('IpId')['new_session'].cumsum()
    
    print(f"Total unique sessions identified: {df.groupby(['IpId', 'session_idx']).ngroups}")

    print("\n=== 4. FEATURE ENGINEERING ===")
    # Pre-calculate canonical paths and flags
    df['Uri_path'] = df['Uri'].apply(extract_path)
    df['is_static'] = df['Uri_path'].apply(is_static_asset).astype(int)
    df['is_cart'] = df['Uri_path'].apply(is_cart_uri).astype(int)
    
    sessions = []
    
    grouped = df.groupby(['IpId', 'session_idx'])
    for (ip, s_idx), group in grouped:
        total_hits = len(group)
        cart_hits = group['is_cart'].sum()
        static_hits = group['is_static'].sum()
        
        cart_ratio = cart_hits / total_hits if total_hits > 0 else 0.0
        asset_skip_ratio = 1.0 - (static_hits / total_hits) if total_hits > 0 else 1.0
        
        bot_share = (group["req_label"] == "bot").sum() / total_hits
        human_share = (group["req_label"] == "human").sum() / total_hits
        
        if bot_share >= 0.80:
            dominant_label = "bot"
            bot_rows = group[group["req_label"] == "bot"]
            if 'medium' in bot_rows['req_confidence'].values:
                dominant_conf = 'medium'
            else:
                dominant_conf = 'high'
        elif human_share >= 0.80:
            dominant_label = "human"
            dominant_conf = "high"
        else:
            dominant_label = "unknown"
            dominant_conf = "none"
            
        non_static_group = group[group['is_static'] == 0]
        recent_non_static = non_static_group.tail(50)
        
        req_count = len(recent_non_static)
        session_depth = req_count
        
        if req_count >= 2:
            times = recent_non_static['TimeSec'].values
            duration = times[-1] - times[0]
            timeSpanSeconds = max(duration, 0.001)
            velocity = req_count / timeSpanSeconds
            
            gaps = np.diff(times)
            mean_iat = np.mean(gaps)
            if mean_iat == 0:
                temporal_var = 0.0
            else:
                std_iat = np.std(gaps)
                temporal_var = float(std_iat / mean_iat)
                
            diversity = compute_entropy(recent_non_static['Uri_path'])
            path_counts = recent_non_static['Uri_path'].value_counts()
            endpoint_conc = path_counts.iloc[0] / req_count
            
            non_static_nav_gap = float(np.median(gaps))
            non_static_long_gap_ratio = float(np.mean(gaps >= 0.50))
        else:
            velocity = 1.0
            temporal_var = 0.0
            diversity = 0.0
            endpoint_conc = 1.0 if req_count == 1 else 0.0
            non_static_nav_gap = 0.0
            non_static_long_gap_ratio = 0.0
        
        sessions.append({
            'IpId': ip,
            'session_id': f"{ip}_sess{s_idx}",
            'SAGE_Session_Depth': session_depth,
            'SAGE_Temporal_Variance': temporal_var,
            'SAGE_Request_Velocity': velocity,
            'SAGE_Behavioral_Diversity': diversity,
            'SAGE_Endpoint_Concentration': endpoint_conc,
            'SAGE_Cart_Ratio': cart_ratio,
            'SAGE_Asset_Skip_Ratio': asset_skip_ratio,
            'SAGE_NonStatic_Navigation_Gap': non_static_nav_gap,
            'SAGE_NonStatic_Long_Gap_Ratio': non_static_long_gap_ratio,
            'label': dominant_label,
            'label_confidence': dominant_conf
        })
        
    df_sessions = pd.DataFrame(sessions)
    
    print(f"\nGenerated {len(df_sessions)} sessions.")
    print("\nSession-Level Label Distribution:")
    print(df_sessions['label'].value_counts())
    print("\nSession-Level Confidence Distribution:")
    print(df_sessions.groupby(['label', 'label_confidence']).size())
    
    print("\n=== 5. SAVING LABELED DATASET ===")
    df_sessions.to_csv(OUTPUT_FILE, index=False)
    print(f"Saved successfully to: {OUTPUT_FILE}")
    
    print("\nFeature Summary (Means, excluding 'unknown'):")
    known_sessions = df_sessions[df_sessions['label'] != 'unknown']
    if len(known_sessions) > 0:
        print(known_sessions.groupby('label')[
            ['SAGE_Session_Depth', 'SAGE_Request_Velocity', 'SAGE_Behavioral_Diversity', 
             'SAGE_Endpoint_Concentration', 'SAGE_Cart_Ratio', 'SAGE_Asset_Skip_Ratio',
             'SAGE_NonStatic_Navigation_Gap', 'SAGE_NonStatic_Long_Gap_Ratio']
        ].mean().round(3))
    else:
        print("No known sessions found.")

if __name__ == "__main__":
    t0 = time.time()
    process_data()
    print(f"\nCompleted in {time.time()-t0:.1f}s")
