from flask import Flask, jsonify, request, send_from_directory
from pymongo import MongoClient
from pymongo.server_api import ServerApi
from bson.objectid import ObjectId
import base64
import datetime
import os
import random
import time
import json
import urllib.request
import urllib.error
from urllib.parse import quote_plus
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
WEBSITE_DIR = os.path.join(BASE_DIR, 'website')
PI_URL = os.environ.get('PI_URL', 'http://192.168.1.100:5000')

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


_mongo_ready_cache = {'ready': False, 'time': 0}


def _mongo_ready() -> bool:
    now = time.time()
    # Cache the result for 5 seconds to avoid repeated timeouts
    if now - _mongo_ready_cache['time'] < 5:
        return _mongo_ready_cache['ready']
    try:
        client.admin.command('ping', timeoutMS=2000)
        result = True
    except Exception as exc:
        print('Mongo unavailable:', exc)
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
_robot_state = {'state': 'off'}
_pi_url_override = None


def _get_pi_url():
    """Get the current PI URL (from override or environment)"""
    if _pi_url_override:
        return _pi_url_override
    return PI_URL


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


@app.route('/feed/latest.png', methods=['GET'])
def get_latest_frame_png():
    transparent_png = base64.b64decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/7t8AAAAASUVORK5CYII='
    )
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
        print('Failed to serve latest frame PNG:', exc)
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
    # Lightweight endpoint for external keepalive pingers.
    return jsonify(status='ok', message='keepalive')


@app.route('/test', methods=['POST'])
def test_post():
    data = request.get_json(silent=True) or {}
    return jsonify(status='ok', message='test post received', received=data)


@app.route('/robot/status', methods=['GET'])
def robot_status():
    # Try to get real status from Pi
    try:
        pi_url = _get_pi_url()
        status_url = f"{pi_url}/status"
        with urllib.request.urlopen(status_url, timeout=3) as response:
            pi_data = json.loads(response.read().decode('utf-8'))
            state = pi_data.get('state', 'unknown')
            _robot_state['state'] = state  # Update cache
            return jsonify(state=state)
    except Exception as e:
        # Fall back to cached state if Pi unavailable
        print(f"Could not reach Pi for status: {e}")
        return jsonify(state=_robot_state['state'], warning='using cached state')


@app.route('/robot/toggle', methods=['POST'])
def robot_toggle():
    # Toggle the local state
    new_state = 'on' if _robot_state['state'] == 'off' else 'off'
    _robot_state['state'] = new_state
    
    # Try to send command to Raspberry Pi
    pi_error = None
    try:
        pi_url = _get_pi_url()
        command_url = f"{pi_url}/control/robot?action={new_state}"
        req = urllib.request.Request(command_url, method='POST', timeout=5)
        with urllib.request.urlopen(req) as response:
            response.read()
        print(f"Robot command sent to Pi: {new_state}")
    except urllib.error.URLError as e:
        pi_error = f"Pi unreachable: {str(e)}"
        print(pi_error)
    except Exception as e:
        pi_error = f"Pi command failed: {str(e)}"
        print(pi_error)
    
    return jsonify(state=new_state, pi_error=pi_error)


@app.route('/robot/set-pi-url', methods=['POST'])
def set_pi_url():
    global _pi_url_override
    data = request.get_json(force=True) or {}
    new_url = data.get('pi_url', '').strip()
    if not new_url:
        _pi_url_override = None
        return jsonify(status='cleared', pi_url=PI_URL)
    _pi_url_override = new_url
    print(f"Pi URL updated to: {new_url}")
    return jsonify(status='ok', pi_url=new_url)


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


@app.route('/locations', methods=['POST'])
def add_location():
    if not _mongo_ready():
        return jsonify(error='database unavailable'), 503
    data = request.get_json(force=True) or {}
    # Generate a random point here so clients do not need to send coordinates.
    lat = random.uniform(-45.0, 45.0)
    lon = random.uniform(-90.0, 90.0)
    device = data.get('device')
    doc = {'timestamp': datetime.datetime.utcnow(), 'lat': lat, 'lon': lon, 'device': device, 'source': 'random'}
    res = locations_col.insert_one(doc)
    try:
        all_docs = list(locations_col.find().sort('timestamp', -1))
        _dedupe_locations(all_docs)
    except Exception as exc:
        print('Duplicate cleanup after insert failed:', exc)
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
    return jsonify(locations=docs)


if __name__=='__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',8000)))
