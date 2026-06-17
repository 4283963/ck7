from flask import Flask, request, jsonify, send_from_directory, send_file, abort
from flask_cors import CORS
import pandas as pd
import os
import gc
import uuid
from werkzeug.utils import secure_filename

from cleaner import clean_ais_data, get_cleaning_stats, clean_ais_data_stream
from aggregator import (
    grid_aggregation, grid_aggregation_stream,
    grid_to_heatmap_data, grid_to_trajectory_lines,
    detect_illegal_anchorage, detect_illegal_anchorage_stream
)

app = Flask(__name__, static_folder='../frontend', static_url_path='')
CORS(app)

MAX_CONTENT_LENGTH = 500 * 1024 * 1024
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

UPLOAD_FOLDER = 'uploads'
SAMPLE_FOLDER = 'sample_data'
CLEANED_FOLDER = 'cleaned'
ALLOWED_EXTENSIONS = {'csv'}
STREAM_THRESHOLD_MB = 50

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['CLEANED_FOLDER'] = CLEANED_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SAMPLE_FOLDER, exist_ok=True)
os.makedirs(CLEANED_FOLDER, exist_ok=True)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_file_size_mb(filepath):
    if not os.path.exists(filepath):
        return 0
    return os.path.getsize(filepath) / (1024 * 1024)


def should_use_stream(filepath):
    return get_file_size_mb(filepath) > STREAM_THRESHOLD_MB


def stream_save_file(file_storage, filepath):
    """流式保存上传文件，避免大文件一次性加载到内存。"""
    chunk_size = 1024 * 1024
    with open(filepath, 'wb') as f:
        while True:
            chunk = file_storage.read(chunk_size)
            if not chunk:
                break
            f.write(chunk)


@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({
        'success': False,
        'error': f'文件过大，最大支持 {MAX_CONTENT_LENGTH // (1024*1024)} MB'
    }), 413


@app.errorhandler(MemoryError)
def memory_error_handler(error):
    return jsonify({
        'success': False,
        'error': '服务器内存不足，请使用较小的文件或增加服务器内存'
    }), 500


@app.route('/')
def index():
    return send_from_directory('../frontend', 'index.html')


@app.route('/api/sample-data', methods=['POST'])
def generate_sample_data():
    import numpy as np
    from datetime import datetime, timedelta

    np.random.seed(42)

    ship_names = [f'BOAT{i:03d}' for i in range(1, 16)]
    routes = [
        {'lat': 30.0, 'lon': 121.0, 'dst_lat': 31.5, 'dst_lon': 122.5},
        {'lat': 29.5, 'lon': 122.0, 'dst_lat': 32.0, 'dst_lon': 121.5},
        {'lat': 31.0, 'lon': 120.5, 'dst_lat': 30.0, 'dst_lon': 123.0},
        {'lat': 29.0, 'lon': 121.5, 'dst_lat': 32.5, 'dst_lon': 122.0},
    ]

    illegal_anchorage_ships = {
        'BOAT005': {'lat': 30.50, 'lon': 121.45, 'duration_hours': 5.5},
        'BOAT010': {'lat': 30.20, 'lon': 121.80, 'duration_hours': 4.0},
        'BOAT012': {'lat': 31.10, 'lon': 122.30, 'duration_hours': 6.5},
    }

    records = []
    start_time = datetime(2025, 6, 1, 0, 0, 0)

    for ship_idx, call_sign in enumerate(ship_names):
        route = routes[ship_idx % len(routes)]
        num_points = np.random.randint(40, 80)
        base_time = start_time + timedelta(minutes=np.random.randint(0, 180))

        lats = np.linspace(route['lat'], route['dst_lat'], num_points)
        lons = np.linspace(route['lon'], route['dst_lon'], num_points)

        lats += np.random.normal(0, 0.02, num_points)
        lons += np.random.normal(0, 0.02, num_points)

        base_speed = np.random.uniform(10, 25)
        speeds = base_speed + np.random.normal(0, 3, num_points)
        speeds = np.clip(speeds, 2, 40)

        for i in range(num_points):
            ts = base_time + timedelta(minutes=i * 15 + np.random.randint(-3, 3))
            records.append({
                'call_sign': call_sign,
                'latitude': round(lats[i], 6),
                'longitude': round(lons[i], 6),
                'speed': round(speeds[i], 2),
                'heading': round(np.random.uniform(0, 360), 1),
                'timestamp': ts.strftime('%Y-%m-%d %H:%M:%S')
            })

        if call_sign in illegal_anchorage_ships:
            anchor_info = illegal_anchorage_ships[call_sign]
            duration = anchor_info['duration_hours']
            num_anchor_points = int(duration * 4)

            mid_idx = num_points // 2
            anchor_lat = lats[mid_idx] + np.random.normal(0, 0.01)
            anchor_lon = lons[mid_idx] + np.random.normal(0, 0.01)
            anchor_start_time = base_time + timedelta(minutes=mid_idx * 15)

            for i in range(num_anchor_points):
                drift_lat = anchor_lat + np.random.normal(0, 0.002)
                drift_lon = anchor_lon + np.random.normal(0, 0.002)
                anchor_speed = np.random.uniform(0.1, 0.4)
                ts = anchor_start_time + timedelta(minutes=i * 15)
                records.append({
                    'call_sign': call_sign,
                    'latitude': round(drift_lat, 6),
                    'longitude': round(drift_lon, 6),
                    'speed': round(anchor_speed, 2),
                    'heading': round(np.random.uniform(0, 360), 1),
                    'timestamp': ts.strftime('%Y-%m-%d %H:%M:%S')
                })

        num_drift = np.random.randint(2, 6)
        for _ in range(num_drift):
            drift_idx = np.random.randint(0, num_points)
            drift_lat = lats[drift_idx] + np.random.choice([-1, 1]) * np.random.uniform(0.3, 0.8)
            drift_lon = lons[drift_idx] + np.random.choice([-1, 1]) * np.random.uniform(0.3, 0.8)
            drift_speed = np.random.uniform(80, 200)
            drift_ts = base_time + timedelta(minutes=drift_idx * 15 + np.random.randint(-2, 2))
            records.append({
                'call_sign': call_sign,
                'latitude': round(drift_lat, 6),
                'longitude': round(drift_lon, 6),
                'speed': round(drift_speed, 2),
                'heading': round(np.random.uniform(0, 360), 1),
                'timestamp': drift_ts.strftime('%Y-%m-%d %H:%M:%S')
            })

    df = pd.DataFrame(records)
    sample_path = os.path.join(SAMPLE_FOLDER, 'ais_sample.csv')
    df.to_csv(sample_path, index=False, encoding='utf-8-sig')
    record_count = len(df)
    ship_count = df['call_sign'].nunique()
    del df
    del records
    gc.collect()

    return jsonify({
        'success': True,
        'message': f'示例数据已生成，共 {record_count} 条记录，{ship_count} 艘船舶',
        'filename': 'ais_sample.csv',
        'record_count': record_count,
        'ship_count': int(ship_count)
    })


@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': '未找到上传文件'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': '未选择文件'}), 400

    if not allowed_file(file.filename):
        return jsonify({'success': False, 'error': '仅支持 CSV 文件'}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)

    try:
        stream_save_file(file, filepath)
    except MemoryError:
        return jsonify({'success': False, 'error': '内存不足，文件保存失败'}), 500

    try:
        df_head = pd.read_csv(filepath, encoding='utf-8-sig', nrows=10)
        columns = list(df_head.columns)
        preview = df_head.to_dict('records')

        file_size_mb = get_file_size_mb(filepath)

        return jsonify({
            'success': True,
            'filename': filename,
            'columns': columns,
            'file_size_mb': round(file_size_mb, 2),
            'preview': preview,
            'will_stream_process': file_size_mb > STREAM_THRESHOLD_MB
        })
    except Exception as e:
        if os.path.exists(filepath):
            os.remove(filepath)
        return jsonify({'success': False, 'error': f'文件读取失败: {str(e)}'}), 500


@app.route('/api/process', methods=['POST'])
def process_data():
    data = request.json or {}
    filename = data.get('filename')
    use_sample = data.get('use_sample', False)
    max_speed = float(data.get('max_speed', 50.0))
    lat_step = float(data.get('lat_step', 0.05))
    lon_step = float(data.get('lon_step', 0.05))
    chunksize = int(data.get('chunksize', 100000))

    cleaned_id = str(uuid.uuid4())[:8]
    cleaned_path = os.path.join(app.config['CLEANED_FOLDER'], f'cleaned_{cleaned_id}.csv')

    try:
        if use_sample:
            filepath = os.path.join(SAMPLE_FOLDER, 'ais_sample.csv')
            if not os.path.exists(filepath):
                return jsonify({'success': False, 'error': '示例数据不存在，请先生成'}), 400
        else:
            if not filename:
                return jsonify({'success': False, 'error': '缺少文件名参数'}), 400
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(filename))

        if not os.path.exists(filepath):
            return jsonify({'success': False, 'error': f'文件不存在: {filename}'}), 404

        file_size_mb = get_file_size_mb(filepath)
        use_stream = file_size_mb > STREAM_THRESHOLD_MB

        if use_stream:
            stats = clean_ais_data_stream(
                filepath, cleaned_path,
                max_speed_knots=max_speed,
                chunksize=chunksize
            )

            point_count_list, traj_list, meta, ships_list = grid_aggregation_stream(
                cleaned_path,
                lat_step=lat_step, lon_step=lon_step,
                chunksize=chunksize
            )

            heatmap_data = grid_to_heatmap_data(point_count_list)
            trajectory_lines = grid_to_trajectory_lines(traj_list)

            suspects = detect_illegal_anchorage_stream(
                cleaned_path,
                speed_threshold=0.5,
                min_duration_hours=3.0,
                chunksize=chunksize
            )

            ships_info = [
                {
                    'call_sign': s['call_sign'],
                    'track_points': int(s['track_points']),
                    'lat_range': [round(float(s['min_lat']), 4), round(float(s['max_lat']), 4)],
                    'lon_range': [round(float(s['min_lon']), 4), round(float(s['max_lon']), 4)],
                    'avg_speed': round(float(s['avg_speed']), 2)
                }
                for s in ships_list
            ]

            gc.collect()

            return jsonify({
                'success': True,
                'stats': stats,
                'meta': meta,
                'heatmap_data': heatmap_data,
                'trajectory_lines': trajectory_lines,
                'ships_info': ships_info,
                'suspect_ships': suspects,
                'cleaned_id': cleaned_id,
                'used_stream': True,
                'file_size_mb': round(file_size_mb, 2)
            })

        else:
            df = pd.read_csv(filepath, encoding='utf-8-sig')

            cleaned_df = clean_ais_data(df, max_speed_knots=max_speed)
            stats = get_cleaning_stats(df, cleaned_df)

            point_count, traj_density, meta, ship_tracks = grid_aggregation(
                cleaned_df, lat_step=lat_step, lon_step=lon_step
            )

            heatmap_data = grid_to_heatmap_data(point_count)
            trajectory_lines = grid_to_trajectory_lines(traj_density)

            suspects = detect_illegal_anchorage(
                cleaned_df,
                speed_threshold=0.5,
                min_duration_hours=3.0
            )

            ships_info = []
            for _, row in ship_tracks.iterrows():
                ships_info.append({
                    'call_sign': row['call_sign'],
                    'track_points': int(row['track_points']),
                    'lat_range': [round(float(row['min_lat']), 4), round(float(row['max_lat']), 4)],
                    'lon_range': [round(float(row['min_lon']), 4), round(float(row['max_lon']), 4)],
                    'avg_speed': round(float(row['avg_speed']), 2)
                })

            cleaned_df.to_csv(cleaned_path, index=False, encoding='utf-8-sig')

            del df, cleaned_df, point_count, traj_density, ship_tracks
            gc.collect()

            return jsonify({
                'success': True,
                'stats': stats,
                'meta': meta,
                'heatmap_data': heatmap_data,
                'trajectory_lines': trajectory_lines,
                'ships_info': ships_info,
                'suspect_ships': suspects,
                'cleaned_id': cleaned_id,
                'used_stream': False,
                'file_size_mb': round(file_size_mb, 2)
            })

    except MemoryError:
        if os.path.exists(cleaned_path):
            try:
                os.remove(cleaned_path)
            except:
                pass
        gc.collect()
        return jsonify({
            'success': False,
            'error': '内存不足，处理中断。请尝试使用更小的文件或增大 chunksize 分块处理。'
        }), 500
    except ValueError as e:
        if os.path.exists(cleaned_path):
            try:
                os.remove(cleaned_path)
            except:
                pass
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        if os.path.exists(cleaned_path):
            try:
                os.remove(cleaned_path)
            except:
                pass
        return jsonify({'success': False, 'error': f'处理失败: {str(e)}'}), 500


@app.route('/api/download-cleaned/<cleaned_id>', methods=['GET'])
def download_cleaned(cleaned_id):
    import re

    if not re.match(r'^[a-f0-9]{8}$', cleaned_id):
        return jsonify({'success': False, 'error': '无效的文件ID'}), 400

    filename = f'cleaned_{cleaned_id}.csv'
    filepath = os.path.join(app.config['CLEANED_FOLDER'], filename)

    if not os.path.exists(filepath):
        return jsonify({'success': False, 'error': '清洗结果文件不存在或已过期'}), 404

    try:
        return send_file(
            filepath,
            mimetype='text/csv; charset=utf-8-sig',
            as_attachment=True,
            download_name='ais_cleaned.csv'
        )
    except Exception as e:
        return jsonify({'success': False, 'error': f'下载失败: {str(e)}'}), 500


@app.route('/api/file-info', methods=['POST'])
def get_file_info():
    data = request.json or {}
    filename = data.get('filename')
    use_sample = data.get('use_sample', False)

    try:
        if use_sample:
            filepath = os.path.join(SAMPLE_FOLDER, 'ais_sample.csv')
        else:
            if not filename:
                return jsonify({'success': False, 'error': '缺少文件名'}), 400
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(filename))

        if not os.path.exists(filepath):
            return jsonify({'success': False, 'error': '文件不存在'}), 404

        file_size_mb = get_file_size_mb(filepath)

        df_head = pd.read_csv(filepath, encoding='utf-8-sig', nrows=1)
        columns = list(df_head.columns)

        return jsonify({
            'success': True,
            'file_size_mb': round(file_size_mb, 2),
            'columns': columns,
            'will_stream_process': file_size_mb > STREAM_THRESHOLD_MB,
            'stream_threshold_mb': STREAM_THRESHOLD_MB
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    print("=" * 60)
    print("  AIS 轨迹数据清洗与可视化系统 - 后端服务")
    print("=" * 60)
    print(f"  访问地址: http://localhost:5001")
    print(f"  最大上传文件: {MAX_CONTENT_LENGTH // (1024*1024)} MB")
    print(f"  流式处理阈值: {STREAM_THRESHOLD_MB} MB")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5001, debug=True)
