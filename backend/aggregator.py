import pandas as pd
import numpy as np


def grid_aggregation(df, lat_step=0.05, lon_step=0.05):
    if df.empty:
        return pd.DataFrame(), {}

    df = df.copy()

    df['lat_bin'] = np.floor(df['latitude'] / lat_step) * lat_step
    df['lon_bin'] = np.floor(df['longitude'] / lon_step) * lon_step

    df['lat_bin_center'] = df['lat_bin'] + lat_step / 2
    df['lon_bin_center'] = df['lon_bin'] + lon_step / 2

    point_count = df.groupby(['lat_bin', 'lon_bin']).agg(
        point_count=('call_sign', 'count'),
        ship_count=('call_sign', 'nunique'),
        avg_speed=('speed', 'mean'),
        avg_lat=('lat_bin_center', 'first'),
        avg_lon=('lon_bin_center', 'first')
    ).reset_index()

    ship_tracks = df.groupby('call_sign').agg(
        track_points=('call_sign', 'count'),
        min_lat=('latitude', 'min'),
        max_lat=('latitude', 'max'),
        min_lon=('longitude', 'min'),
        max_lon=('longitude', 'max'),
        avg_speed=('speed', 'mean')
    ).reset_index()

    trajectory_grid = []
    for call_sign, group in df.sort_values('timestamp').groupby('call_sign'):
        if len(group) < 2:
            continue
        coords = list(zip(group['lat_bin_center'], group['lon_bin_center']))
        seen = set()
        for i in range(len(coords) - 1):
            lat1, lon1 = coords[i]
            lat2, lon2 = coords[i + 1]
            seg_key = (min(lat1, lat2), min(lon1, lon2), max(lat1, lat2), max(lon1, lon2))
            if seg_key not in seen:
                seen.add(seg_key)
                trajectory_grid.append({
                    'lat1': lat1, 'lon1': lon1,
                    'lat2': lat2, 'lon2': lon2,
                    'call_sign': call_sign
                })

    trajectory_df = pd.DataFrame(trajectory_grid)
    if not trajectory_df.empty:
        trajectory_density = trajectory_df.groupby(['lat1', 'lon1', 'lat2', 'lon2']).agg(
            track_count=('call_sign', 'count'),
            ship_count=('call_sign', 'nunique')
        ).reset_index()
    else:
        trajectory_density = pd.DataFrame()

    meta = {
        'lat_step': lat_step,
        'lon_step': lon_step,
        'total_cells': len(point_count),
        'total_ships': df['call_sign'].nunique(),
        'total_points': len(df),
        'lat_range': [float(df['latitude'].min()), float(df['latitude'].max())],
        'lon_range': [float(df['longitude'].min()), float(df['longitude'].max())],
        'speed_range': [float(df['speed'].min()), float(df['speed'].max())] if 'speed' in df.columns and len(df) > 0 else [0, 0]
    }

    return point_count, trajectory_density, meta, ship_tracks


def grid_to_heatmap_data(point_count_df):
    if point_count_df.empty:
        return []

    max_count = point_count_df['point_count'].max() if 'point_count' in point_count_df.columns else 1
    heatmap_data = []
    for _, row in point_count_df.iterrows():
        value = int(row['point_count'])
        normalized = value / max_count if max_count > 0 else 0
        heatmap_data.append([
            float(row['avg_lon']),
            float(row['avg_lat']),
            value,
            round(normalized, 4),
            int(row.get('ship_count', 0)),
            round(float(row.get('avg_speed', 0)), 2)
        ])
    return heatmap_data


def grid_to_trajectory_lines(trajectory_density_df):
    if trajectory_density_df.empty:
        return []

    lines = []
    max_track = trajectory_density_df['track_count'].max() if 'track_count' in trajectory_density_df.columns else 1
    for _, row in trajectory_density_df.iterrows():
        count = int(row['track_count'])
        weight = 0.5 + (count / max_track) * 4.5 if max_track > 0 else 0.5
        lines.append({
            'coords': [
                [float(row['lon1']), float(row['lat1'])],
                [float(row['lon2']), float(row['lat2'])]
            ],
            'track_count': count,
            'ship_count': int(row.get('ship_count', 0)),
            'weight': round(weight, 2)
        })
    return lines
