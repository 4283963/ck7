import pandas as pd
import numpy as np
from collections import defaultdict


def grid_aggregation(df, lat_step=0.05, lon_step=0.05):
    if df.empty:
        return pd.DataFrame(), pd.DataFrame(), {}, pd.DataFrame()

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
        prev_lat, prev_lon = coords[0]
        for i in range(1, len(coords)):
            lat2, lon2 = coords[i]
            if abs(prev_lat - lat2) < 1e-9 and abs(prev_lon - lon2) < 1e-9:
                continue
            lat_a = min(prev_lat, lat2)
            lon_a = min(prev_lon, lon2)
            lat_b = max(prev_lat, lat2)
            lon_b = max(prev_lon, lon2)
            trajectory_grid.append({
                'lat1': lat_a, 'lon1': lon_a,
                'lat2': lat_b, 'lon2': lon_b,
                'call_sign': call_sign
            })
            prev_lat, prev_lon = lat2, lon2

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


def grid_aggregation_stream(input_path, lat_step=0.05, lon_step=0.05,
                            chunksize=100000, encoding='utf-8-sig'):
    """
    流式分块聚合大文件。
    使用 dict 增量维护格子统计、航线段统计、船舶统计，
    内存占用与文件总大小无关，只与格子数和船舶数成正比。
    """
    cell_stats = defaultdict(lambda: {
        'point_count': 0,
        'ship_set': set(),
        'speed_sum': 0.0,
        'speed_count': 0
    })

    ship_stats = defaultdict(lambda: {
        'track_points': 0,
        'min_lat': float('inf'),
        'max_lat': float('-inf'),
        'min_lon': float('inf'),
        'max_lon': float('-inf'),
        'speed_sum': 0.0,
        'speed_count': 0
    })

    trajectory_counts = defaultdict(lambda: {'track_count': 0, 'ship_set': set()})

    ship_last_cell = {}

    min_lat = float('inf')
    max_lat = float('-inf')
    min_lon = float('inf')
    max_lon = float('-inf')
    min_speed = float('inf')
    max_speed = float('-inf')
    total_points = 0
    total_ships_set = set()

    reader = pd.read_csv(input_path, encoding=encoding, chunksize=chunksize)

    for chunk in reader:
        chunk['timestamp'] = pd.to_datetime(chunk['timestamp'])
        chunk['speed'] = pd.to_numeric(chunk['speed'], errors='coerce')
        chunk['latitude'] = pd.to_numeric(chunk['latitude'], errors='coerce')
        chunk['longitude'] = pd.to_numeric(chunk['longitude'], errors='coerce')
        chunk = chunk.dropna(subset=['latitude', 'longitude', 'speed', 'call_sign'])

        if len(chunk) == 0:
            continue

        chunk = chunk.sort_values(['call_sign', 'timestamp']).reset_index(drop=True)

        chunk['lat_bin'] = np.floor(chunk['latitude'] / lat_step) * lat_step
        chunk['lon_bin'] = np.floor(chunk['longitude'] / lon_step) * lon_step
        chunk['lat_center'] = chunk['lat_bin'] + lat_step / 2
        chunk['lon_center'] = chunk['lon_bin'] + lon_step / 2

        lats = chunk['latitude'].values
        lons = chunk['longitude'].values
        speeds = chunk['speed'].values
        call_signs = chunk['call_sign'].values
        lat_centers = chunk['lat_center'].values
        lon_centers = chunk['lon_center'].values
        lat_bins = chunk['lat_bin'].values
        lon_bins = chunk['lon_bin'].values

        min_lat = min(min_lat, float(np.min(lats)))
        max_lat = max(max_lat, float(np.max(lats)))
        min_lon = min(min_lon, float(np.min(lons)))
        max_lon = max(max_lon, float(np.max(lons)))
        min_speed = min(min_speed, float(np.min(speeds)))
        max_speed = max(max_speed, float(np.max(speeds)))
        total_points += len(chunk)

        for i in range(len(chunk)):
            cs = call_signs[i]
            lb = lat_bins[i]
            lob = lon_bins[i]
            latc = lat_centers[i]
            lonc = lon_centers[i]
            sp = speeds[i]
            lat = lats[i]
            lon = lons[i]

            key = (lb, lob)
            cell = cell_stats[key]
            cell['point_count'] += 1
            cell['ship_set'].add(cs)
            cell['speed_sum'] += sp
            cell['speed_count'] += 1
            cell['avg_lat'] = latc
            cell['avg_lon'] = lonc

            ss = ship_stats[cs]
            ss['track_points'] += 1
            ss['min_lat'] = min(ss['min_lat'], lat)
            ss['max_lat'] = max(ss['max_lat'], lat)
            ss['min_lon'] = min(ss['min_lon'], lon)
            ss['max_lon'] = max(ss['max_lon'], lon)
            ss['speed_sum'] += sp
            ss['speed_count'] += 1

            total_ships_set.add(cs)

            if cs in ship_last_cell:
                prev_latc, prev_lonc = ship_last_cell[cs]
                if not (abs(prev_latc - latc) < 1e-9 and abs(prev_lonc - lonc) < 1e-9):
                    seg_key = (
                        min(prev_latc, latc),
                        min(prev_lonc, lonc),
                        max(prev_latc, latc),
                        max(prev_lonc, lonc)
                    )
                    seg = trajectory_counts[seg_key]
                    seg['track_count'] += 1
                    seg['ship_set'].add(cs)
                    seg['lat1'] = prev_latc
                    seg['lon1'] = prev_lonc
                    seg['lat2'] = latc
                    seg['lon2'] = lonc

            ship_last_cell[cs] = (latc, lonc)

    point_count_list = []
    for (lb, lob), cell in cell_stats.items():
        point_count_list.append({
            'lat_bin': lb,
            'lon_bin': lob,
            'point_count': cell['point_count'],
            'ship_count': len(cell['ship_set']),
            'avg_speed': cell['speed_sum'] / cell['speed_count'] if cell['speed_count'] > 0 else 0,
            'avg_lat': cell.get('avg_lat', lb + lat_step / 2),
            'avg_lon': cell.get('avg_lon', lob + lon_step / 2)
        })

    trajectory_list = []
    for key, seg in trajectory_counts.items():
        trajectory_list.append({
            'lat1': seg.get('lat1', key[0]),
            'lon1': seg.get('lon1', key[1]),
            'lat2': seg.get('lat2', key[2]),
            'lon2': seg.get('lon2', key[3]),
            'track_count': seg['track_count'],
            'ship_count': len(seg['ship_set'])
        })

    ships_list = []
    for cs, ss in ship_stats.items():
        ships_list.append({
            'call_sign': cs,
            'track_points': ss['track_points'],
            'min_lat': ss['min_lat'],
            'max_lat': ss['max_lat'],
            'min_lon': ss['min_lon'],
            'max_lon': ss['max_lon'],
            'avg_speed': ss['speed_sum'] / ss['speed_count'] if ss['speed_count'] > 0 else 0
        })

    meta = {
        'lat_step': lat_step,
        'lon_step': lon_step,
        'total_cells': len(cell_stats),
        'total_ships': len(total_ships_set),
        'total_points': total_points,
        'lat_range': [min_lat if min_lat != float('inf') else 0, max_lat if max_lat != float('-inf') else 0],
        'lon_range': [min_lon if min_lon != float('inf') else 0, max_lon if max_lon != float('-inf') else 0],
        'speed_range': [min_speed if min_speed != float('inf') else 0, max_speed if max_speed != float('-inf') else 0]
    }

    return point_count_list, trajectory_list, meta, ships_list


def grid_to_heatmap_data(point_count_df):
    if isinstance(point_count_df, list):
        point_list = point_count_df
    else:
        if point_count_df.empty:
            return []
        point_list = point_count_df.to_dict('records')

    if len(point_list) == 0:
        return []

    if isinstance(point_list[0], dict):
        max_count = max(p.get('point_count', 0) for p in point_list)
    else:
        max_count = 1

    heatmap_data = []
    for row in point_list:
        if isinstance(row, dict):
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
        else:
            heatmap_data.append(row)

    return heatmap_data


def grid_to_trajectory_lines(trajectory_density_df):
    if isinstance(trajectory_density_df, list):
        traj_list = trajectory_density_df
    else:
        if trajectory_density_df.empty:
            return []
        traj_list = trajectory_density_df.to_dict('records')

    if len(traj_list) == 0:
        return []

    if isinstance(traj_list[0], dict):
        max_track = max(t.get('track_count', 0) for t in traj_list)
    else:
        max_track = 1

    lines = []
    for row in traj_list:
        if isinstance(row, dict):
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
        else:
            lines.append(row)

    return lines
