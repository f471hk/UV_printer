# utils/helpers.py
"""
Utility functions for the experiment control script.
"""
import logging # Use logging within helpers too if needed

def seconds_to_hms(seconds):
    """Converts a duration in seconds to hours, minutes, and seconds."""
    try:
        seconds = float(seconds)
        if seconds < 0:
            # Log instead of raising ValueError if preferred in a library context
            logging.warning(f"Input seconds ({seconds}) cannot be negative. Returning 0h 0m 0s.")
            # raise ValueError("Input seconds cannot be negative.")
            return 0, 0, 0
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds_rem = divmod(remainder, 60)
        # Use round() for potentially fractional seconds if higher precision is needed
        return int(hours), int(minutes), int(round(seconds_rem))
    except (TypeError, ValueError) as e:
        logging.error(f"Error converting seconds to H:M:S: {e}")
        return 0, 0, 0

# Add other general helper functions here if needed in the future.