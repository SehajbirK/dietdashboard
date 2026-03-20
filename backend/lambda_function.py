"""
Task 3 - Simulated Serverless Function

This script:
1. Connects to Azurite (local Azure Blob emulator)
2. Creates container if not exists
3. Uploads All_Diets.csv to Blob Storage
4. Downloads it again (simulating serverless trigger)
5. Calculates average macros per diet type
6. Saves results to JSON (simulated NoSQL)
"""

from azure.storage.blob import BlobServiceClient
import pandas as pd
import io
import json
import os

def process_data():

    print("Connecting to Azurite...")

    connect_str = "UseDevelopmentStorage=true"





    blob_service_client = BlobServiceClient.from_connection_string(connect_str)

    container_name = "datasets"
    blob_name = "All_Diets.csv"

    # Create container if it doesn't exist
    container_client = blob_service_client.get_container_client(container_name)
    try:
        container_client.create_container()
        print("Container created.")
    except:
        print("Container already exists.")

    # Upload file to Azurite
    with open("All_Diets.csv", "rb") as data:
        container_client.upload_blob(name=blob_name, data=data, overwrite=True)

    print("CSV uploaded to Azurite.")

    # Download file back from Azurite
    blob_client = container_client.get_blob_client(blob_name)
    stream = blob_client.download_blob().readall()

    df = pd.read_csv(io.BytesIO(stream))

    print("Rows loaded:", len(df))

    # Clean data
    df['Protein(g)'] = pd.to_numeric(df['Protein(g)'], errors='coerce')
    df['Carbs(g)'] = pd.to_numeric(df['Carbs(g)'], errors='coerce')
    df['Fat(g)'] = pd.to_numeric(df['Fat(g)'], errors='coerce')
    df.fillna(df.mean(numeric_only=True), inplace=True)

    # Calculate averages
    avg_macros = df.groupby('Diet_type')[['Protein(g)', 'Carbs(g)', 'Fat(g)']].mean()

    os.makedirs("simulated_nosql", exist_ok=True)

    result = avg_macros.reset_index().to_dict(orient='records')

    with open("simulated_nosql/results.json", "w") as f:
        json.dump(result, f, indent=4)

    print("Data processed and saved successfully.")

if __name__ == "__main__":
    process_data()
