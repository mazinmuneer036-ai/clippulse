import os
import yt_dlp
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from moviepy.editor import VideoFileClip
import stripe
import assemblyai as aai

app = Flask(__name__)
CORS(app)

OUTPUT_DIR = "processed_clips"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Configure developer keys using server environment variables
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
aai.settings.api_key = os.environ.get("ASSEMBLYAI_API_KEY")

def find_most_popular_timestamps(video_url):
    ydl_opts = {'keepvideo': False, 'extract_flat': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=False)
        heatmap = info.get('heatmap')
        
        if not heatmap:
            return [15.0, 60.0]
            
        sorted_heatmap = sorted(heatmap, key=lambda x: x.get('value', 0), reverse=True)
        top_moments = []
        for point in sorted_heatmap:
            t = point.get('start_time', 0)
            if not any(abs(t - existing) < 45 for existing in top_moments):
                top_moments.append(t)
            if len(top_moments) == 2:
                break
                
        return top_moments if len(top_moments) == 2 else [15.0, 60.0]

@app.route('/process-clips', methods=['POST'])
def process_clips():
    data = request.json
    url = data.get('url')
    
    if not url:
        return jsonify({"success": False, "message": "Missing video link"}), 400

    try:
        timestamps = find_most_popular_timestamps(url)
        ydl_file_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
            'outtmpl': 'raw_source.mp4',
            'overwrites': True
        }
        with yt_dlp.YoutubeDL(ydl_file_opts) as ydl:
            ydl.download([url])
        
        clip_paths = []
        master_video = VideoFileClip("raw_source.mp4")
        
        for idx, start_time in enumerate(timestamps):
            duration = 30 
            end_time = min(start_time + duration, master_video.duration)
            sub_clip = master_video.subclip(start_time, end_time)
            
            original_w, original_h = sub_clip.size
            target_w = int(original_h * (9 / 16))
            x1 = (original_w - target_w) // 2
            x2 = x1 + target_w
            
            cropped_clip = sub_clip.crop(x1=x1, y1=0, x2=x2, y2=original_h)
            filename = f"viral_short_{idx+1}.mp4"
            filepath = os.path.join(OUTPUT_DIR, filename)
            
            cropped_clip.write_videofile(
                filepath, 
                codec="libx264", 
                audio_codec="aac",
                threads=2
            )
            clip_paths.append(f"{request.host_url}download/{filename}")
            
        master_video.close()
        return jsonify({"success": True, "clips": clip_paths})
        
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': os.environ.get("STRIPE_PRICE_ID"), 
                'quantity': 1,
            }],
            mode='subscription',
            success_url=request.host_url + '?status=success',
            cancel_url=request.host_url + '?status=canceled',
        )
        return jsonify({'id': checkout_session.id})
    except Exception as e:
        return jsonify(error=str(e)), 403

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory(OUTPUT_DIR, filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
