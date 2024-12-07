import cv2
from picamera2 import Picamera2, Preview
import time

# Initialize camera
picam2 = Picamera2()
config = picam2.create_preview_configuration()
picam2.configure(config)
picam2.start()

# Set initial camera parameters
picam2.set_controls({"ExposureTime": 1000, "AnalogueGain": 1.0})

# Function to update camera controls based on user input
def update_camera_settings():
    print("\nAdjust Camera Settings:")
    print("1. Set Brightness (range: -1.0 to 1.0)")
    print("2. Set Contrast (range: -1.0 to 1.0)")
    print("3. Set Saturation (range: -1.0 to 1.0)")
    print("4. Set Exposure Time (microseconds)")
    print("5. Set Analogue Gain (range: 1.0 to 16.0)")
    print("6. Exit settings menu")
    option = input("Enter the number of the setting you want to adjust: ")

    if option == "1":
        brightness = float(input("Enter brightness (-1.0 to 1.0): "))
        picam2.set_controls({"Brightness": brightness})
    elif option == "2":
        contrast = float(input("Enter contrast (-1.0 to 1.0): "))
        picam2.set_controls({"Contrast": contrast})
    elif option == "3":
        saturation = float(input("Enter saturation (-1.0 to 1.0): "))
        picam2.set_controls({"Saturation": saturation})
    elif option == "4":
        exposure_time = int(input("Enter exposure time (in microseconds): "))
        picam2.set_controls({"ExposureTime": exposure_time})
    elif option == "5":
        gain = float(input("Enter analogue gain (1.0 to 16.0): "))
        picam2.set_controls({"AnalogueGain": gain})
    elif option == "6":
        print("Exiting settings menu.")
        return
    else:
        print("Invalid option.")
        
    time.sleep(1)  # Give some time for settings to apply

# Main loop for live view and settings adjustments
try:
    while True:
        # Capture frame
        frame = picam2.capture_array()
        
        # Display the frame
        cv2.imshow("Live View", frame)

        # Check for user input
        key = cv2.waitKey(1) & 0xFF
        if key == ord('s'):
            update_camera_settings()
        elif key == ord('q'):
            print("Exiting live view.")
            break

except KeyboardInterrupt:
    print("Interrupted by user. Exiting...")

finally:
    # Clean up
    cv2.destroyAllWindows()
    picam2.stop()
