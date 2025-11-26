from flask import Flask, request, jsonify
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlparse, parse_qs

app = Flask(__name__)


def extract_video_id(video_url: str) -> str:
    """
    Extract the YouTube video ID from typical URL formats.
    Supports:
      - https://www.youtube.com/watch?v=VIDEO_ID
      - https://youtu.be/VIDEO_ID
    """
    if not video_url:
        return None

    parsed = urlparse(video_url)

    # Case 1: https://www.youtube.com/watch?v=VIDEO_ID
    if parsed.hostname and "youtube.com" in parsed.hostname:
        qs = parse_qs(parsed.query)
        if "v" in qs and qs["v"]:
            return qs["v"][0]

    # Case 2: https://youtu.be/VIDEO_ID
    if parsed.hostname and "youtu.be" in parsed.hostname:
        # path is like "/VIDEO_ID"
        return parsed.path.lstrip("/")

    # Fallback: if user passes the bare ID
    if len(video_url) == 11:
        return video_url

    return None


def format_timestamp(seconds: float) -> str:
    """
    Convert seconds -> HH:MM:SS (zero-padded).
    """
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def fetch_youtube_transcript(video_id: str, lang: str = "en") -> dict:
    """
    Fetch subtitles from YouTube's timedtext API and format them.
    Returns a dict with:
      - segments: list of {start, dur, text}
      - formatted_transcript: string with timestamps like 00:00:00 ...
    """
    base_url = "https://www.youtube.com/api/timedtext"
    params = {"v": video_id, "lang": lang}

    r = requests.get(base_url, params=params, timeout=20)

    if r.status_code != 200 or not r.text.strip():
        return {
            "segments": [],
            "formatted_transcript": "",
        }

    # Parse XML
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError:
        return {
            "segments": [],
            "formatted_transcript": "",
        }

    segments = []
    for node in root.findall("text"):
        start = float(node.attrib.get("start", "0"))
        dur = float(node.attrib.get("dur", "0"))
        text = (node.text or "").replace("\n", " ").strip()
        if text:
            segments.append(
                {"start": start, "dur": dur, "text": text}
            )

    # Build a human-friendly transcript with timestamps every ~30 seconds
    # similar style to NoteGPT
    bucket_seconds = 30  # you can change this to 15, 60, etc.
    buckets = {}

    for seg in segments:
        bucket_start = int(seg["start"] // bucket_seconds) * bucket_seconds
        buckets.setdefault(bucket_start, [])
        buckets[bucket_start].append(seg["text"])

    lines = []
    for bucket_start in sorted(buckets.keys()):
        ts = format_timestamp(bucket_start)
        text_block = " ".join(buckets[bucket_start])
        lines.append(f"{ts}\n{text_block}")

    formatted_transcript = "\n\n".join(lines)

    return {
        "segments": segments,
        "formatted_transcript": formatted_transcript,
    }


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "message": "YouTube transcript service is running"})


@app.route("/transcript", methods=["POST"])
def transcript_endpoint():
    data = request.get_json(silent=True) or {}
    video_url = data.get("video_url")

    if not video_url:
        return jsonify({"error": "Missing 'video_url' in JSON body"}), 400

    video_id = extract_video_id(video_url)
    if not video_id:
        return jsonify({"error": "Could not extract video ID from URL"}), 400

    result = fetch_youtube_transcript(video_id, lang="en")

    if not result["segments"]:
        return (
            jsonify(
                {
                    "video_url": video_url,
                    "video_id": video_id,
                    "error": "No transcript found (maybe subtitles are disabled or not in English).",
                }
            ),
            404,
        )

    return jsonify(
        {
            "video_url": video_url,
            "video_id": video_id,
            "formatted_transcript": result["formatted_transcript"],
            "segments": result["segments"],
        }
    )


if __name__ == "__main__":
    # for local debugging; Render will ignore this
    app.run(host="0.0.0.0", port=10000)
