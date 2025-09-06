"""Simplified Projector Module for Lab Platform device agents."""

import glob
import logging
import platform
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, Any, Optional

import serial

try:
    from lab_agent.base import Module
except ImportError:
    # Add device agent to path if not installed
    possible_paths = [
        Path(__file__).resolve().parents[3] / "device-agent" / "src",
        Path.cwd() / "device-agent" / "src",
        Path("/opt/lab-platform/device-agent/src"),
    ]
    
    for path in possible_paths:
        if path.exists():
            sys.path.insert(0, str(path))
            break
    
    from lab_agent.base import Module


class SerialManager:
    """Manages serial connection to projector."""
    
    def __init__(self, logger: logging.Logger, config: Dict[str, Any]):
        self.log = logger
        self.config = config
        self.connection: Optional[serial.Serial] = None
    
    def find_device(self) -> Optional[str]:
        """Find the first available USB serial device."""
        system = platform.system().lower()
        patterns = []
        
        if system == 'darwin':
            patterns = ['/dev/tty.usbserial*', '/dev/tty.usbmodem*', '/dev/tty.SLAB_USBtoUART*']
        elif system == 'linux':
            patterns = ['/dev/ttyUSB*', '/dev/ttyACM*']
        elif system == 'windows':
            patterns = ['COM*']
        
        for pattern in patterns:
            devices = glob.glob(pattern)
            if devices:
                return devices[0]
        
        return None
    
    def connect(self) -> bool:
        """Establish serial connection."""
        if self.connection and self.connection.is_open:
            return True
        
        port = self.config.get("serial_port")
        if not port:
            port = self.find_device()
            if not port:
                self.log.error("No serial device found")
                return False
        
        try:
            self.connection = serial.Serial(
                port=port,
                baudrate=self.config.get("baudrate", 9600),
                timeout=self.config.get("timeout", 1.0)
            )
            self.log.info(f"Connected to projector on {port}")
            return True
            
        except Exception as e:
            self.log.error(f"Failed to connect to {port}: {e}")
            return False
    
    def disconnect(self) -> None:
        """Close serial connection."""
        if self.connection and self.connection.is_open:
            self.connection.close()
            self.log.info("Disconnected from projector")
    
    def send_command(self, command: str) -> bool:
        """Send command to projector."""
        if not self.connect():
            return False
        
        try:
            self.connection.write(command.encode())
            self.log.info(f"Sent command: {command.strip()}")
            return True
        except Exception as e:
            self.log.error(f"Failed to send command: {e}")
            return False


class ProjectorModule(Module):
    """Simplified projector control module."""
    
    name = "projector"
    
    # Standard projector commands
    COMMANDS = {
        # Power
        "ON": "~0000 1\r",
        "OFF": "~0000 0\r",
        
        # Inputs
        "HDMI1": "~00305 1\r",
        "HDMI2": "~0012 15\r",
        
        # Aspect ratio
        "4:3": "~0060 1\r",
        "16:9": "~0060 2\r",
        
        # Navigation
        "UP": "~00140 10\r",
        "DOWN": "~00140 14\r",
        "LEFT": "~00140 11\r",
        "RIGHT": "~00140 13\r",
        "ENTER": "~00140 12\r",
        "MENU": "~00140 20\r",
        "BACK": "~00140 74\r",
    }
    
    # Commands that take parameters
    PARAMETRIC_COMMANDS = {
        "H-IMAGE-SHIFT": "~0063 {value}\r",  # -100 to 100
        "V-IMAGE-SHIFT": "~0064 {value}\r",  # -100 to 100
        "H-KEYSTONE": "~0065 {value}\r",     # -40 to 40
        "V-KEYSTONE": "~0066 {value}\r",     # -40 to 40
    }

    def __init__(self, device_id: str, cfg: Dict[str, Any] = None):
        super().__init__(device_id, cfg)
        self.log = self._setup_logger()
        self.serial_manager = SerialManager(self.log, self.cfg)
        self.current_state = {"power": "unknown", "input": "unknown"}

    def _setup_logger(self) -> logging.Logger:
        """Setup module-specific logging."""
        logger = logging.getLogger(f"projector.{self.device_id}")
        if logger.handlers:
            return logger
        
        logger.setLevel(logging.INFO)
        log_path = Path(self.cfg.get("log_file", f"/tmp/projector_{self.device_id}.log"))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        handler = RotatingFileHandler(str(log_path), maxBytes=1_000_000, backupCount=3)
        formatter = logging.Formatter("%(asctime)sZ %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
        formatter.converter = time.gmtime
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False
        
        return logger

    def handle_cmd(self, action: str, params: Dict[str, Any]) -> tuple[bool, str | None, dict]:
        """Handle module commands."""
        self.log.info(f"Handling command: {action} with params: {params}")
        
        try:
            if action == "status":
                return self._handle_status()
            elif action == "power":
                return self._handle_power(params)
            elif action == "input":
                return self._handle_input(params)
            elif action == "command":
                return self._handle_command(params)
            elif action == "navigate":
                return self._handle_navigate(params)
            elif action == "adjust":
                return self._handle_adjust(params)
            else:
                return False, f"Unknown action: {action}", {}
                
        except Exception as e:
            self.log.error(f"Error handling {action}: {e}")
            return False, str(e), {}

    def _handle_status(self) -> tuple[bool, None, dict]:
        """Get module status."""
        status = {
            "state": self.current_state,
            "serial_connected": self.serial_manager.connection is not None and self.serial_manager.connection.is_open,
            "available_commands": list(self.COMMANDS.keys()),
            "parametric_commands": list(self.PARAMETRIC_COMMANDS.keys())
        }
        return True, None, status

    def _handle_power(self, params: Dict[str, Any]) -> tuple[bool, str | None, dict]:
        """Handle power commands."""
        state = params.get("state", "").upper()
        
        if state not in ["ON", "OFF"]:
            return False, "Power state must be 'on' or 'off'", {}
        
        command = self.COMMANDS[state]
        success = self.serial_manager.send_command(command)
        
        if success:
            self.current_state["power"] = state.lower()
            return True, None, {"power": state.lower()}
        else:
            return False, "Failed to send power command", {}

    def _handle_input(self, params: Dict[str, Any]) -> tuple[bool, str | None, dict]:
        """Handle input selection."""
        input_source = params.get("source", "").upper()
        
        if input_source not in ["HDMI1", "HDMI2"]:
            return False, "Input source must be 'hdmi1' or 'hdmi2'", {}
        
        command = self.COMMANDS[input_source]
        success = self.serial_manager.send_command(command)
        
        if success:
            self.current_state["input"] = input_source.lower()
            return True, None, {"input": input_source.lower()}
        else:
            return False, "Failed to send input command", {}

    def _handle_command(self, params: Dict[str, Any]) -> tuple[bool, str | None, dict]:
        """Handle raw command sending."""
        cmd = params.get("cmd", "").upper()
        
        if cmd not in self.COMMANDS:
            return False, f"Unknown command: {cmd}. Available: {list(self.COMMANDS.keys())}", {}
        
        command = self.COMMANDS[cmd]
        success = self.serial_manager.send_command(command)
        
        if success:
            return True, None, {"command_sent": cmd}
        else:
            return False, f"Failed to send command: {cmd}", {}

    def _handle_navigate(self, params: Dict[str, Any]) -> tuple[bool, str | None, dict]:
        """Handle navigation commands."""
        direction = params.get("direction", "").upper()
        nav_commands = ["UP", "DOWN", "LEFT", "RIGHT", "ENTER", "MENU", "BACK"]
        
        if direction not in nav_commands:
            return False, f"Invalid direction. Available: {nav_commands}", {}
        
        command = self.COMMANDS[direction]
        success = self.serial_manager.send_command(command)
        
        if success:
            return True, None, {"navigation": direction.lower()}
        else:
            return False, f"Failed to send navigation command: {direction}", {}

    def _handle_adjust(self, params: Dict[str, Any]) -> tuple[bool, str | None, dict]:
        """Handle parametric adjustment commands."""
        adjustment = params.get("type", "").upper()
        value = params.get("value")
        
        if adjustment not in self.PARAMETRIC_COMMANDS:
            return False, f"Invalid adjustment. Available: {list(self.PARAMETRIC_COMMANDS.keys())}", {}
        
        if value is None:
            return False, "Value parameter required for adjustment commands", {}
        
        try:
            value = int(value)
        except ValueError:
            return False, "Value must be an integer", {}
        
        # Validate value ranges
        if adjustment in ["H-IMAGE-SHIFT", "V-IMAGE-SHIFT"] and not (-100 <= value <= 100):
            return False, "Image shift value must be between -100 and 100", {}
        elif adjustment in ["H-KEYSTONE", "V-KEYSTONE"] and not (-40 <= value <= 40):
            return False, "Keystone value must be between -40 and 40", {}
        
        command = self.PARAMETRIC_COMMANDS[adjustment].format(value=value)
        success = self.serial_manager.send_command(command)
        
        if success:
            return True, None, {"adjustment": adjustment.lower(), "value": value}
        else:
            return False, f"Failed to send adjustment command: {adjustment}", {}

    def shutdown(self) -> None:
        """Shutdown the module and clean up connections."""
        self.log.info("Shutting down projector module")
        self.serial_manager.disconnect()