import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

# Load dataset
df = pd.read_csv("data/All_Diets.csv")

# Clean missing values
df[['Protein(g)', 'Carbs(g)', 'Fat(g)']] = df[['Protein(g)', 'Carbs(g)', 'Fat(g)']].fillna(
    df[['Protein(g)', 'Carbs(g)', 'Fat(g)']].mean()
)

# Average macros per diet
avg_macros = df.groupby("Diet_type")[['Protein(g)', 'Carbs(g)', 'Fat(g)']].mean()
print("\nAverage Macros per Diet:\n", avg_macros)

# Top 5 protein recipes per diet
top_protein = df.sort_values("Protein(g)", ascending=False).groupby("Diet_type").head(5)
top_protein.to_csv("top_protein_recipes.csv")

# New ratios
df["Protein_to_Carbs_ratio"] = df["Protein(g)"] / df["Carbs(g)"]
df["Carbs_to_Fat_ratio"] = df["Carbs(g)"] / df["Fat(g)"]

df.to_csv("processed_data.csv", index=False)

# ---------------- VISUALIZATIONS ----------------

# Bar chart
avg_macros.plot(kind="bar")
plt.title("Average Macronutrients by Diet Type")
plt.ylabel("Grams")
plt.tight_layout()
plt.savefig("avg_macros_bar.png")
plt.show()

# Heatmap
sns.heatmap(avg_macros, annot=True, cmap="coolwarm")
plt.title("Heatmap of Macronutrients")
plt.tight_layout()
plt.savefig("heatmap.png")
plt.show()

# Scatter plot
sns.scatterplot(
    data=top_protein,
    x="Protein(g)",
    y="Carbs(g)",
    hue="Cuisine_type"
)
plt.title("Top Protein Recipes Scatter Plot")
plt.tight_layout()
plt.savefig("scatter.png")
plt.show()

print("\nAnalysis complete!")
