import pandas as pd
import numpy as np
from math import radians, sin, cos, sqrt, atan2
import os


def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


def _validate_columns(df):
    required_cols = ['call_sign', 'latitude', 'longitude', 'speed', 'timestamp']
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"缺少必要列: {', '.join(missing)}")


def _clean_ship_group(group, max_speed_knots, speed_tolerance, prefix_point=None):
    """
    清洗单艘船的轨迹数据，只和上一个有效点比较位移速度。
    返回 (有效点列表, 最后一个有效点的dict 或 None)。
    """
    n = len(group)
    if n == 0 and prefix_point is None:
        return [], None

    valid_mask = [True] * n
    lats = group['latitude'].values
    lons = group['longitude'].values
    times = group['timestamp'].values
    speeds = group['speed'].values

    for i in range(n):
        if pd.isna(speeds[i]):
            valid_mask[i] = False
        elif speeds[i] > max_speed_knots * speed_tolerance:
            valid_mask[i] = False

    last_valid_lat = None
    last_valid_lon = None
    last_valid_time = None
    last_valid_speed = None

    if prefix_point is not None:
        last_valid_lat = prefix_point['latitude']
        last_valid_lon = prefix_point['longitude']
        last_valid_time = prefix_point['timestamp']
        last_valid_speed = prefix_point['speed']

    for i in range(n):
        if not valid_mask[i]:
            continue

        if last_valid_lat is None:
            last_valid_lat = lats[i]
            last_valid_lon = lons[i]
            last_valid_time = times[i]
            last_valid_speed = speeds[i]
            continue

        dt_hours = (times[i] - last_valid_time).astype('timedelta64[ns]').astype(float) / 3.6e12
        if dt_hours <= 0:
            valid_mask[i] = False
            continue

        dist_km = haversine_distance(last_valid_lat, last_valid_lon, lats[i], lons[i])
        calc_speed_kmh = dist_km / dt_hours
        calc_speed_knots = calc_speed_kmh / 1.852

        reported_speed = speeds[i] if pd.notna(speeds[i]) else 0
        expected_max = max(max_speed_knots, reported_speed * speed_tolerance)

        if calc_speed_knots > expected_max:
            valid_mask[i] = False
        else:
            last_valid_lat = lats[i]
            last_valid_lon = lons[i]
            last_valid_time = times[i]
            last_valid_speed = speeds[i]

    valid_indices = [i for i, v in enumerate(valid_mask) if v]
    valid_rows = group.iloc[valid_indices]

    last_point = None
    if len(valid_indices) > 0:
        last_idx = valid_indices[-1]
        last_point = {
            'call_sign': group['call_sign'].iloc[last_idx],
            'latitude': lats[last_idx],
            'longitude': lons[last_idx],
            'speed': speeds[last_idx],
            'timestamp': times[last_idx]
        }
    elif prefix_point is not None:
        last_point = prefix_point

    return valid_rows, last_point


def clean_ais_data(df, max_speed_knots=50.0, speed_tolerance=1.5):
    """
    全量清洗：整个 DataFrame 一次性加载到内存。
    适合小文件（< 50MB），速度快。
    """
    if df.empty:
        return df.copy()

    _validate_columns(df)

    df = df.copy()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['speed'] = pd.to_numeric(df['speed'], errors='coerce')
    df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
    df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')
    df = df.dropna(subset=['latitude', 'longitude', 'call_sign'])
    df = df.sort_values(['call_sign', 'timestamp']).reset_index(drop=True)

    original_count = len(df)

    all_valid = []
    for call_sign, group in df.groupby('call_sign', sort=False):
        group = group.sort_values('timestamp').reset_index(drop=True)
        valid_rows, _ = _clean_ship_group(group, max_speed_knots, speed_tolerance)
        all_valid.append(valid_rows)

    if all_valid:
        cleaned_df = pd.concat(all_valid, ignore_index=True)
    else:
        cleaned_df = pd.DataFrame(columns=df.columns)

    cleaned_df.attrs['original_count'] = original_count

    return cleaned_df


def clean_ais_data_stream(input_path, output_path, max_speed_knots=50.0,
                          speed_tolerance=1.5, chunksize=100000, encoding='utf-8-sig'):
    """
    流式分块清洗大文件。
    通过保留每艘船的最后一个有效点作为下一块的前缀，
    解决跨块相邻点的速度校验问题。
    内存占用 ≈ chunksize × 单行大小，与文件总大小无关。

    返回 stats 字典。
    """
    last_valid_points = {}
    original_count = 0
    cleaned_count = 0
    first_chunk = True
    all_call_signs = set()

    reader = pd.read_csv(input_path, encoding=encoding, chunksize=chunksize)

    for chunk in reader:
        _validate_columns(chunk)

        chunk['timestamp'] = pd.to_datetime(chunk['timestamp'])
        chunk['speed'] = pd.to_numeric(chunk['speed'], errors='coerce')
        chunk['latitude'] = pd.to_numeric(chunk['latitude'], errors='coerce')
        chunk['longitude'] = pd.to_numeric(chunk['longitude'], errors='coerce')
        chunk = chunk.dropna(subset=['latitude', 'longitude', 'call_sign'])
        chunk = chunk.sort_values(['call_sign', 'timestamp']).reset_index(drop=True)

        original_count += len(chunk)
        all_call_signs.update(chunk['call_sign'].unique())

        if len(chunk) == 0:
            continue

        cleaned_parts = []

        for call_sign, group in chunk.groupby('call_sign', sort=False):
            group = group.sort_values('timestamp').reset_index(drop=True)

            prefix = last_valid_points.get(call_sign)
            valid_rows, last_point = _clean_ship_group(
                group, max_speed_knots, speed_tolerance, prefix
            )

            if len(valid_rows) > 0:
                cleaned_parts.append(valid_rows)

            if last_point is not None:
                last_valid_points[call_sign] = last_point

        if cleaned_parts:
            cleaned_chunk = pd.concat(cleaned_parts, ignore_index=True)
            cleaned_count += len(cleaned_chunk)
            cleaned_chunk['timestamp'] = cleaned_chunk['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')

            cleaned_chunk.to_csv(
                output_path,
                mode='w' if first_chunk else 'a',
                header=first_chunk,
                index=False,
                encoding=encoding
            )
            first_chunk = False

    stats = {
        'original_count': original_count,
        'cleaned_count': cleaned_count,
        'removed_count': original_count - cleaned_count,
        'removal_rate': (original_count - cleaned_count) / original_count * 100 if original_count > 0 else 0,
        'ships_original': len(all_call_signs),
        'ships_cleaned': len(last_valid_points)
    }

    return stats


def get_cleaning_stats(original_df, cleaned_df):
    original_count = len(original_df)
    cleaned_count = len(cleaned_df)
    stats = {
        'original_count': original_count,
        'cleaned_count': cleaned_count,
        'removed_count': original_count - cleaned_count,
        'removal_rate': (original_count - cleaned_count) / original_count * 100 if original_count > 0 else 0,
        'ships_original': original_df['call_sign'].nunique() if 'call_sign' in original_df.columns else 0,
        'ships_cleaned': cleaned_df['call_sign'].nunique() if 'call_sign' in cleaned_df.columns else 0
    }
    return stats
