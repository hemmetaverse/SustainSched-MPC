import os
import requests
import pandas as pd
from datetime import datetime
import argparse
import numpy as np

ELECTRICITY_MAPS_API_URL = "https://api.electricitymaps.com/v3/carbon-intensity/past"

# Map paper regions to realistic Electricity Maps Zone Keys
REGION_MAPPING = {
    "US-West": "US-CAL-CISO", # California ISO (High solar)
    "EU-Central": "DE",       # Germany (Mixed renewables)
    "AS-East": "JP-TK"        # Tokyo (Fossil-dominated)
}

def fetch_carbon_intensity(zone: str, auth_token: str, hours: int = 24) -> pd.DataFrame:
    """
    Fetches historical carbon intensity data from Electricity Maps API v3/past endpoint.
    Pulls data for the past `hours` hours.
    """
    headers = {
        "auth-token": auth_token
    }
    
    records = []
    # Fetch data for the past `hours` hours
    now = pd.Timestamp.now('UTC')
    for h in range(hours):
        target_time = now - pd.Timedelta(hours=h)
        # format: YYYY-MM-DDTHH:MM
        time_str = target_time.strftime('%Y-%m-%dT%H:%M')
        
        params = {
            "zone": zone,
            "datetime": time_str
        }
        
        response = requests.get(ELECTRICITY_MAPS_API_URL, headers=headers, params=params)
        
        if response.status_code == 200:
            data = response.json()
            ci = data.get('carbonIntensity')
            try:
                ci = float(ci) if ci is not None else np.nan
            except (ValueError, TypeError):
                ci = np.nan
                
            records.append({
                'datetime': data.get('datetime'),
                'zone': data.get('zone'),
                'carbon_intensity': ci # gCO2eq/kWh
            })
        else:
            print(f"Failed to fetch {time_str} for {zone}: {response.status_code}")
            
    df = pd.DataFrame(records)
    if not df.empty:
        df['datetime'] = pd.to_datetime(df['datetime'])
        df.set_index('datetime', inplace=True)
        # Ensure carbon intensity column is float type
        df['carbon_intensity'] = pd.to_numeric(df['carbon_intensity'], errors='coerce')
        # If the whole column is nan, just return empty df or zeroed df
        if df['carbon_intensity'].isna().all():
            print("Warning: All carbon intensity values are NaN or missing.")
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
    # Ensure numerical structure before interpolating
    df['carbon_intensity'] = pd.to_numeric(df['carbon_intensity'], errors='coerce')
    
    # Drop string columns before interpolation
    if 'zone' in df.columns:
        zone_val = df['zone'].iloc[0] if not df.empty else "Unknown"
        df = df.drop(columns=['zone'])
        
    resampled = df.resample(f'{target_interval_min}min').interpolate(method='linear')
    
    # Re-add the zone column if needed
    resampled['zone'] = zone_val
    
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
