import cv2
import numpy as np
import os

def main():
    img_path = "/home/hsr/.gemini/antigravity-ide/brain/41d4f52c-f2ed-4e0b-8e8c-1313f00c857a/cropped_fisheye.png"
    img = cv2.imread(img_path)
    if img is None:
        print("Failed to load cropped_fisheye.png")
        return
    
    h, w = img.shape[:2]
    # Draw circles at front_cx = 300, back_cx = 900, cy = 225
    # Let's try different radii and offsets to find the best fit
    overlay = img.copy()
    
    # Let's draw the default circles
    radius_default = min(w / 4.0, h / 2.0) * 0.96 # 225 * 0.96 = 216
    cv2.circle(overlay, (300, 225), int(radius_default), (0, 255, 0), 2)
    cv2.circle(overlay, (900, 225), int(radius_default), (0, 255, 0), 2)
    
    # Save the overlay image
    out_path = "/home/hsr/.gemini/antigravity-ide/brain/41d4f52c-f2ed-4e0b-8e8c-1313f00c857a/circle_overlay_default.png"
    cv2.imwrite(out_path, overlay)
    print(f"Saved default overlay to {out_path}")

    # Let's also print some stats. Are there black pixels on the left or right?
    # In Theta images, the background around the circles is black.
    # Let's find the bounding box of non-black pixels in left and right halves.
    left_half = img[:, 0:w//2]
    right_half = img[:, w//2:]
    
    gray_left = cv2.cvtColor(left_half, cv2.COLOR_BGR2GRAY)
    gray_right = cv2.cvtColor(right_half, cv2.COLOR_BGR2GRAY)
    
    _, thresh_l = cv2.threshold(gray_left, 15, 255, cv2.THRESH_BINARY)
    _, thresh_r = cv2.threshold(gray_right, 15, 255, cv2.THRESH_BINARY)
    
    contours_l, _ = cv2.findContours(thresh_l, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours_r, _ = cv2.findContours(thresh_r, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    print("Left half contours:")
    for i, c in enumerate(contours_l):
        x, y, w_c, h_c = cv2.boundingRect(c)
        print(f"  Contour {i}: x={x}, y={y}, w={w_c}, h={h_c}")
        
    print("Right half contours:")
    for i, c in enumerate(contours_r):
        x, y, w_c, h_c = cv2.boundingRect(c)
        print(f"  Contour {i}: x={x}, y={y}, w={w_c}, h={h_c}")

if __name__ == "__main__":
    main()
