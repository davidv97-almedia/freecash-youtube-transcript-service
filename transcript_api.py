import os
import re
import tempfile
from flask import Flask, request, jsonify

from youtube_transcript_api import (
    YouTubeTranscriptApi,
    TranscriptsDisabled,
    NoTranscriptFound,
    CouldNotRetrieveTranscript,
)
import yt_dlp
from openai import OpenAI

# ====== config ======
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

app = Flask(__name__)


# ---------- helpers ----------

def extract_video_id(video_url: str) -> str | None:
    """
    Extract YouTube video ID from a full URL or just return the ID if given.
    """
    # If they already give just the ID
    if re.fullmatch(r"[0-9A-Za-z_-]{11}", video_url):
        return video_url

    # Common URL patterns
    patterns = [
        r"youtube\.com/watch\?v=([0-9A-Za-z_-]{11})",
        r"youtu\.be/([0-9A-Za-z_-]{11})",
        r"youtube\.com/embed/([0-9A-Za-z_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, video_url)
        if m:
            return m.group(1)
    return None


def format_time(seconds: float) -> str:
    """
    Convert seconds -> HH:MM:SS
    """
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_timed_transcript_from_youtube(video_id: str) -> dict:
    """
    First try to fetch YouTube captions and format them as:
    00:00:00 Text...
    00:00:04 Next line...
    """
    try:
        transcripts = YouTubeTranscriptApi.list_transcripts(video_id)

        # Prefer manually created subtitles, otherwise auto-generated
        try:
            transcript_obj = transcripts.find_manually_created_transcript(["en"])
        except NoTranscriptFound:
            transcript_obj = transcripts.find_generated_transcript(["en"])

        raw = transcript_obj.fetch()
    except (TranscriptsDisabled, NoTranscriptFound, CouldNotRetrieveTranscript) as e:
        raise e  # handled in caller
    except Exception as e:
        raise e

    lines = []
    for entry in raw:
        t = format_time(entry["start"])
        text = entry["text"].replace("\n", " ").strip()
        if text:
            lines.append(f"{t}\n{text}")

    return {
        "source": "youtube_captions",
        "video_id": video_id,
        "transcript": "\n\n".join(lines),
    }


def download_audio(video_url: str, temp_dir: str) -> str:
    """
    Use yt-dlp to download audio only and return filepath.
    """
    filename = os.path.join(temp_dir, "audio.m4a")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": filename,
        "quiet": True,
        "noplaylist": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])

    return filename


def build_timed_transcript_from_whisper(video_url: str, video_id: str) -> dict:
    """
    Fallback: download audio + call OpenAI Whisper, then build time-coded text.
    """
    if not OPENAI_API_KEY:
        return {
            "source": "error",
            "video_id": video_id,
            "error": "OPENAI_API_KEY not set on server; cannot run ASR fallback.",
        }

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = download_audio(video_url, tmpdir)

        with open(audio_path, "rb") as f:
            # Use verbose_json to get segments with timestamps
            result = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="verbose_json",
            )

        segments = result.segments or []

    lines = []
    for seg in segments:
        start = float(seg.get("start", 0.0))
        t = format_time(start)
        text = seg.get("text", "").strip()
        if text:
            lines.append(f"{t}\n{text}")

    return {
        "source": "whisper_fallback",
        "video_id": video_id,
        "transcript": "\n\n".join(lines),
    }


# ---------- routes ----------


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/transcript", methods=["POST"])
def transcript():
    data = request.get_json(silent=True) or {}
    video_url = data.get("video_url")

    if not video_url:
        return jsonify({"error": "Missing 'video_url' in JSON body"}), 400

    video_id = extract_video_id(video_url)
    if not video_id:
        return jsonify({"error": "Could not extract video_id from URL"}), 400

    # 1) try YouTube captions
    try:
        yt_result = build_timed_transcript_from_youtube(video_id)
        yt_result["video_url"] = video_url
        return jsonify(yt_result), 200
    except (TranscriptsDisabled, NoTranscriptFound, CouldNotRetrieveTranscript):
        # no captions – fall through to Whisper
        pass
    except Exception as e:
        # unexpected error – log and still try Whisper
        print("Error fetching YouTube transcript:", e)

    # 2) fallback to Whisper
    try:
        whisper_result = build_timed_transcript_from_whisper(video_url, video_id)
        whisper_result["video_url"] = video_url
        status = 200 if whisper_result.get("source") != "error" else 500
        return jsonify(whisper_result), status
    except Exception as e:
        print("Error in Whisper fallback:", e)
        return jsonify(
            {
                "error": "Failed to generate transcript from captions or audio.",
                "video_id": video_id,
                "video_url": video_url,
            }
        ), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
