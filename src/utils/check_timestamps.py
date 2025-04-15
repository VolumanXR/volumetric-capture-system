import json
import numpy as np

def check_intervals(json_data, tolerance=1):
    # Parse the JSON
    timestamps = list(json_data.values())
    
    # Compute time differences between consecutive timestamps (convert to ms)
    intervals = np.diff(timestamps) / 1e6  # Convert nanoseconds to milliseconds
    
    # Define target interval based on 25 FPS (1/25s = 40ms)
    target_interval = 40.0
    upper_threshold = target_interval*1.1 # 80ms (Too long)
    lower_threshold = target_interval *0.8      # 40ms (Too short)

    # Calculate mean interval
    mean_interval = np.mean(intervals)
    
    # Compute deviation in ms
    deviation = np.abs(intervals - target_interval)
    max_deviation = np.max(deviation)
    
    # Find inconsistent intervals
    inconsistent_indices = np.where(deviation > (tolerance * target_interval))[0]
    inconsistent_count = len(inconsistent_indices)
    consistent = inconsistent_count == 0

    # Find frames with excessive duration (> 80ms)
    long_duration_indices = np.where(intervals > upper_threshold)[0]

    # Find frames with too short duration (< 40ms)
    short_duration_indices = np.where(intervals < lower_threshold)[0]

    # Print frames with excessive duration (> 80ms)
    if len(long_duration_indices) > 0:
        print("\n⚠️ Frames with excessively long durations (> 80ms):")
        for idx in long_duration_indices:
            print(f"Frame {idx} → Duration: {intervals[idx]:.3f} ms")

    # Print frames with too short duration (< 40ms)
    if len(short_duration_indices) > 0:
        print("\n⚠️ Frames with too short durations (< 40ms):")
        for idx in short_duration_indices:
            print(f"Frame {idx} → Duration: {intervals[idx]:.3f} ms")

    return mean_interval, max_deviation, inconsistent_count, inconsistent_indices.tolist(), consistent

# Load JSON from a file
with open('hardware-capture\\capture-software\\transfer09\\Sessions\\Abc04\\Abc04_116.json', 'r') as f:
    data = json.load(f)

# Run the check
mean_interval, max_deviation, inconsistent_count, inconsistent_indices, consistent = check_intervals(data)

# Print summary results
print(f"\n📊 Mean Interval: {mean_interval:.3f} ms")
print(f"📈 Max Deviation: {max_deviation:.3f} ms")
print(f"❌ Number of inconsistent intervals: {inconsistent_count}")
print(f"🔍 Inconsistent frame indices: {inconsistent_indices}")
print(f"✅ Intervals are {'consistent' if consistent else 'inconsistent'}")
