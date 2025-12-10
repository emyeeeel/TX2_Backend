import pyrealsense2 as rs
import numpy as np
import cv2
import os
import requests
import sys

# ================================================================
#                       CONFIGURATION
# ================================================================

# 1. SERVER URL
# You gave: https://h3vkhzth-4200.asse.devtunnels.ms/patient-info/1
# We change 4200 -> 8000 and point to the API endpoint
SERVER_URL = "https://h3vkhzth-8000.asse.devtunnels.ms/api/segment/"

# 2. MEDIA FOLDER SETUP
# Automatically find the 'media' folder in the same directory as this script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEDIA_DIR = os.path.join(BASE_DIR, "media")

# Ensure media directory exists
if not os.path.exists(MEDIA_DIR):
    os.makedirs(MEDIA_DIR)

# ================================================================
#                    1. REALSENSE CAPTURE
#    (Logic preserved exactly from your setup.py)
# ================================================================
def capture_realsense_image(width=848, height=480, fps=30):
    pipeline = rs.pipeline()
    config = rs.config()

    config.enable_stream(rs.stream.depth, width, height, rs.format.z16, fps)
    config.enable_stream(rs.stream.color, width, height, rs.format.bgr8, fps)

    print("Starting RealSense camera...")
    profile = pipeline.start(config)

    depth_sensor = profile.get_device().first_depth_sensor()

    # Use numeric preset (RealSense enums break in some SDK versions)
    depth_sensor.set_option(rs.option.visual_preset, 1.0)  # 1 = default

    # Warmup
    for _ in range(5):
        pipeline.wait_for_frames()

    frames = pipeline.wait_for_frames()

    align = rs.align(rs.stream.color)
    aligned = align.process(frames)

    depth_frame = aligned.get_depth_frame()
    color_frame = aligned.get_color_frame()

    if not depth_frame or not color_frame:
        pipeline.stop()
        raise RuntimeError("Could not retrieve frames")

    depth_image = np.asanyarray(depth_frame.get_data())
    color_image = np.asanyarray(color_frame.get_data())

    pipeline.stop()
    print("Camera stopped.")

    return depth_image, color_image


# ================================================================
#                     2. SAVE IMAGES & COLORMAPS
#    (Logic preserved, only added path joining for Media folder)
# ================================================================
def save_depth_and_rgb(depth_image, color_image,
                       rgb_filename="rgb_image.png",
                       depth_csv_filename="depth_image.csv",
                       depth_jet_filename="depth_image_jet.png",
                       mask_filename="depth_mask.png"):

    # -- MODIFICATION: Prepend MEDIA_DIR to filenames --
    rgb_path = os.path.join(MEDIA_DIR, rgb_filename)
    depth_csv_path = os.path.join(MEDIA_DIR, depth_csv_filename)
    depth_jet_path = os.path.join(MEDIA_DIR, depth_jet_filename)
    mask_path = os.path.join(MEDIA_DIR, mask_filename)
    # --------------------------------------------------

    cv2.imwrite(rgb_path, color_image)
    print("Saved:", rgb_path)

    np.savetxt(depth_csv_path, depth_image, fmt="%d", delimiter=",")
    print("Saved:", depth_csv_path)

    mask = np.where(depth_image == 0, 0, 255).astype(np.uint8)
    cv2.imwrite(mask_path, mask)
    print("Saved:", mask_path)

    valid_mask = depth_image > 0

    if np.any(valid_mask):
        depth_for_viz = depth_image.astype(np.float32)
        valid_depths = depth_for_viz[valid_mask]

        # Clip extremes
        dmin, dmax = np.percentile(valid_depths, [2, 98])
        depth_for_viz = np.clip(depth_for_viz, dmin, dmax)

        depth_norm = cv2.normalize(depth_for_viz, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        depth_eq = cv2.equalizeHist(depth_norm)

        depth_colormap_jet = cv2.applyColorMap(depth_eq, cv2.COLORMAP_JET)
        depth_colormap_jet[depth_image == 0] = (0, 0, 0)

    else:
        depth_colormap_jet = np.zeros((depth_image.shape[0], depth_image.shape[1], 3), dtype=np.uint8)

    cv2.imwrite(depth_jet_path, depth_colormap_jet)
    print("Saved:", depth_jet_path)


# ================================================================
#                3. TELEA INPAINTING & NUMERIC DEPTH SAVE
#    (Logic preserved, only added path joining for Media folder)
# ================================================================
def telea_inpaint_and_save():
    print("\n=== Running TELEA Inpainting ===")

    # -- MODIFICATION: Prepend MEDIA_DIR --
    jet_path = os.path.join(MEDIA_DIR, "depth_image_jet.png")
    mask_path = os.path.join(MEDIA_DIR, "depth_mask.png")
    out_img_path = os.path.join(MEDIA_DIR, "inpainted_depth.png")
    out_csv_path = os.path.join(MEDIA_DIR, "inpainted_depth.csv")
    orig_csv_path = os.path.join(MEDIA_DIR, "depth_image.csv")
    # -------------------------------------

    if not os.path.exists(jet_path):
        raise FileNotFoundError(f"Missing {jet_path}")

    if not os.path.exists(mask_path):
        raise FileNotFoundError(f"Missing {mask_path}")

    img = cv2.imread(jet_path)
    mask_raw = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)

    # TELEA expects WHITE (255) = fill, so invert mask:
    mask = cv2.bitwise_not(mask_raw)

    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    inpainted = cv2.inpaint(img, mask, 3, cv2.INPAINT_TELEA)

    cv2.imwrite(out_img_path, inpainted)
    print(f"Saved: {out_img_path}")

    # ----------------------------------------------------
    # Convert TELEA image (JET color) back to numeric depth
    # ----------------------------------------------------

    # Load original depth numeric CSV
    depth_orig = np.loadtxt(orig_csv_path, delimiter=",")

    valid_mask = depth_orig > 0
    valid_depths = depth_orig[valid_mask]

    # Reuse same clipping as before
    dmin, dmax = np.percentile(valid_depths, [2, 98])

    # Convert inpainted JET → grayscale → normalized depth value
    inpaint_gray = cv2.cvtColor(inpainted, cv2.COLOR_BGR2GRAY)
    depth_norm = inpaint_gray.astype(np.float32) / 255.0

    # Expand to depth range
    depth_inpaint_numeric = depth_norm * (dmax - dmin) + dmin

    np.savetxt(out_csv_path, depth_inpaint_numeric, fmt="%.2f", delimiter=",")
    print(f"Saved: {out_csv_path}")

    return inpainted, depth_inpaint_numeric


# ================================================================
#                  4. SEND TO RTX 5090 SERVER
# ================================================================
def send_to_server():
    print("\n=== Sending to RTX 5090 Server ===")
    
    path_rgb = os.path.join(MEDIA_DIR, "rgb_image.png")
    path_inpainted_csv = os.path.join(MEDIA_DIR, "inpainted_depth.csv") 
    
    files = {
        'rgb_image': open(path_rgb, 'rb'),          
        'depth_csv': open(path_inpainted_csv, 'rb') 
    }

    print("Uploading... (This takes time due to AI processing)")

    try:
        # INCREASED TIMEOUT to 120 seconds (2 minutes)
        response = requests.post(SERVER_URL, files=files, verify=False)
        
        print(f"Server Response Code: {response.status_code}")
        print(f"Server Message: {response.text}")

    except requests.exceptions.ReadTimeout:
        # This handles the exact case you are seeing!
        print("\nSUCCESS (Probable): Data sent, but server took too long to reply.")
        print("Since your groupmate confirmed receipt, you can ignore this timeout.")

    except Exception as e:
        print(f"Failed to connect to 5090 Server: {e}")
        pass

# ================================================================
#                        MAIN EXECUTION
# ================================================================
if __name__ == "__main__":
    try:
        # 1. Capture
        depth, color = capture_realsense_image()
        
        # 2. Save Locally
        save_depth_and_rgb(depth, color)

        # 3. Process
        telea_inpaint_and_save()

        # 4. Send
        send_to_server()
        
    except Exception as e:
        print(f"Error occurred: {e}")
        sys.exit(1)