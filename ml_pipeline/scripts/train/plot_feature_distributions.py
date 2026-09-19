"""
SAGE Engine — Feature Distribution Visualization Script
Generates boxplots for all 7 behavioral features across the 4 traffic classes:
human | flood | scraper | recon
"""

from pathlib import Path
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

# ── Paths ────────────────────────────────────────────────────────────────────
DATA_PATH = Path("ml_pipeline/data/training_data.csv")
OUTPUT_PATH = Path("ml_pipeline/models/feature_distributions.png")
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

FEATURES = [
    "SAGE_Session_Depth",
    "SAGE_Temporal_Variance",
    "SAGE_Request_Velocity",
    "SAGE_Behavioral_Diversity",
    "SAGE_Endpoint_Concentration",
    "SAGE_Cart_Ratio",
    "SAGE_Asset_Skip_Ratio",
]
LABEL_COL = "label"

def plot_feature_distributions():
    print("=== LOADING DATASET ===")
    df = pd.read_csv(DATA_PATH)
    
    # Filter residual dummy vectors
    dummy_mask = (
        (df["SAGE_Asset_Skip_Ratio"] == 1.0) &
        (df["SAGE_Session_Depth"]    == 0.0) &
        (df["SAGE_Request_Velocity"] == 0.0) &
        (df["SAGE_Temporal_Variance"]== 0.0)
    )
    if dummy_mask.sum() > 0:
        df = df[~dummy_mask].reset_index(drop=True)
        
    classes = sorted(df[LABEL_COL].unique())
    print(f"Data shape: {df.shape} | Classes: {classes}")
    
    # Setup subplots grid (3x3 grid for 7 features)
    fig, axes = plt.subplots(3, 3, figsize=(15, 12))
    axes = axes.flatten()
    
    colors = ['#2ca02c', '#d62728', '#ff7f0e', '#9467bd'] # green (human), red (flood), orange (scraper), purple (recon)
    
    for idx, feature in enumerate(FEATURES):
        ax = axes[idx]
        data_per_class = [df[df[LABEL_COL] == cls][feature].values for cls in classes]
        
        box = ax.boxplot(
            data_per_class,
            labels=classes,
            patch_artist=True,
            showfliers=False,
            medianprops=dict(color="black", linewidth=1.5)
        )
        
        for patch, color in zip(box['boxes'], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
            
        ax.set_title(feature, fontsize=12, fontweight="bold", pad=8)
        ax.grid(axis="y", linestyle="--", alpha=0.5)
        ax.tick_params(axis="x", rotation=15)

    # Hide unused grid cells (cell 7 and 8 in 3x3)
    for i in range(len(FEATURES), len(axes)):
        fig.delaxes(axes[i])
        
    fig.suptitle("SAGE Behavioral Feature Distributions by Traffic Persona", fontsize=16, fontweight="bold", y=0.98)
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    
    plt.savefig(OUTPUT_PATH, dpi=150)
    plt.close()
    print(f"✅ Feature distributions plot saved to → {OUTPUT_PATH}")

if __name__ == "__main__":
    plot_feature_distributions()
