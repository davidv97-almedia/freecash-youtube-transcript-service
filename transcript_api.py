from flask import Flask, request, jsonify
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound, VideoUnavailable
from flask_cors import CORS
import re

app = Flask(__name__)
CORS(app)

# -------------------------------------------------------
# Extract video ID from full YouTube URL
# -------------------------------------------------------
def extract_video_id(url: str):
    if not url:
        return None

    patterns = [
        r"v=([a-zA-Z0-9_-]{6,})",
        r"youtu\.be/([a-zA-Z0-9_-]{6,})",
        r"youtube\.com/embed/([a-zA-Z0-9_-]{6,})",
    ]

    for p in patterns:
        match = re.search(p, url)
        if match:
            return match.group(1)

    return None


# -------------------------------------------------------
# Fetch transcript from YouTube
# -------------------------------------------------------
def fetch_youtube_transcript(video_id, lang="en"):
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        # Try requested language first
        try:
            transcript = transcript_list.find_transcript([lang])
        except:
            # Try AUTO-GENERATED captions
            transcript = transcript_list.find_generated_transcript([lang])

        segments = transcript.fetch()

        formatted = format_transcript_readable(segments)

        return {
            "segments": segments,
            "formatted_transcript": formatted,
        }

    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable):
        return {"segments": [], "formatted_transcript": ""}

    except Exception as e:
        return {"segments": [], "formatted_transcript": "", "error": str(e)}


# -------------------------------------------------------
# Format transcript like NoteGPT: timestamp blocks
# -------------------------------------------------------
def format_transcript_readable(segments):
    output = []
    for seg in segments:
        start = seg["start"]
        text = seg["text"].replace("\n", " ")

        timestamp = format_timestamp(start)
        output.append(f"{timestamp} {text}")

    return "\n\n".join(output)


def format_timestamp(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# -------------------------------------------------------
# /transcript endpoint
# -------------------------------------------------------
@app.route("/transcript", methods=["POST"])
def transcript_endpoint():
    # Very forgiving JSON parsing
    try:
        data = request.get_json(force=True, silent=True) or {}
    except:
        data = {}

    video_url = data.get("video_url")

    if not video_url:
        return jsonify({
            "error": "Missing 'video_url' in JSON body",
            "received_body": data
        }), 400

    # Parse ID
    video_id = extract_video_id(video_url)
    if not video_id:
        return jsonify({
            "error": "Could not extract video ID from URL",
            "video_url": video_url
        }), 400

    # Get transcript
    result = fetch_youtube_transcript(video_id)

    if not result["segments"]:
        return jsonify({
            "video_url": video_url,
            "video_id": video_id,
            "error": "No transcript available (subtitles disabled or unsupported language)"
        }), 404

    # Success
    return jsonify({
        "video_url": video_url,
        "video_id": video_id,
        "formatted_transcript": result["formatted_transcript"],
        "segments": result["segments"]
    })


# -------------------------------------------------------
# Root endpoint
# -------------------------------------------------------
@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "OK",
        "message": "Freecash YouTube Transcript API",
        "usage": "POST /transcript with JSON { 'video_url': '...'}"
    })


# -------------------------------------------------------
# Run locally
# -------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
