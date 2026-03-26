import joblib
from sklearn.ensemble import IsolationForest
import numpy as np

# Create a fake model that thinks anything with high 'velocity' is a bot
model = IsolationForest(contamination=0.1)
fake_data = np.random.rand(100, 4) # 100 samples, 4 features
model.fit(fake_data)

# Save the model to a file
joblib.dump(model, 'isolation_forest.pkl')
print("Mock model saved as isolation_forest.pkl")