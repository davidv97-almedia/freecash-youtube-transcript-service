from flask import Flask, request, jsonify
from youtube_transcript_api import YouTubeTranscriptApi
from urllib.parse import urlparse, parse_qs

app = Flask(__name__)

def extract_video_id(url):
    query = urlparse(url)
    if query.hostname == 'youtu.be':
        return query.path[1:]
    if query.hostname in ['www.youtube.com', 'youtube.com']:
        return parse_qs(query.query).get('v', [None])[0]
    return None

@app.route('/transcript', methods=['POST'])
def transcript():
    data = request.get_json()
    if not data or "video_url" not in data:
        return jsonify({"error": "video_url is required"}), 400

    video_id = extract_video_id(data["video_url"])
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400

    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        # Format transcript like NoteGPT
        formatted = []
        for entry in transcript_list:
            formatted.append({
                "start": entry["start"],
                "duration": entry["duration"],
                "text": entry["text"]
            })

        return jsonify({
            "video_id": video_id,
            "transcript": formatted
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/')
def home():
    return jsonify({"message": "YouTube Transcript API Running"})
