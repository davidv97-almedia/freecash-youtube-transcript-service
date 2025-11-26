from flask import Flask, request, jsonify
from urllib.parse import urlparse, parse_qs

from youtube_transcript_api import (
    YouTubeTranscriptApi,
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

app = Flask(__name__)


def extract_video_id(url_or_id: str) -> str:
    """
    Accepts either a full YouTube URL or a plain video id and
    returns the 11-character video id.
    """
    url_or_id = url_or_id.strip()

    # If it looks like a bare 11-char ID, just return it
    if len(url_or_id) == 11 and "/" not in url_or_id and "?" not in url_or_id:
        return url_or_id

    parsed = urlparse(url_or_id)

    # youtu.be/<id>
    if parsed.hostname and parsed.hostname.endswith("youtu.be"):
        return parsed.path.lstrip("/")

    # youtube.com/watch?v=<id>
    if parsed.hostname and "youtube" in parsed.hostname:
        qs = parse_qs(parsed.query)
        if "v" in qs and qs["v"]:
            return qs["v"][0]

    # Fallback: last 11 chars
    return url_or_id[-11:]


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/transcript", methods=["POST"])
def transcript():
    """
    Request body:
      { "video_url": "<full YouTube URL or ID>" }

    Response body:
      {
        "video_id": "...",
        "video_url": "...",
        "segments": [ { "start": ..., "duration": ..., "text": "..." }, ... ],
        "formatted": "00:00:00\\nText...\\n\\n00:00:05\\nNext text..."
      }
    """
    data = request.get_json(force=True) or {}
    video_url = data.get("video_url")

    if not video_url:
        return jsonify({"error": "video_url is required"}), 400

    video_id = extract_video_id(video_url)

    try:
        # Get transcript (English by default – adjust languages if needed)
        segments = YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])
    except TranscriptsDisabled:
        return jsonify({"error": "transcripts_disabled"}), 404
    except NoTranscriptFound:
        return jsonify({"error": "no_transcript_found"}), 404
    except VideoUnavailable:
        return jsonify({"error": "video_unavailable"}), 404
    except Exception as e:
        # Catch any unexpected errors
        return jsonify({"error": str(e)}), 500

    # Build NoteGPT-style formatted text
    formatted_blocks = []
    for entry in segments:
        start = int(entry["start"])
        h = start // 3600
        m = (start % 3600) // 60
        s = start % 60
        timestamp = f"{h:02d}:{m:02d}:{s:02d}"
        formatted_blocks.append(f"{timestamp}\n{entry['text']}")

    formatted_text = "\n\n".join(formatted_blocks)

    return jsonify(
        {
            "video_id": video_id,
            "video_url": video_url,
            "segments": segments,
            "formatted": formatted_text,
        }
    )


if __name__ == "__main__":
    # Local dev
    app.run(host="0.0.0.0", port=8000, debug=True)
