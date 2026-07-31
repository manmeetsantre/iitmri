import pandas as pd

# Read CSV
df = pd.read_csv("Tampa_MODEL_INPUT.csv")

# Create new variable
df["local_revenue"] = (df["pricing"] + 1) * df["num_neighbors"]

# Save
df.to_csv("Tampa_MODEL_INPUT.csv", index=False)

# print("Done!")
print(df[["pricing", "num_neighbors", "local_revenue"]].head())