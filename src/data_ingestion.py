import os
import requests
import pandas as pd
from datetime import datetime
import argparse

ELECTRICITY_MAPS_API_URL = "https://api-access.electricitymaps.com/free-tier/carbon-intensity/history"

# Map paper regions to realistic Electricity Maps Zone Keys
REGION_MAPPING = {
    "US-West": "US-CAL-CISO", # California ISO (High solar)
    "EU-Central": "DE",       # Germany (Mixed renewables)
    "AS-East": "JP-TK"        # Tokyo (Fossil-dominated)
}

def fetch_carbon_intensity(zone: str, auth_token: str) -> pd.DataFrame:
    """
    Fetches historical carbon intensity data from Electricity Maps API.
    Note: Requires an Electricity Maps API free-tier token.
    """
    headers = {
        "auth-token": auth_token
    }
    params = {
        "zone": zone
    }
    
    response = requests.get(ELECTRICITY_MAPS_API_URL, headers=headers, params=params)
    response.raise_for_status()
    
    data = response.json()
    if 'history' not in data:
        raise ValueError(f"Invalid API response for zone {zone}")
        
    records = []
    for entry in data['history']:
        records.append({
            'datetime': entry['datetime'],
            'zone': entry['zone'],
            'carbon_intensity': entry['carbonIntensity'] # gCO2eq/kWh
        })
        
    df = pd.DataFrame(records)
    df['datetime'] = pd.to_datetime(df['datetime'])
    df.set_index('datetime', inplace=True)
    return df

def preprocess_and_interpolate(df: pd.DataFrame, target_interval_min: int = 5) -> pd.DataFrame:
    """
    Interpolates the hourly/15-min API data into the 5-min intervals used by SustainSched-MPC.
    """
    # Resample to 5-min intervals and linearly interpolate for missing slots
    if df.empty:
        return df
    
    # Needs to be sorted before resampling
    df = df.sort_index()
    resampled = df.resample(f'{target_interval_min}min').interpolate(method='linear')
    return resampled

def main(auth_token: str, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    print(f"Downloading historical Marginal Emission Factor (MEF) data to {output_dir}/...")
    
    for region_name, zone_id in REGION_MAPPING.items():
        print(f"Fetching data for Region: {region_name} (API Zone: {zone_id})...")
        try:
            df = fetch_carbon_intensity(zone_id, auth_token)
            df_interpolated = preprocess_and_interpolate(df)
            
            output_path = os.path.join(output_dir, f"{region_name}_carbon_intensity.csv")
            df_interpolated.to_csv(output_path)
            print(f" -> Saved {len(df_interpolated)} records to {output_path}")
            
        except Exception as e:
            print(f" -> Failed to fetch {region_name}: {str(e)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download and preprocess Electricity Maps carbon intensity data.")
    parser.add_argument("--token", type=str, required=True, help="Electricity Maps API Auth Token")
    parser.add_argument("--out", type=str, default="data/carbon", help="Output directory for CSV files")
    
    args = parser.parse_args()
    main(args.token, args.out)
