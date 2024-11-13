import time
import cv2
import numpy as np
import matplotlib.pyplot as plt
from picamera2 import Picamera2

# Function to calculate sharpness based on Laplacian variance
def calculate_sharpness(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    variance = laplacian.var()
    return variance

# Capture images at different lens positions and evaluate sharpness
def find_optimal_focus(lens_positions):
    picam2 = Picamera2()
    config = picam2.create_still_configuration()
    picam2.configure(config)
    picam2.start()

    sharpness_scores = {}

    for lens_position in lens_positions:
        # Set lens position and capture image
        picam2.set_controls({"lens_position": lens_position})
        time.sleep(1)  # Allow time for lens to adjust
        image = picam2.capture_array()  # Capture the image as a NumPy array
        
        # Calculate sharpness
        sharpness = calculate_sharpness(image)
        sharpness_scores[lens_position] = sharpness
        print(f"Lens position {lens_position}: Sharpness = {sharpness}")

    # Find the lens position with the highest sharpness
    optimal_position = max(sharpness_scores, key=sharpness_scores.get)
    print(f"Optimal lens position: {optimal_position} with sharpness {sharpness_scores[optimal_position]}")

    picam2.stop()
    return sharpness_scores, optimal_position

# Define a range of lens positions to test
lens_positions = np.arange(4.0, 6.5, 0.1)  # Adjust range and step size as needed

# Run the focus finding function
sharpness_scores, optimal_focus_position = find_optimal_focus(lens_positions)
print(f"The optimal focus position is: {optimal_focus_position}")

# Plot the sharpness against lens position
lens_positions_list = list(sharpness_scores.keys())
sharpness_values = list(sharpness_scores.values())

plt.plot(lens_positions_list, sharpness_values, marker='o', color='b', label='Sharpness')
plt.xlabel('Lens Position')
plt.ylabel('Sharpness (Laplacian Variance)')
plt.title('Sharpness vs. Lens Position')
plt.axvline(optimal_focus_position, color='r', linestyle='--', label=f'Optimal Position: {optimal_focus_position}')
plt.legend()
plt.grid(True)
plt.show()