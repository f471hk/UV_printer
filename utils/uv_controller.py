# utils/uv_controller.py
"""
Class definition for controlling the Agiltron UV light source via serial commands.
Based on original code by Fatih Kocabas for Bio-IRL December 2024.
Includes logging and connection status check.
"""

import serial
import time
import logging

class UVcontroller:
    # Written by Fatih Kocabas for Bio-IRL December 2024,
    # Class to control Agiltron 4 head UV.
    # Only UV1 output is controlled and only on off an connection status code is applicable.
    def __init__(self, port="COM8", baudrate=9600):
        """
        Initializes the UV controller interface.

        Args:
            port (str): The serial COM port to connect to (e.g., "COM8").
            baudrate (int): The serial communication baud rate.
        """
        self.port = port
        self.baudrate = baudrate
        self.serial = None
        self._is_connected = False # Internal flag
        logging.debug(f"UVcontroller instance created for port {self.port}")

    def connect(self):
        """Establishes serial connection to the UV controller."""
        if self.serial and self.serial.is_open:
            logging.warning(f"UV controller already connected to {self.port}.")
            self._is_connected = True
            return True
        try:
            self.serial = serial.Serial(self.port, self.baudrate, timeout=1, stopbits=1)
            logging.info(f"Connected to UV controller on {self.port}.")
            self._is_connected = True
            return True # Indicate success
        except serial.SerialException as e:
            logging.error(f"Failed to connect to UV controller on {self.port}: {e}")
            self.serial = None; self._is_connected = False
            return False # Indicate failure
        except Exception as e:
             logging.error(f"An unexpected error occurred during UV connect on {self.port}: {e}")
             self.serial = None; self._is_connected = False
             return False

    def disconnect(self):
        """Closes the serial connection."""
        if self.serial and self.serial.is_open:
            try:
                self.serial.close()
                logging.info(f"Disconnected from UV controller on {self.port}.")
            except Exception as e:
                 logging.error(f"Error during UV disconnect from {self.port}: {e}")
            finally:
                 self.serial = None
                 self._is_connected = False
        else:
            logging.warning("UV controller already disconnected or not connected.")
        self._is_connected = False

    def send_command(self, command: bytes) -> bytes:
        """Sends a command and reads response. Returns empty bytes on failure."""
        if not self.is_connected(): # Use the helper method
            logging.error("Cannot send command: UV controller not connected.")
            return b''
        try:
            self.serial.reset_input_buffer(); self.serial.reset_output_buffer()
            bytes_written = self.serial.write(command)
            logging.debug(f"Sent {bytes_written} bytes: {command.hex()} to {self.port}")
            time.sleep(1.0) # Device processing time
            response = self.serial.read_all()
            logging.debug(f"Received {len(response)} bytes: {response.hex()} from {self.port}")
            return response
        except serial.SerialTimeoutException:
             logging.warning(f"Timeout sending/receiving UV command {command.hex()} on {self.port}")
             return b''
        except serial.SerialException as e:
             logging.error(f"Serial error sending/receiving UV command {command.hex()} on {self.port}: {e}")
             return b''
        except Exception as e:
             logging.error(f"Unexpected error during UV send/receive on {self.port}: {e}")
             return b''

    def uv_port_status(self):
        """Checks the status of the UV port (presumably UV1)."""
        cmd = bytes([0xA5, 0xC4, 0x00, 0x69])
        response = self.send_command(command=cmd)
        if not response: return None
        response_hex = response.hex()
        try:
            status_char = response_hex[-1]
            is_on = (status_char == '1')
            logging.info(f"UV port status check response: {response_hex}, Interpreted as ON: {is_on}")
            return is_on
        except IndexError:
             logging.error(f"Could not parse UV status from empty/invalid response: {response_hex}")
             return None
        except Exception as e:
             logging.error(f"Error parsing UV status response {response_hex}: {e}")
             return None

    def uv_on(self):
        """Turns UV port 1 ON."""
        cmd = bytes([0xA5, 0xC0, 0x01, 0x66])
        response = self.send_command(command=cmd)
        if not response:
             logging.error("Failed to send UV ON command or received no response.")
             return False
        response_hex = response.hex()
        logging.info(f"UV ON command sent. Response: {response_hex}")
        return True # Assume success if command sent

    def uv_off(self):
        """Turns UV port 1 OFF."""
        cmd = bytes([0xA5, 0xC1, 0x01, 0x67])
        response = self.send_command(command=cmd)
        if not response:
             logging.error("Failed to send UV OFF command or received no response.")
             return False
        response_hex = response.hex()
        logging.info(f"UV OFF command sent. Response: {response_hex}")
        return True # Assume success if command sent

    # --- HERE IS THE REQUIRED METHOD ---
    def is_connected(self):
        """Checks if the serial port is configured and currently open."""
        # Checks internal flag AND actual serial port status
        return self._is_connected and self.serial and self.serial.is_open
    # --- END OF REQUIRED METHOD ---

# (Optional standalone test block remains the same)
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.info("Testing UVcontroller standalone...")
    test_port = "COM8"
    uv = UVcontroller(port=test_port)
    if uv.connect():
        logging.info(f"Connection successful. Is connected? {uv.is_connected()}")
        status = uv.uv_port_status()
        logging.info(f"Initial UV Status: {status}")
        if uv.uv_on():
            time.sleep(2); status = uv.uv_port_status()
            logging.info(f"UV Status after ON: {status}")
            uv.uv_off()
            time.sleep(2); status = uv.uv_port_status()
            logging.info(f"UV Status after OFF: {status}")
        uv.disconnect()
        logging.info(f"After disconnect. Is connected? {uv.is_connected()}")
    else: logging.error(f"Failed to connect to UV controller on {test_port}.")
    logging.info("UVcontroller standalone test finished.")