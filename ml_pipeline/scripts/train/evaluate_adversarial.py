import pandas as pd
import pickle
import numpy as np

def evaluate_adversarial_personas(csv_path="ml_pipeline/data/training_data.csv", model_path="ml_pipeline/models/sage_model.pkl"):
    print("=== LOADING ADVERSARIAL TEST DATA ===")
    
    # Load dataset
    df = pd.read_csv(csv_path)
    df = df.dropna()
    
    if "SAGE_Sequential_Traversal" in df.columns:
        df = df.drop(columns=["SAGE_Sequential_Traversal"])
        
    # Isolate personas by their unique IP prefixes
    # AdversarialScraper: 44.x.x.x
    # SlowFlood: 88.x.x.x
    # HumanBrowser: 172.25.x.x
    
    adv_scraper = df[df["session_id"].str.startswith("44.")]
    slow_flood = df[df["session_id"].str.startswith("88.")]
    human = df[df["session_id"].str.startswith("172.25.")]
    
    print(f"Rows found for AdversarialScraper : {len(adv_scraper)}")
    print(f"Rows found for SlowFlood          : {len(slow_flood)}")
    print(f"Rows found for HumanBrowser       : {len(human)}")
    
    if len(adv_scraper) == 0 and len(slow_flood) == 0:
        print("\nNo adversarial data found. Please run Locust with the adversarial tags and export the data first.")
        return
        
    print("\n=== LOADING TRAINED SAGE MODEL ===")
    with open(model_path, "rb") as f:
        artifact = pickle.load(f)
        clf = artifact["model"]
        features = artifact["features"]
        
    print("\n=== EVALUATING ADVERSARIAL PERSONAS ===")
    
    def score_persona(name, persona_df):
        if len(persona_df) == 0:
            return
            
        X = persona_df[features]
        preds = clf.predict(X)
        
        detected = np.sum(preds != "human")
        missed = np.sum(preds == "human")
        total = len(preds)
        
        print(f"{name:<20} -> Detected as Bot: {detected}/{total} ({(detected/total)*100:.1f}%) | Misclassified as Human: {missed}/{total} ({(missed/total)*100:.1f}%)")
        
        # If any got through, let's see their actual feature profiles
        if missed > 0:
            missed_df = persona_df.iloc[preds == "human"]
            print(f"  [!] Profile of misclassified {name} sessions:")
            print("      Mean Request_Velocity:", missed_df["SAGE_Request_Velocity"].mean().round(3))
            print("      Mean Asset_Skip_Ratio:", missed_df["SAGE_Asset_Skip_Ratio"].mean().round(3))
            print("      Mean Endpoint_Concent:", missed_df["SAGE_Endpoint_Concentration"].mean().round(3))

    score_persona("AdversarialScraper", adv_scraper)
    score_persona("SlowFlood", slow_flood)
    
    # Also score humans as a sanity check
    if len(human) > 0:
        X_human = human[features]
        preds_human = clf.predict(X_human)
        false_positives = np.sum(preds_human != "human")
        total_human = len(preds_human)
        print(f"{'HumanBrowser':<20} -> True Human: {total_human-false_positives}/{total_human} | False Positives: {false_positives}/{total_human} ({(false_positives/total_human)*100:.1f}%)")

if __name__ == "__main__":
    evaluate_adversarial_personas()
