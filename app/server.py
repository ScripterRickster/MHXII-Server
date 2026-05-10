from flask import Flask, jsonify, request, send_from_directory
from pymongo import MongoClient
from pymongo.server_api import ServerApi
from bson.objectid import ObjectId
import base64
import datetime
import os
import random
import time
from urllib.parse import quote_plus
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
WEBSITE_DIR = os.path.join(BASE_DIR, 'website')

mongo_uri = os.environ.get('MONGO_URI')
# If MONGO_URI contains obvious placeholders like '<' or '>' treat it as unset
if mongo_uri and ('<' in mongo_uri or '>' in mongo_uri or 'db_password' in mongo_uri):
    print('Ignoring placeholder MONGO_URI from environment')
    mongo_uri = None

if not mongo_uri:
    mongo_user = os.environ.get('MONGO_USER')
    mongo_pass = os.environ.get('MONGO_PASS')
    mongo_host = os.environ.get('MONGO_HOST', 'mhxii.qi2wpez.mongodb.net')
    if mongo_user and mongo_pass:
        # use lowercase appname as recognized option
        mongo_uri = f"mongodb+srv://{quote_plus(mongo_user)}:{quote_plus(mongo_pass)}@{mongo_host}/?appname=MHXII"
    else:
        mongo_uri = os.environ.get('MONGO_URI', 'mongodb://localhost:27017')

def _mask_uri(uri: str) -> str:
    try:
        # mask between // and @
        if '://' in uri and '@' in uri:
            prefix, rest = uri.split('://', 1)
            creds, hostpart = rest.split('@', 1)
            return f"{prefix}://{creds.split(':')[0]}:****@{hostpart}"
    except Exception:
        pass
    return uri

print('Mongo URI (masked):', _mask_uri(mongo_uri))
try:
    client = MongoClient(mongo_uri, server_api=ServerApi('1'), serverSelectionTimeoutMS=3000, connectTimeoutMS=3000)
    try:
        client.admin.command('ping')
        print('Pinged your deployment. You successfully connected to MongoDB!')
    except Exception as e:
        print('Mongo ping failed:', e)
except Exception as e:
    print('Failed to create MongoClient from MONGO_URI, falling back to localhost:', e)
    client = MongoClient('mongodb://localhost:27017', serverSelectionTimeoutMS=3000, connectTimeoutMS=3000)

db = client.get_database(os.environ.get('MONGO_DB','testdb'))
items_col = db.get_collection('items')
frames_col = db.get_collection('frames')
locations_col = db.get_collection('locations')


_mongo_ready_cache = {'ready': False, 'time': 0, 'last_warn': 0}


def _mongo_ready() -> bool:
    now = time.time()
    # Cache longer when known-good (30s); retry sooner when known-bad (10 s)
    ttl = 30 if _mongo_ready_cache['ready'] else 10
    if now - _mongo_ready_cache['time'] < ttl:
        return _mongo_ready_cache['ready']
    try:
        client.admin.command('ping', timeoutMS=6000)
        if not _mongo_ready_cache['ready']:
            print('INFO: MongoDB connection restored')
        result = True
    except Exception as exc:
        # Only warn once every 60s to avoid flooding the console
        if now - _mongo_ready_cache['last_warn'] > 60:
            print(f'WARNING: MongoDB unavailable — {exc}')
            _mongo_ready_cache['last_warn'] = now
        result = False
    _mongo_ready_cache['ready'] = result
    _mongo_ready_cache['time'] = now
    return result


def _location_key(doc):
    return (
        round(float(doc.get('lat', 0)), 6),
        round(float(doc.get('lon', 0)), 6),
        doc.get('device') or '',
        doc.get('source') or ''
    )


def _dedupe_locations(docs):
    seen = set()
    unique_docs = []
    duplicate_ids = []

    for doc in docs:
        key = _location_key(doc)
        if key in seen:
            duplicate_ids.append(doc['_id'])
            continue
        seen.add(key)
        unique_docs.append(doc)

    if duplicate_ids:
        try:
            locations_col.delete_many({'_id': {'$in': duplicate_ids}})
            print(f'Removed {len(duplicate_ids)} duplicate location(s) from MongoDB')
        except Exception as exc:
            print('Failed to delete duplicate locations:', exc)

    return unique_docs


# Robot state
_robot_state = {
    'state': 'off',
    'desired_state': 'off',
    'shutdown_requested': False,
    'pi_last_seen': 0,    # updated when Pi polls /robot/pi/commands
    'pi_last_update': 0,  # updated when Pi posts state (on/starting/stopping only)
    'pi_meta': {}
}
PI_STALE_SECONDS = 15


@app.route('/feed/upload', methods=['POST'])
def upload_frame():
    data = request.get_json(force=True) or {}
    img_b64 = data.get('image')
    if not img_b64:
        return jsonify(error='no image'), 400
    if img_b64.startswith('data:'):
        img_b64 = img_b64.split(',', 1)[1]
    try:
        img_bytes = base64.b64decode(img_b64)
    except Exception:
        return jsonify(error='invalid image data'), 400
    doc = {'timestamp': datetime.datetime.utcnow(), 'image_b64': img_b64}
    res = frames_col.insert_one(doc)
    return jsonify(inserted_id=str(res.inserted_id)), 201


@app.route('/feed/latest', methods=['GET'])
def get_latest_frame():
    doc = frames_col.find_one(sort=[('timestamp', -1)])
    if not doc:
        return jsonify(error='no frames'), 404
    return jsonify(timestamp=doc['timestamp'].isoformat()+'Z', image=doc['image_b64'])


_frame_warn_ts = 0

@app.route('/feed/latest.png', methods=['GET'])
def get_latest_frame_png():
    global _frame_warn_ts
    transparent_png = base64.b64decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/7t8AAAAASUVORK5CYII='
    )
    if not _mongo_ready():
        now = time.time()
        if now - _frame_warn_ts > 30:
            print('WARNING: /feed/latest.png - MongoDB unavailable, returning blank frame')
            _frame_warn_ts = now
        return (transparent_png, 200, {'Content-Type': 'image/png'})
    try:
        doc = frames_col.find_one(sort=[('timestamp', -1)])
        if not doc:
            return (transparent_png, 200, {'Content-Type': 'image/png'})
        img_b64 = doc.get('image_b64')
        if not img_b64:
            return (transparent_png, 200, {'Content-Type': 'image/png'})
        img_bytes = base64.b64decode(img_b64)
        return (img_bytes, 200, {'Content-Type': 'image/png'})
    except Exception as exc:
        now = time.time()
        if now - _frame_warn_ts > 30:
            print(f'WARNING: Failed to serve latest frame PNG: {exc}')
            _frame_warn_ts = now
        return (transparent_png, 200, {'Content-Type': 'image/png'})

@app.route('/', methods=['GET'])
def root():
    return send_from_directory(os.path.join(WEBSITE_DIR, 'html'), 'main.html')

@app.route('/health', methods=['GET'])
def health():
    return jsonify(status='ok')


@app.route('/ping', methods=['GET'])
def ping():
    return jsonify(status='ok', message='pong')


@app.route('/keepalive', methods=['GET', 'HEAD'])
def keepalive():
    print('server status: OK')
    return jsonify(status='ok', message='keepalive')


@app.route('/test', methods=['POST'])
def test_post():
    data = request.get_json(silent=True) or {}
    return jsonify(status='ok', message='test post received', received=data)


@app.route('/robot/status', methods=['GET'])
def robot_status():
    now = time.time()
    last_seen = _robot_state.get('pi_last_seen', 0)
    last_update = _robot_state.get('pi_last_update', 0)
    pi_polling  = (now - last_seen)   <= PI_STALE_SECONDS if last_seen   else False
    pi_connected = (now - last_update) <= PI_STALE_SECONDS if last_update else False
    pi_meta = _robot_state.get('pi_meta') or {}
    return jsonify(
        state=_robot_state['state'],
        desired_state=_robot_state['desired_state'],
        shutdown_requested=_robot_state['shutdown_requested'],
        pi_connected=pi_connected,
        pi_polling=pi_polling,
        pi_last_seen=last_seen,
        battery=pi_meta.get('battery'),
        message=pi_meta.get('message'),
        extra=pi_meta.get('extra')
    )


@app.route('/robot/toggle', methods=['POST'])
def robot_toggle():
    new_desired = 'on' if _robot_state['desired_state'] == 'off' else 'off'
    _robot_state['desired_state'] = new_desired
    if new_desired == 'off':
        # clear shutdown intent unless explicitly requested
        _robot_state['shutdown_requested'] = False
    return jsonify(
        ok=True,
        desired_state=_robot_state['desired_state'],
        state=_robot_state['state']
    )


@app.route('/robot/shutdown', methods=['POST'])
def robot_shutdown():
    _robot_state['shutdown_requested'] = True
    _robot_state['desired_state'] = 'off'
    return jsonify(ok=True, shutdown_requested=True)


@app.route('/robot/pi/update', methods=['POST'])
def robot_pi_update():
    data = request.get_json(silent=True) or {}
    state = str(data.get('state', _robot_state['state'])).lower()
    if state not in ('on', 'off', 'starting', 'stopping', 'idle', 'unknown'):
        state = 'unknown'

    now = time.time()
    _robot_state['state'] = state
    _robot_state['pi_last_seen'] = now
    # pi_last_update only advances when the robot is actively running.
    # This keeps the circle yellow (Pi idle) rather than green (robot running).
    if state in ('on', 'starting', 'stopping'):
        _robot_state['pi_last_update'] = now
    _robot_state['pi_meta'] = {
        'battery': data.get('battery'),
        'message': data.get('message'),
        'extra': data.get('extra')
    }

    return jsonify(ok=True)


@app.route('/robot/pi/commands', methods=['GET'])
def robot_pi_commands():
    now = time.time()
    _robot_state['pi_last_seen'] = now

    start_requested = _robot_state['desired_state'] == 'on'
    shutdown_requested = _robot_state['shutdown_requested']

    return jsonify(
        ok=True,
        start=start_requested,
        shutdown=shutdown_requested,
        desired_state=_robot_state['desired_state'],
        server_time=now
    )


@app.route('/robot/pi/ack-shutdown', methods=['POST'])
def robot_pi_ack_shutdown():
    data = request.get_json(silent=True) or {}
    ack = bool(data.get('ack', True))
    if ack:
        _robot_state['shutdown_requested'] = False
        _robot_state['state'] = 'off'
        _robot_state['desired_state'] = 'off'
    _robot_state['pi_last_seen'] = time.time()
    return jsonify(ok=True, shutdown_requested=_robot_state['shutdown_requested'])


@app.route('/css/<path:filename>')
def serve_css(filename):
    return send_from_directory(os.path.join(WEBSITE_DIR, 'css'), filename)


@app.route('/scripts/<path:filename>')
def serve_scripts(filename):
    return send_from_directory(os.path.join(WEBSITE_DIR, 'scripts'), filename)


@app.route('/images/<path:filename>')
def serve_images(filename):
    return send_from_directory(os.path.join(WEBSITE_DIR, 'images'), filename)

@app.route('/items', methods=['GET'])
def get_items():
    docs = list(items_col.find())
    for d in docs:
        d['_id'] = str(d['_id'])
    return jsonify(items=docs)

@app.route('/items', methods=['POST'])
def create_item():
    data = request.get_json(force=True) or {}
    res = items_col.insert_one(data)
    return jsonify(inserted_id=str(res.inserted_id)), 201

@app.route('/items/<id>', methods=['GET'])
def get_item(id):
    try:
        doc = items_col.find_one({'_id': ObjectId(id)})
    except Exception:
        return jsonify(error='invalid id'), 400
    if not doc:
        return jsonify(error='not found'), 404
    doc['_id'] = str(doc['_id'])
    return jsonify(item=doc)


@app.route('/locations/count', methods=['GET'])
def get_location_count():
    if not _mongo_ready():
        return jsonify(count=0, warning='database unavailable'), 200
    try:
        count = locations_col.count_documents({})
    except Exception as exc:
        print('Failed to count locations:', exc)
        return jsonify(count=0, warning='database unavailable'), 200
    return jsonify(count=count)


@app.route('/locations', methods=['POST'])
def add_location():
    data = request.get_json(force=True) or {}

    device = data.get('device')
    source = 'random'
    lat = None
    lon = None

    # Accept GPS coordinates as a space-separated string -> "lat lon"
    gps_raw = data.get('gps') or data.get('location') or ''
    if gps_raw and isinstance(gps_raw, str):
        parts = gps_raw.strip().split()
        if len(parts) >= 2:
            try:
                lat = float(parts[0])
                lon = float(parts[1])
                if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                    print(f'GPS coords out of range ({lat}, {lon}), falling back to random')
                    lat = lon = None
                else:
                    source = 'gps'
            except ValueError:
                print(f'Failed to parse GPS string: {gps_raw!r}, falling back to random')

    # Fallback -> random coordinates
    if lat is None or lon is None:
        lat = random.uniform(-45.0, 45.0)
        lon = random.uniform(-90.0, 90.0)
        source = 'random'

    # Optional -> base64 image captured at detection time
    img_b64 = data.get('image') or ''
    if img_b64 and img_b64.startswith('data:'):
        img_b64 = img_b64.split(',', 1)[1]
    if img_b64:
        try:
            base64.b64decode(img_b64)  # validate
        except Exception:
            print('Invalid image data on location POST, discarding image')
            img_b64 = ''

    doc = {
        'timestamp': datetime.datetime.utcnow(),
        'lat': lat,
        'lon': lon,
        'device': device,
        'source': source,
        'image_b64': img_b64 or None,
    }
    try:
        res = locations_col.insert_one(doc)
    except Exception as exc:
        print(f'WARNING: Failed to insert location: {exc}')
        return jsonify(error='database unavailable'), 503
    try:
        all_docs = list(locations_col.find().sort('timestamp', -1))
        _dedupe_locations(all_docs)
    except Exception as exc:
        print(f'WARNING: Duplicate cleanup after insert failed: {exc}')
    _mongo_ready_cache['ready'] = True
    _mongo_ready_cache['time'] = time.time()
    return jsonify(inserted_id=str(res.inserted_id)), 201


@app.route('/locations', methods=['GET'])
def get_locations():
    if not _mongo_ready():
        return jsonify(locations=[], warning='database unavailable'), 200
    try:
        limit = int(request.args.get('limit', 100))
    except Exception:
        limit = 100
    try:
        docs = list(locations_col.find().sort('timestamp', -1).limit(limit))
    except Exception as exc:
        print('Failed to read locations:', exc)
        return jsonify(locations=[], warning='database unavailable'), 200
    docs = _dedupe_locations(docs)
    for d in docs:
        d['_id'] = str(d['_id'])
        # ensure timestamp is serializable
        if isinstance(d.get('timestamp'), datetime.datetime):
            d['timestamp'] = d['timestamp'].isoformat() + 'Z'
        # ensure image field is always present (may be None)
        if 'image_b64' not in d:
            d['image_b64'] = None
    return jsonify(locations=docs)


if __name__=='__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',8000)))