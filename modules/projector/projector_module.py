"""Projector Module for Lab Platform device agents."""

from typing import Dict, Any
import serial
import glob
import time
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

# Import base module from device agent
# Try multiple import paths for standalone operation
try:
    from lab_agent.base import Module
except ImportError:
    # Add device agent to path if not installed
    possible_paths = [
        Path(__file__).resolve().parents[3] / "device-agent" / "src",  # Development layout
        Path.cwd() / "device-agent" / "src",  # Current directory
        Path("/opt/lab-platform/device-agent/src"),  # System installation
    ]
    
    for path in possible_paths:
        if path.exists():
            sys.path.insert(0, str(path))
            break
    
    try:
        from lab_agent.base import Module
    except ImportError:
        raise ImportError("Could not import lab_agent.base.Module. Ensure lab-agent is installed or available in path.")


class ProjectorModule(Module):
    """Projector control module for RS232/USB serial communication."""
    
    name = "projector"

    # Commands for the projector (from original ascii.py)
    COMMANDS = {
        # Power commands
        "ON": "~0000 1\r",
        "OFF": "~0000 0\r",
        
        # Input selection
        "HDMI1": "~00305 1\r",
        "HDMI2": "~0012 15\r",
        
        # Aspect ratio
        "4:3": "~0060 1\r",
        "16:9": "~0060 2\r",
        
        # Navigation
        "UP": "~00140 10\r",
        "LEFT": "~00140 11\r",
        "ENTER": "~00140 12\r",
        "RIGHT": "~00140 13\r",
        "DOWN": "~00140 14\r",
        "MENU": "~00140 20\r",
        "BACK": "~00140 74\r",
        
        # Dynamic commands (require parameters)
        "H-IMAGE-SHIFT": "~0063 {value}\r",  # horizontal image shift (-100 <= value <= 100)
        "V-IMAGE-SHIFT": "~0064 {value}\r",  # vertical image shift (-100 <= value <= 100)
        "H-KEYSTONE": "~0065 {value}\r",     # horizontal keystone (-40 <= value <= 40)
        "V-KEYSTONE": "~0066 {value}\r",     # vertical keystone (-40 <= value <= 40)
    }

    def __init__(self, device_id: str, cfg: Dict[str, Any] | None = None):
        super().__init__(device_id, cfg)
        self.serial_connection: serial.Serial | None = None
        self._setup_logger()
        self._setup_serial()

    def _setup_logger(self) -> None:
        """Setup module-specific logging."""
        self.log = logging.getLogger(f"projector.{self.device_id}")
        if self.log.handlers:
            return
        
        self.log.setLevel(logging.INFO)
        # Allow config override; fallback to /tmp/projector_<device>.log
        log_path = Path(self.cfg.get("log_file") or f"/tmp/projector_{self.device_id}.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        handler = RotatingFileHandler(str(log_path), maxBytes=1_000_000, backupCount=3)
        fmt = logging.Formatter("%(asctime)sZ %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
        fmt.converter = time.gmtime  # UTC timestamps
        handler.setFormatter(fmt)
        self.log.addHandler(handler)
        self.log.propagate = False

    def _find_usb_serial_device(self) -> str:
        """Find the first available USB serial device."""
        usb_devices = glob.glob('/dev/ttyUSB*')
        if not usb_devices:
            raise RuntimeError("No USB serial device found")
        return usb_devices[0]

    def _setup_serial(self) -> None:
        """Setup serial connection to projector."""
        try:
            # Get serial port from config or auto-discover
            serial_port = self.cfg.get("serial_port")
            if not serial_port and self.cfg.get("auto_discover_port", True):
                serial_port = self._find_usb_serial_device()
            
            if not serial_port:
                self.log.error("No serial port specified and auto-discovery disabled")
                return
            
            baudrate = self.cfg.get("baudrate", 9600)
            timeout = self.cfg.get("timeout", 1.0)
            
            self.serial_connection = serial.Serial(
                port=serial_port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=timeout
            )
            
            self.log.info("Serial connection established: port=%s, baudrate=%d", serial_port, baudrate)
            self.state = "connected"
            self.fields.update({
                "serial_port": serial_port,
                "baudrate": baudrate,
                "connected": True
            })
            
        except Exception as e:
            self.log.error("Failed to setup serial connection: %s", e)
            self.state = "error"
            self.fields.update({"connected": False, "error": str(e)})

    def on_agent_connect(self) -> None:
        """Called when agent connects to orchestrator."""
        self.log.info("Agent connected, projector module ready")

    def _send_command(self, command: str) -> bool:
        """Send command to projector via serial connection."""
        if not self.serial_connection or not self.serial_connection.is_open:
            self.log.error("Serial connection not available")
            return False
        
        try:
            self.serial_connection.write(command.encode('utf-8'))
            self.log.info("Sent command: %s", command.strip())
            return True
        except Exception as e:
            self.log.error("Failed to send command '%s': %s", command.strip(), e)
            return False

    def _read_response(self, timeout: float = 2.0) -> str:
        """Read response from projector."""
        if not self.serial_connection or not self.serial_connection.is_open:
            return ""
        
        try:
            start_time = time.time()
            response_parts = []
            
            while time.time() - start_time < timeout:
                if self.serial_connection.in_waiting > 0:
                    data = self.serial_connection.read(self.serial_connection.in_waiting)
                    response_parts.append(data.decode('ascii', errors='ignore'))
                time.sleep(0.1)
            
            response = ''.join(response_parts)
            if response:
                self.log.info("Received response: %s", response.strip())
            return response
            
        except Exception as e:
            self.log.error("Failed to read response: %s", e)
            return ""

    def shutdown(self) -> None:
        """Shutdown the module and clean up resources."""
        if self.serial_connection and self.serial_connection.is_open:
            self.serial_connection.close()
            self.log.info("Serial connection closed")
        
        self.state = "idle"
        self.fields.update({"connected": False})

    def handle_cmd(self, action: str, params: Dict[str, Any]) -> tuple[bool, str | None, dict]:
        """Handle module commands."""
        self.log.info(
            "handle_cmd: action=%s params=%s", 
            action, 
            {k: ("***" if k in {"password", "token"} else v) for k, v in (params or {}).items()}
        )

        if not self.serial_connection or not self.serial_connection.is_open:
            return False, "Serial connection not available", {}

        if action == "power_on":
            success = self._send_command(self.COMMANDS["ON"])
            if success:
                self.fields["power_state"] = "on"
            return success, None if success else "Failed to send power on command", {"power_state": "on" if success else "unknown"}

        if action == "power_off":
            success = self._send_command(self.COMMANDS["OFF"])
            if success:
                self.fields["power_state"] = "off"
            return success, None if success else "Failed to send power off command", {"power_state": "off" if success else "unknown"}

        if action == "set_input":
            input_source = params.get("input")
            if input_source not in ["HDMI1", "HDMI2"]:
                return False, "Invalid input source. Must be HDMI1 or HDMI2", {}
            
            success = self._send_command(self.COMMANDS[input_source])
            if success:
                self.fields["current_input"] = input_source
            return success, None if success else f"Failed to set input to {input_source}", {"current_input": input_source if success else "unknown"}

        if action == "set_aspect_ratio":
            ratio = params.get("ratio")
            if ratio not in ["4:3", "16:9"]:
                return False, "Invalid aspect ratio. Must be 4:3 or 16:9", {}
            
            success = self._send_command(self.COMMANDS[ratio])
            if success:
                self.fields["aspect_ratio"] = ratio
            return success, None if success else f"Failed to set aspect ratio to {ratio}", {"aspect_ratio": ratio if success else "unknown"}

        if action == "navigate":
            direction = params.get("direction")
            if direction not in ["UP", "DOWN", "LEFT", "RIGHT", "ENTER", "MENU", "BACK"]:
                return False, "Invalid navigation direction", {}
            
            success = self._send_command(self.COMMANDS[direction])
            return success, None if success else f"Failed to send {direction} command", {"last_navigation": direction if success else None}

        if action == "adjust_image":
            adjustment = params.get("adjustment")
            value = params.get("value")
            
            if adjustment not in ["H-IMAGE-SHIFT", "V-IMAGE-SHIFT", "H-KEYSTONE", "V-KEYSTONE"]:
                return False, "Invalid adjustment type", {}
            
            if not isinstance(value, int):
                return False, "Adjustment value must be an integer", {}
            
            # Validate value ranges
            if adjustment in ["H-IMAGE-SHIFT", "V-IMAGE-SHIFT"]:
                if not (-100 <= value <= 100):
                    return False, "Image shift value must be between -100 and 100", {}
            elif adjustment in ["H-KEYSTONE", "V-KEYSTONE"]:
                if not (-40 <= value <= 40):
                    return False, "Keystone value must be between -40 and 40", {}
            
            command = self.COMMANDS[adjustment].format(value=value)
            success = self._send_command(command)
            
            result = {"adjustment": adjustment, "value": value} if success else {}
            return success, None if success else f"Failed to adjust {adjustment}", result

        if action == "send_raw_command":
            command = params.get("command")
            if not command:
                return False, "Raw command cannot be empty", {}
            
            success = self._send_command(command)
            response = self._read_response() if success else ""
            
            return success, None if success else "Failed to send raw command", {"response": response}

        self.log.error("handle_cmd: unknown action=%s", action)
        return False, f"unknown action: {action}", {}
