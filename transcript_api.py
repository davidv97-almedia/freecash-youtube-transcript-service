from flask import Flask, request, jsonify
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
from urllib.parse import urlparse, parse_qs

app = Flask(__name__)

def extract_video_id(url: str) -> str:
    """
    Handles:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID
    - https://www.youtube.com/shorts/VIDEO_ID
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()

    # youtu.be/VIDEO_ID
    if "youtu.be" in host:
        return parsed.path.lstrip("/")

    # youtube.com/* variants
    if "youtube.com" in host:
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [""])[0]
        # /shorts/VIDEO_ID
        if parsed.path.startswith("/shorts/"):
            parts = parsed.path.split("/")
            if len(parts) >= 3:
                return parts[2]

    # fallback: last path segment
    return parsed.path.split("/")[-1]

@app.route("/transcript", methods=["POST"])
def get_transcript():
    data = request.get_json(force=True, silent=True) or {}
    video_url = data.get("video_url")

    if not video_url:
        return jsonify({"error": "video_url is required"}), 400

    video_id = extract_video_id(video_url)

    try:
        # Try common languages – adjust if needed
        transcript = YouTubeTranscriptApi.get_transcript(
            video_id,
            languages=['en', 'de', 'es', 'fr', 'pt']
        )
    except (NoTranscriptFound, TranscriptsDisabled):
        return jsonify({"error": "no_transcript_available", "video_id": video_id}), 404
    except Exception as e:
        return jsonify({"error": "internal_error", "detail": str(e), "video_id": video_id}), 500

    # transcript = list of {text, start, duration}
    return jsonify({
        "video_id": video_id,
        "video_url": video_url,
        "transcript_segments": transcript
    }), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
