from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
import subprocess
import os
import sys

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
def capture_api(request):
    """
    Called by Angular Frontend.
    Triggers the capture_processing.py script located in the project root.
    """
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir) 
        script_path = os.path.join(project_root, "capture_processing.py")

        if not os.path.exists(script_path):
            return JsonResponse({
                "status": "error",
                "message": f"Script not found at {script_path}"
            }, status=500)

        result = subprocess.run(
            [sys.executable, script_path], 
            capture_output=True,
            text=True,
            check=True
        )

        return JsonResponse({
            "status": "success",
            "message": "Capture successful and sent to server.",
            "logs": result.stdout
        })

    except subprocess.CalledProcessError as e:
        return JsonResponse({
            "status": "error",
            "message": "Capture script failed.",
            "error_logs": e.stderr
        }, status=500)

    except Exception as e:
        return JsonResponse({
            "status": "error",
            "message": str(e)
        }, status=500)
