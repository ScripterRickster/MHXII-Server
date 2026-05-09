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

if __name__=='__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',8000)))
