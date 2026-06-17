import math

HARBORS = [
    {
        'name': '上海港洋山港区',
        'code': 'SHANGHAI-YS',
        'lat_center': 30.65,
        'lon_center': 122.15,
        'radius_km': 8.0,
        'type': 'international_port'
    },
    {
        'name': '宁波舟山港',
        'code': 'NINGBO-ZS',
        'lat_center': 29.95,
        'lon_center': 122.10,
        'radius_km': 10.0,
        'type': 'international_port'
    },
    {
        'name': '上海外高桥港区',
        'code': 'SHANGHAI-WGQ',
        'lat_center': 31.38,
        'lon_center': 121.62,
        'radius_km': 5.0,
        'type': 'river_port'
    },
    {
        'name': '舟山嵊泗锚地',
        'code': 'ZHOUSHAN-SS',
        'lat_center': 30.75,
        'lon_center': 122.45,
        'radius_km': 6.0,
        'type': 'designated_anchorage'
    },
    {
        'name': '杭州湾跨海大桥施工区',
        'code': 'HZW-BRIDGE',
        'lat_center': 30.30,
        'lon_center': 121.20,
        'radius_km': 3.0,
        'type': 'construction_zone'
    }
]


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def is_in_any_harbor(lat, lon, harbor_list=None):
    if harbor_list is None:
        harbor_list = HARBORS
    for h in harbor_list:
        dist = haversine_km(lat, lon, h['lat_center'], h['lon_center'])
        if dist <= h['radius_km']:
            return True, h
    return False, None
