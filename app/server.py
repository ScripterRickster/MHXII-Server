from flask import Flask, jsonify, request, send_from_directory
from pymongo import MongoClient
from pymongo.server_api import ServerApi
from bson.objectid import ObjectId
import base64
import datetime
import os
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
    client = MongoClient(mongo_uri, server_api=ServerApi('1'))
    try:
        client.admin.command('ping')
        print('Pinged your deployment. You successfully connected to MongoDB!')
    except Exception as e:
        print('Mongo ping failed:', e)
except Exception as e:
    print('Failed to create MongoClient from MONGO_URI, falling back to localhost:', e)
    client = MongoClient('mongodb://localhost:27017')

db = client.get_database(os.environ.get('MONGO_DB','testdb'))
items_col = db.get_collection('items')
frames_col = db.get_collection('frames')
locations_col = db.get_collection('locations')


def _mongo_ready() -> bool:
    try:
        client.admin.command('ping')
        return True
    except Exception as exc:
        print('Mongo unavailable:', exc)
        return False


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
    doc = frames_col.find_one(sort=[('timestamp', -1)])
    if not doc:
        return ('', 404)
    img_b64 = doc['image_b64']
    img_bytes = base64.b64decode(img_b64)
    return (img_bytes, 200, {'Content-Type': 'image/png'})

@app.route('/', methods=['GET'])
def root():
    return send_from_directory(os.path.join(WEBSITE_DIR, 'html'), 'main.html')

@app.route('/health', methods=['GET'])
def health():
    return jsonify(status='ok')


@app.route('/ping', methods=['GET'])
def ping():
    return jsonify(status='ok', message='pong')


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
    # accept lat/lon or latitude/longitude, optional device id
    lat = data.get('lat') if data.get('lat') is not None else data.get('latitude')
    lon = data.get('lon') if data.get('lon') is not None else data.get('longitude')
    device = data.get('device')
    if lat is None or lon is None:
        return jsonify(error='lat and lon required'), 400
    try:
        lat = float(lat)
        lon = float(lon)
    except Exception:
        return jsonify(error='invalid lat/lon'), 400
    doc = {'timestamp': datetime.datetime.utcnow(), 'lat': lat, 'lon': lon, 'device': device}
    res = locations_col.insert_one(doc)
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
    for d in docs:
        d['_id'] = str(d['_id'])
        # ensure timestamp is serializable
        if isinstance(d.get('timestamp'), datetime.datetime):
            d['timestamp'] = d['timestamp'].isoformat() + 'Z'
    return jsonify(locations=docs)


if __name__=='__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',8000)))
