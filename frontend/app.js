const API_BASE = '';

let state = {
    currentFile: null,
    useSample: false,
    heatmapData: [],
    trajectoryLines: [],
    shipsInfo: [],
    stats: null,
    meta: null,
    cleanedCsv: null,
    chart: null
};

function $(id) { return document.getElementById(id); }

function showLoading(text = '处理中...') {
    $('loadingText').textContent = text;
    $('loadingOverlay').classList.remove('hidden');
}

function hideLoading() {
    $('loadingOverlay').classList.add('hidden');
}

function setStatus(msg, type = 'info') {
    const el = $('dataStatus');
    el.className = `status-box status-${type}`;
    el.textContent = msg;
}

function initChart() {
    const dom = $('mainChart');
    state.chart = echarts.init(dom, 'dark');
    window.addEventListener('resize', () => state.chart && state.chart.resize());
    renderEmptyChart();
}

function renderEmptyChart() {
    if (!state.chart) return;
    state.chart.setOption({
        backgroundColor: 'transparent',
        title: {
            text: '等待数据加载...',
            subtext: '请先生成示例数据或上传 CSV 文件',
            left: 'center',
            top: 'center',
            textStyle: { color: '#7ed8ff', fontSize: 20 },
            subtextStyle: { color: '#90b0d0', fontSize: 14 }
        }
    });
}

function buildChartOption() {
    if (!state.meta) return {};

    const latRange = state.meta.lat_range;
    const lonRange = state.meta.lon_range;
    const latPad = (latRange[1] - latRange[0]) * 0.1 || 0.5;
    const lonPad = (lonRange[1] - lonRange[0]) * 0.1 || 0.5;

    const showHeatmap = $('showHeatmap').checked;
    const showTrajectories = $('showTrajectories').checked;
    const showScatter = $('showScatter').checked;
    const dimension = $('heatmapDimension').value;

    const series = [];

    if (showTrajectories && state.trajectoryLines.length > 0) {
        const linesData = state.trajectoryLines.map(l => ({
            coords: l.coords,
            lineStyle: {
                width: l.weight,
                opacity: Math.min(0.3 + l.track_count * 0.05, 0.8)
            }
        }));

        series.push({
            name: '航线轨迹',
            type: 'lines',
            coordinateSystem: 'cartesian2d',
            polyline: false,
            effect: {
                show: true,
                period: 6,
                trailLength: 0.2,
                symbol: 'arrow',
                symbolSize: 6,
                color: '#7ed8ff'
            },
            lineStyle: {
                color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
                    { offset: 0, color: '#00c8ff' },
                    { offset: 1, color: '#0080ff' }
                ]),
                width: 1.5,
                opacity: 0.5,
                curveness: 0.15
            },
            data: linesData,
            zlevel: 2
        });
    }

    if (showHeatmap && state.heatmapData.length > 0) {
        let data;
        if (dimension === 'ship_count') {
            data = state.heatmapData.map(d => [d[0], d[1], d[4]]);
        } else if (dimension === 'avg_speed') {
            data = state.heatmapData.map(d => [d[0], d[1], d[5]]);
        } else {
            data = state.heatmapData.map(d => [d[0], d[1], d[2]]);
        }

        series.push({
            name: '密度热力图',
            type: 'heatmap',
            coordinateSystem: 'cartesian2d',
            data: data,
            pointSize: Math.max(6, 20 * (state.meta.lat_step || 0.05) / 0.05),
            blurSize: 20,
            minOpacity: 0.15,
            maxOpacity: 0.9,
            emphasis: {
                itemStyle: {
                    borderColor: '#fff',
                    borderWidth: 1,
                    shadowBlur: 10,
                    shadowColor: 'rgba(255, 255, 255, 0.5)'
                }
            },
            zlevel: 3
        });
    }

    if (showScatter && state.heatmapData.length > 0) {
        const scatterData = state.heatmapData
            .filter(d => d[2] > 1)
            .map(d => ({
                value: [d[0], d[1], d[2]],
                symbolSize: Math.min(8 + d[2] * 0.3, 22)
            }));

        series.push({
            name: '船舶散点',
            type: 'scatter',
            coordinateSystem: 'cartesian2d',
            data: scatterData,
            symbolSize: d => d.symbolSize || 8,
            itemStyle: {
                color: '#ffcc00',
                shadowBlur: 6,
                shadowColor: 'rgba(255, 200, 0, 0.6)'
            },
            zlevel: 4
        });
    }

    const dimLabel = {
        'point_count': '轨迹点密度',
        'ship_count': '船舶数量',
        'avg_speed': '平均航速(节)'
    }[dimension];

    return {
        backgroundColor: 'transparent',
        title: {
            text: '🚢 船舶航道拥堵热力图',
            subtext: `${dimLabel} · 海域格子 ${state.meta.lat_step}° × ${state.meta.lon_step}°`,
            left: 'left',
            top: 10,
            textStyle: { color: '#7ed8ff', fontSize: 17, fontWeight: 600 },
            subtextStyle: { color: '#90b0d0', fontSize: 12 }
        },
        tooltip: {
            trigger: 'item',
            backgroundColor: 'rgba(10, 30, 60, 0.95)',
            borderColor: 'rgba(0, 180, 255, 0.4)',
            textStyle: { color: '#e0e8f0' },
            formatter: function (params) {
                if (params.seriesType === 'heatmap' || params.seriesType === 'scatter') {
                    const d = params.value;
                    const orig = state.heatmapData.find(
                        x => Math.abs(x[0] - d[0]) < 0.0001 && Math.abs(x[1] - d[1]) < 0.0001
                    );
                    if (orig) {
                        return `
                            <strong style="color:#7ed8ff">📍 海域格子</strong><br/>
                            经度: ${d[0].toFixed(4)}°<br/>
                            纬度: ${d[1].toFixed(4)}°<br/>
                            <hr style="border-color:rgba(0,180,255,0.2);margin:6px 0"/>
                            轨迹点数: <strong>${orig[2]}</strong><br/>
                            经过船舶: <strong style="color:#70e0a0">${orig[4]}</strong> 艘<br/>
                            平均航速: <strong style="color:#ffcc00">${orig[5]}</strong> 节
                        `;
                    }
                    return `经度: ${d[0].toFixed(4)}°<br/>纬度: ${d[1].toFixed(4)}°<br/>值: ${d[2]}`;
                }
                if (params.seriesType === 'lines') {
                    const data = params.data;
                    if (data && data.coords) {
                        return `<strong style="color:#7ed8ff">🛤️ 航线段</strong><br/>
                            起点: ${data.coords[0][0].toFixed(3)}°, ${data.coords[0][1].toFixed(3)}°<br/>
                            终点: ${data.coords[1][0].toFixed(3)}°, ${data.coords[1][1].toFixed(3)}°`;
                    }
                }
                return '';
            }
        },
        grid: {
            left: 60,
            right: 80,
            top: 60,
            bottom: 50
        },
        xAxis: {
            type: 'value',
            name: '经度 (°E)',
            nameLocation: 'middle',
            nameGap: 30,
            nameTextStyle: { color: '#90b0d0', fontSize: 12 },
            min: lonRange[0] - lonPad,
            max: lonRange[1] + lonPad,
            axisLine: { lineStyle: { color: 'rgba(0, 180, 255, 0.3)' } },
            axisLabel: { color: '#90b0d0', formatter: v => v.toFixed(2) },
            splitLine: { lineStyle: { color: 'rgba(0, 180, 255, 0.06)' } }
        },
        yAxis: {
            type: 'value',
            name: '纬度 (°N)',
            nameLocation: 'middle',
            nameGap: 45,
            nameTextStyle: { color: '#90b0d0', fontSize: 12 },
            min: latRange[0] - latPad,
            max: latRange[1] + latPad,
            axisLine: { lineStyle: { color: 'rgba(0, 180, 255, 0.3)' } },
            axisLabel: { color: '#90b0d0', formatter: v => v.toFixed(2) },
            splitLine: { lineStyle: { color: 'rgba(0, 180, 255, 0.06)' } }
        },
        visualMap: {
            type: 'continuous',
            min: 0,
            calculable: true,
            orient: 'vertical',
            right: 10,
            top: 'center',
            itemWidth: 12,
            itemHeight: 160,
            textStyle: { color: '#90b0d0' },
            dimension: dimension === 'point_count' ? 2 : (dimension === 'ship_count' ? 2 : 2),
            inRange: {
                color: [
                    '#003366',
                    '#0066cc',
                    '#00aaff',
                    '#33ffcc',
                    '#99ff66',
                    '#ffee00',
                    '#ff9900',
                    '#ff3300',
                    '#cc0000'
                ]
            },
            outOfRange: { color: '#334455' },
            text: ['高', '低']
        },
        series: series
    };
}

function renderChart() {
    if (!state.chart || !state.meta) return;
    state.chart.setOption(buildChartOption(), true);
}

async function generateSample() {
    showLoading('正在生成示例 AIS 数据...');
    try {
        const res = await fetch(`${API_BASE}/api/sample-data`, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            state.currentFile = data.filename;
            state.useSample = true;
            setStatus(`✅ 示例数据就绪: ${data.record_count} 条记录 · ${data.ship_count} 艘船舶`, 'ok');
            $('btnProcess').disabled = false;
        } else {
            setStatus(`❌ ${data.error || '生成失败'}`, 'error');
        }
    } catch (e) {
        setStatus(`❌ 请求失败: ${e.message}`, 'error');
    } finally {
        hideLoading();
    }
}

function handleFileUpload(e) {
    const file = e.target.files[0];
    if (!file) return;

    showLoading('正在上传并解析 CSV...');
    const formData = new FormData();
    formData.append('file', file);

    fetch(`${API_BASE}/api/upload`, { method: 'POST', body: formData })
        .then(r => r.json())
        .then(data => {
            hideLoading();
            if (data.success) {
                state.currentFile = data.filename;
                state.useSample = false;
                setStatus(
                    `✅ 上传成功: ${data.filename} · ${data.record_count} 条记录 · 列: ${data.columns.join(', ')}`,
                    'ok'
                );
                $('btnProcess').disabled = false;
            } else {
                setStatus(`❌ ${data.error || '上传失败'}`, 'error');
            }
        })
        .catch(e => {
            hideLoading();
            setStatus(`❌ 请求失败: ${e.message}`, 'error');
        });
}

async function processData() {
    if (!state.currentFile && !state.useSample) {
        setStatus('⚠️ 请先加载数据', 'error');
        return;
    }

    showLoading('正在执行数据清洗与海域聚合...');

    const payload = {
        filename: state.currentFile,
        use_sample: state.useSample,
        max_speed: parseFloat($('maxSpeed').value),
        lat_step: parseFloat($('latStep').value),
        lon_step: parseFloat($('lonStep').value)
    };

    try {
        const res = await fetch(`${API_BASE}/api/process`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        hideLoading();

        if (data.success) {
            state.stats = data.stats;
            state.meta = data.meta;
            state.heatmapData = data.heatmap_data;
            state.trajectoryLines = data.trajectory_lines;
            state.shipsInfo = data.ships_info;
            state.cleanedCsv = data.cleaned_csv;

            updateStatsPanel();
            updateInfoCards();
            updateShipsTable();
            renderChart();

            $('statsPanel').classList.remove('hidden');
            $('shipsPanel').classList.remove('hidden');

            setStatus(
                `✅ 处理完成 · 删除 ${data.stats.removed_count} 个漂移点 (${data.stats.removal_rate.toFixed(2)}%) · ${state.heatmapData.length} 个海域格子`,
                'ok'
            );
        } else {
            setStatus(`❌ ${data.error || '处理失败'}`, 'error');
        }
    } catch (e) {
        hideLoading();
        setStatus(`❌ 请求失败: ${e.message}`, 'error');
    }
}

function updateStatsPanel() {
    const s = state.stats;
    $('statOriginal').textContent = s.original_count.toLocaleString();
    $('statCleaned').textContent = s.cleaned_count.toLocaleString();
    $('statRemoved').textContent = s.removed_count.toLocaleString();
    $('statRate').textContent = s.removal_rate.toFixed(2) + '%';
    $('statShipsOrig').textContent = s.ships_original;
    $('statShipsClean').textContent = s.ships_cleaned;
}

function updateInfoCards() {
    const m = state.meta;
    $('infoRange').innerHTML = `
        纬度: <strong>${m.lat_range[0].toFixed(4)}°</strong> ~ <strong>${m.lat_range[1].toFixed(4)}°</strong><br/>
        经度: <strong>${m.lon_range[0].toFixed(4)}°</strong> ~ <strong>${m.lon_range[1].toFixed(4)}°</strong><br/>
        航速范围: <strong>${m.speed_range[0].toFixed(1)}</strong> ~ <strong>${m.speed_range[1].toFixed(1)}</strong> 节
    `;

    $('infoGrid').innerHTML = `
        格子步长: <strong>${m.lat_step}°</strong> × <strong>${m.lon_step}°</strong><br/>
        有效格子数: <strong style="color:#70e0a0">${m.total_cells.toLocaleString()}</strong><br/>
        船舶总数: <strong>${m.total_ships}</strong> 艘 · 轨迹点: <strong>${m.total_points.toLocaleString()}</strong>
    `;

    const topCell = state.heatmapData.length > 0
        ? [...state.heatmapData].sort((a, b) => b[2] - a[2])[0]
        : null;

    const topTraj = state.trajectoryLines.length > 0
        ? [...state.trajectoryLines].sort((a, b) => b.track_count - a.track_count)[0]
        : null;

    $('infoTraffic').innerHTML = topCell ? `
        最拥堵格子: <strong style="color:#ffcc00">${topCell[2]}</strong> 个轨迹点<br/>
        位置: ${topCell[0].toFixed(3)}°, ${topCell[1].toFixed(3)}°<br/>
        ${topTraj ? `最繁忙航线段: <strong style="color:#ff9900">${topTraj.track_count}</strong> 次通行` : ''}
    ` : '—';
}

function updateShipsTable() {
    const tbody = $('shipsTableBody');
    tbody.innerHTML = state.shipsInfo.map(s => `
        <tr>
            <td><strong style="color:#7ed8ff">${s.call_sign}</strong></td>
            <td>${s.track_points}</td>
            <td>${s.lat_range[0].toFixed(3)} ~ ${s.lat_range[1].toFixed(3)}</td>
            <td>${s.lon_range[0].toFixed(3)} ~ ${s.lon_range[1].toFixed(3)}</td>
            <td><span style="color:#${s.avg_speed > 20 ? 'ff9900' : s.avg_speed > 10 ? '70e0a0' : '90b0d0'}">${s.avg_speed.toFixed(1)}</span></td>
        </tr>
    `).join('');
}

function downloadCleaned() {
    if (!state.cleanedCsv) {
        alert('没有可下载的数据');
        return;
    }
    const BOM = '\uFEFF';
    const blob = new Blob([BOM + state.cleanedCsv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'ais_cleaned.csv';
    a.click();
    URL.revokeObjectURL(url);
}

function bindEvents() {
    $('btnGenerateSample').addEventListener('click', generateSample);
    $('fileInput').addEventListener('change', handleFileUpload);
    $('btnProcess').addEventListener('click', processData);
    $('btnDownload').addEventListener('click', downloadCleaned);

    ['showHeatmap', 'showTrajectories', 'showScatter'].forEach(id => {
        $(id).addEventListener('change', renderChart);
    });
    $('heatmapDimension').addEventListener('change', renderChart);
}

document.addEventListener('DOMContentLoaded', () => {
    initChart();
    bindEvents();
});
