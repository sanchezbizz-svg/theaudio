from flask import Flask, request, jsonify, Response, stream_with_context
import subprocess
import tempfile
import os
import sys
import re
import shutil

app = Flask(__name__)

# -----------------------------
# Utils
# -----------------------------
def is_valid_tiktok_url(url: str) -> bool:
    return bool(re.search(r"(vm\.tiktok\.com|tiktok\.com)", url))


# -----------------------------
# AUDIO EXTRACTION → MP3
# -----------------------------
@app.route("/tiktok/mp3", methods=["POST", "OPTIONS"])
def tiktok_mp3():
    if request.method == "OPTIONS":
        return "", 200

    data = request.get_json(silent=True)
    if not data or "url" not in data:
        return jsonify({"error": "Missing url"}), 400

    url = data["url"].strip()
    if not is_valid_tiktok_url(url):
        return jsonify({"error": "Invalid TikTok URL"}), 400

    # Dossier temporaire isolé (/tmp sur Fly.io)
    temp_dir = tempfile.mkdtemp(prefix="tiktok_mp3_")
    video_path = os.path.join(temp_dir, "video.mp4")
    audio_path = os.path.join(temp_dir, "audio.mp3")

    try:
        # 1️⃣ Télécharger la vidéo (stable)
        download_cmd = [
            sys.executable,
            "-m", "yt_dlp",
            "-f", "bv*+ba/b",
            "--merge-output-format", "mp4",
            "--no-part",
            "--no-playlist",
            "--quiet",
            "-o", video_path,
            url,
        ]

        subprocess.run(
            download_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
        )

        if not os.path.exists(video_path) or os.path.getsize(video_path) < 1024:
            return jsonify({"error": "Downloaded video is empty"}), 500

        # 2️⃣ Extraire et encoder en MP3 (192 kbps)
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-i", video_path,
            "-vn",
            "-acodec", "libmp3lame",
            "-ab", "192k",
            audio_path,
        ]

        subprocess.run(
            ffmpeg_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=True,
        )

        if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 1024:
            return jsonify({
                "error": "MP3 extraction failed",
                "reason": "No audio track or ffmpeg error"
            }), 409

        # 3️⃣ Streaming MP3 AVEC Content-Length
        mp3_size = os.path.getsize(audio_path)

        def generate():
            with open(audio_path, "rb") as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    yield chunk

        return Response(
            stream_with_context(generate()),
            content_type="audio/mpeg",
            headers={
                "Content-Disposition": "attachment; filename=tiktok_audio.mp3",
                "Content-Length": str(mp3_size),  # ✅ essentiel pour la progression
                "Cache-Control": "no-store",
                "Accept-Ranges": "none",
            },
        )

    except subprocess.CalledProcessError as e:
        return jsonify({
            "error": "Video download or MP3 encoding failed",
            "details": e.stderr.decode(errors="ignore"),
        }), 500

    finally:
        # 4️⃣ Nettoyage GARANTI
        shutil.rmtree(temp_dir, ignore_errors=True)


# -----------------------------
# Healthcheck
# -----------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# -----------------------------
# Run
# -----------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, threaded=True)















