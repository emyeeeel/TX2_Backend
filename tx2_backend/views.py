from django.http import FileResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import json
import subprocess
import os
import sys
import cv2
import numpy as np
import pyrealsense2 as rs
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEDIA_DIR = os.path.join(BASE_DIR, "../media/meals")

os.makedirs(MEDIA_DIR, exist_ok=True)

# Global variable to store the weight
current_live_weight = 0.0

@csrf_exempt
def set_weight(request):
    global current_live_weight
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            current_live_weight = data.get('weight', 0.0)
            return JsonResponse({'status': 'ok'})
        except:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
    return JsonResponse({'error': 'POST only'}, status=405)

def get_weight(request):
    return JsonResponse({'weight': current_live_weight})

# ==========================================================
#                   NEW CAPTURE API
# ==========================================================

@csrf_exempt   # <-- THIS FIXES YOUR 403 ERROR
def capture_api(request): #let this receive url then print the url received
    """
    Called by Angular Frontend.
    Triggers either capture_before.py or capture_after.py based on the segment URL.
    Routes based on URL ending: /before -> capture_before.py, /after -> capture_after.py
    """
    try:
        segment_url = None
        
        # Receive URL from request
        if request.method == 'POST':
            try:
                data = json.loads(request.body)
                segment_url = data.get('segment_url', None)
                
                # Print the received URL
                if segment_url:
                    print(f"✓ Received URL from frontend: {segment_url}")
                else:
                    print("ℹ No segment_url provided in request")
                    
            except json.JSONDecodeError:
                print("⚠ Failed to parse JSON from request body")
        elif request.method == 'GET':
            # Check for URL in query parameters
            segment_url = request.GET.get('segment_url', None)
            if segment_url:
                print(f"✓ Received URL from query params: {segment_url}")
            else:
                print("ℹ No segment_url in query parameters")
        
        # Determine which script to run based on URL
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)
        
        script_name = "capture_before.py"  # Default
        capture_type = "before"  # Default
        
        if segment_url:
            if segment_url.endswith('/before'):
                script_name = "capture_before.py"
                capture_type = "before"
                print(f"🎯 Detected 'before' endpoint - using {script_name}")
            elif segment_url.endswith('/after'):
                script_name = "capture_after.py"
                capture_type = "after"
                print(f"🎯 Detected 'after' endpoint - using {script_name}")
            else:
                print(f"⚠ Unknown endpoint in URL: {segment_url} - defaulting to 'before'")
        
        script_path = os.path.join(project_root, script_name)

        if not os.path.exists(script_path):
            return JsonResponse({
                "status": "error",
                "message": f"Script not found at {script_path}"
            }, status=500)

        # Pass the URL to the appropriate capture script
        command = [sys.executable, script_path]
        if segment_url:
            command.extend(['--segment-url', segment_url])
            print(f"🚀 Running {script_name} with URL: {segment_url}")
        else:
            print(f"🚀 Running {script_name} without URL")

        result = subprocess.run(
            command, 
            capture_output=True,
            text=True,
            check=True
        )

        return JsonResponse({
            "status": "success",
            "message": f"Capture {capture_type} successful and sent to server.",
            "received_url": segment_url,
            "capture_type": capture_type,
            "script_used": script_name,
            "logs": result.stdout
        })

    except subprocess.CalledProcessError as e:
        return JsonResponse({
            "status": "error",
            "message": f"Capture script failed.",
            "error_logs": e.stderr
        }, status=500)

    except Exception as e:
        return JsonResponse({
            "status": "error",
            "message": str(e)
        }, status=500)


def capture_meal_rgb(width=848, height=480, fps=30):
    """
    Capture a single RGB frame from Intel RealSense.
    Returns: numpy array (BGR image)
    """
    pipeline = rs.pipeline()
    config = rs.config()

    # Enable RGB stream only
    config.enable_stream(
        rs.stream.color,
        width,
        height,
        rs.format.bgr8,
        fps
    )

    try:
        pipeline.start(config)

        # Warm-up frames (critical for RealSense)
        for _ in range(5):
            pipeline.wait_for_frames()

        frames = pipeline.wait_for_frames()
        color_frame = frames.get_color_frame()

        if not color_frame:
            raise RuntimeError("Failed to capture RGB frame")

        # Convert to numpy array (OpenCV BGR format)
        color_image = np.asanyarray(color_frame.get_data())

        return color_image

    finally:
        # Always release the camera
        pipeline.stop()


@csrf_exempt
def capture_meal(request):
    try:
        # Ensure RealSense device exists
        ctx = rs.context()
        if len(ctx.devices) == 0:
            return JsonResponse({
                "status": "error",
                "message": "No RealSense device detected"
            }, status=500)

        # Capture RGB image
        rgb_image = capture_meal_rgb()

        # Save as captured_meal.jpg (overwrite-safe timestamp)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"captured_meal_{timestamp}.jpg"
        file_path = os.path.join(MEDIA_DIR, filename)

        cv2.imwrite(file_path, rgb_image)

        # Return image to frontend
        return FileResponse(
            open(file_path, "rb"),
            content_type="image/jpeg",
            filename=filename
        )

    except Exception as e:
        print("❌ capture_meal error:", repr(e))
        return JsonResponse({
            "status": "error",
            "message": str(e)
        }, status=500)
