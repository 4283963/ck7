import pandas as pd
import numpy as np
from math import radians, sin, cos, sqrt, atan2


def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


def clean_ais_data(df, max_speed_knots=50.0, speed_tolerance=1.5):
    if df.empty:
        return df

    required_cols = ['call_sign', 'latitude', 'longitude', 'speed', 'timestamp']
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"缺少必要列: {col}")

    df = df.copy()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values(['call_sign', 'timestamp']).reset_index(drop=True)

    valid_mask = pd.Series(True, index=df.index)

    max_speed_kmh = max_speed_knots * 1.852

    speed_col_valid = pd.to_numeric(df['speed'], errors='coerce').notna()
    valid_mask &= speed_col_valid
    df['speed'] = pd.to_numeric(df['speed'], errors='coerce')

    extreme_speed_mask = df['speed'] <= max_speed_knots * speed_tolerance
    valid_mask &= extreme_speed_mask

    for call_sign, group in df.groupby('call_sign'):
        if len(group) < 2:
            continue

        indices = group.index.values
        lats = group['latitude'].values
        lons = group['longitude'].values
        times = group['timestamp'].values
        speeds = group['speed'].values

        for i in range(1, len(indices)):
            if not valid_mask.iloc[indices[i]]:
                continue

            dt_hours = (times[i] - times[i - 1]).astype('timedelta64[ns]').astype(float) / 3.6e12
            if dt_hours <= 0:
                valid_mask.iloc[indices[i]] = False
                continue

            dist_km = haversine_distance(lats[i - 1], lons[i - 1], lats[i], lons[i])
            calc_speed_kmh = dist_km / dt_hours if dt_hours > 0 else 0
            calc_speed_knots = calc_speed_kmh / 1.852

            reported_speed = speeds[i] if pd.notna(speeds[i]) else 0
            expected_max = max(max_speed_knots, reported_speed * speed_tolerance)

            if calc_speed_knots > expected_max:
                valid_mask.iloc[indices[i]] = False

    cleaned_df = df[valid_mask].reset_index(drop=True)
    return cleaned_df


def get_cleaning_stats(original_df, cleaned_df):
    stats = {
        'original_count': len(original_df),
        'cleaned_count': len(cleaned_df),
        'removed_count': len(original_df) - len(cleaned_df),
        'removal_rate': (len(original_df) - len(cleaned_df)) / len(original_df) * 100 if len(original_df) > 0 else 0,
        'ships_original': original_df['call_sign'].nunique() if 'call_sign' in original_df.columns else 0,
        'ships_cleaned': cleaned_df['call_sign'].nunique() if 'call_sign' in cleaned_df.columns else 0
    }
    return stats
