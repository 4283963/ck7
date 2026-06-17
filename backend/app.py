from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import pandas as pd
import os
from werkzeug.utils import secure_filename

from cleaner import clean_ais_data, get_cleaning_stats
from aggregator import grid_aggregation, grid_to_heatmap_data, grid_to_trajectory_lines

app = Flask(__name__, static_folder='../frontend', static_url_path='')
CORS(app)

UPLOAD_FOLDER = 'uploads'
SAMPLE_FOLDER = 'sample_data'
ALLOWED_EXTENSIONS = {'csv'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SAMPLE_FOLDER, exist_ok=True)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


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

    return jsonify({
        'success': True,
        'message': f'示例数据已生成，共 {len(df)} 条记录，{df["call_sign"].nunique()} 艘船舶',
        'filename': 'ais_sample.csv',
        'record_count': len(df),
        'ship_count': int(df['call_sign'].nunique())
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
    file.save(filepath)

    try:
        df = pd.read_csv(filepath, encoding='utf-8-sig')
        preview = df.head(10).to_dict('records')
        columns = list(df.columns)

        return jsonify({
            'success': True,
            'filename': filename,
            'columns': columns,
            'record_count': len(df),
            'preview': preview
        })
    except Exception as e:
        return jsonify({'success': False, 'error': f'文件读取失败: {str(e)}'}), 500


@app.route('/api/process', methods=['POST'])
def process_data():
    data = request.json or {}
    filename = data.get('filename')
    use_sample = data.get('use_sample', False)
    max_speed = float(data.get('max_speed', 50.0))
    lat_step = float(data.get('lat_step', 0.05))
    lon_step = float(data.get('lon_step', 0.05))

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

        df = pd.read_csv(filepath, encoding='utf-8-sig')

        cleaned_df = clean_ais_data(df, max_speed_knots=max_speed)
        stats = get_cleaning_stats(df, cleaned_df)

        point_count, traj_density, meta, ship_tracks = grid_aggregation(
            cleaned_df, lat_step=lat_step, lon_step=lon_step
        )

        heatmap_data = grid_to_heatmap_data(point_count)
        trajectory_lines = grid_to_trajectory_lines(traj_density)

        ships_info = []
        for _, row in ship_tracks.iterrows():
            ships_info.append({
                'call_sign': row['call_sign'],
                'track_points': int(row['track_points']),
                'lat_range': [round(float(row['min_lat']), 4), round(float(row['max_lat']), 4)],
                'lon_range': [round(float(row['min_lon']), 4), round(float(row['max_lon']), 4)],
                'avg_speed': round(float(row['avg_speed']), 2)
            })

        cleaned_csv = cleaned_df.to_csv(index=False, encoding='utf-8-sig')

        return jsonify({
            'success': True,
            'stats': stats,
            'meta': meta,
            'heatmap_data': heatmap_data,
            'trajectory_lines': trajectory_lines,
            'ships_info': ships_info,
            'cleaned_csv': cleaned_csv
        })

    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': f'处理失败: {str(e)}'}), 500


@app.route('/api/download-cleaned', methods=['POST'])
def download_cleaned():
    from flask import make_response
    data = request.json or {}
    csv_content = data.get('csv_content', '')

    if not csv_content:
        return jsonify({'success': False, 'error': '无数据可下载'}), 400

    response = make_response(csv_content)
    response.headers["Content-Disposition"] = "attachment; filename=ais_cleaned.csv"
    response.headers["Content-Type"] = "text/csv; charset=utf-8-sig"
    return response


if __name__ == '__main__':
    print("=" * 60)
    print("  AIS 轨迹数据清洗与可视化系统 - 后端服务")
    print("=" * 60)
    print("  访问地址: http://localhost:5001")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5001, debug=True)
