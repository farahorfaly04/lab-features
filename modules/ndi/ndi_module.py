"""Simplified NDI Module for Lab Platform device agents."""

import logging
import os
import shlex
import signal
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, Any, Optional

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


class ProcessManager:
    """Manages NDI processes with proper cleanup."""
    
    def __init__(self, logger: logging.Logger):
        self.log = logger
        self.processes: Dict[str, int] = {}
    
    def start_process(self, name: str, cmd: str, env: Dict[str, str]) -> bool:
        """Start a named process."""
        try:
            self.stop_process(name)  # Stop existing process
            
            args = shlex.split(cmd) if isinstance(cmd, str) else cmd
            proc = subprocess.Popen(
                args,
                preexec_fn=os.setsid,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
            
            self.processes[name] = proc.pid
            self.log.info(f"Started {name} process (PID: {proc.pid})")
            return True
            
        except Exception as e:
            self.log.error(f"Failed to start {name}: {e}")
            return False
    
    def stop_process(self, name: str) -> bool:
        """Stop a named process."""
        pid = self.processes.get(name)
        if not pid:
            return True
        
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGTERM)
            
            # Wait for graceful shutdown
            for _ in range(20):  # 2 second timeout
                try:
                    os.killpg(pgid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.1)
            else:
                # Force kill if still running
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            
            del self.processes[name]
            self.log.info(f"Stopped {name} process (PID: {pid})")
            return True
            
        except Exception as e:
            self.log.error(f"Failed to stop {name}: {e}")
            return False
    
    def stop_all(self) -> None:
        """Stop all managed processes."""
        for name in list(self.processes.keys()):
            self.stop_process(name)
    
    def get_status(self) -> Dict[str, Any]:
        """Get status of all processes."""
        status = {}
        for name, pid in self.processes.items():
            try:
                os.kill(pid, 0)  # Check if process exists
                status[name] = {"pid": pid, "status": "running"}
            except ProcessLookupError:
                status[name] = {"pid": pid, "status": "stopped"}
        return status


class NDIModule(Module):
    """Simplified NDI module for video streaming."""
    
    name = "ndi"

    def __init__(self, device_id: str, cfg: Dict[str, Any] = None):
        super().__init__(device_id, cfg)
        self.log = self._setup_logger()
        self.process_manager = ProcessManager(self.log)
        self.current_source: Optional[str] = None

    def _setup_logger(self) -> logging.Logger:
        """Setup module-specific logging."""
        logger = logging.getLogger(f"ndi.{self.device_id}")
        if logger.handlers:
            return logger
        
        logger.setLevel(logging.INFO)
        log_path = Path(self.cfg.get("log_file", f"/tmp/ndi_{self.device_id}.log"))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        handler = RotatingFileHandler(str(log_path), maxBytes=1_000_000, backupCount=3)
        formatter = logging.Formatter("%(asctime)sZ %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
        formatter.converter = time.gmtime
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False
        
        return logger

    def on_agent_connect(self) -> None:
        """Setup environment on agent connect."""
        ndi_path = self.cfg.get("ndi_path")
        if ndi_path:
            os.environ["NDI_PATH"] = ndi_path
            self.log.info(f"Set NDI_PATH to {ndi_path}")

    def _get_env(self) -> Dict[str, str]:
        """Get environment variables for NDI processes."""
        env = os.environ.copy()
        ndi_path = self.cfg.get("ndi_path")
        if ndi_path:
            env["NDI_PATH"] = ndi_path
        
        # Add any additional environment variables
        ndi_env = self.cfg.get("ndi_env", {})
        if isinstance(ndi_env, dict):
            env.update({str(k): str(v) for k, v in ndi_env.items()})
        
        return env

    def _build_command(self, template: str, **kwargs) -> str:
        """Build command from template with parameter substitution."""
        try:
            return template.format(device_id=self.device_id, **kwargs)
        except KeyError as e:
            raise ValueError(f"Missing parameter for command template: {e}")

    def handle_cmd(self, action: str, params: Dict[str, Any]) -> tuple[bool, str | None, dict]:
        """Handle module commands."""
        self.log.info(f"Handling command: {action} with params: {params}")
        
        try:
            if action == "status":
                return self._handle_status()
            elif action == "start":
                return self._handle_start(params)
            elif action == "stop":
                return self._handle_stop()
            elif action == "restart":
                return self._handle_restart(params)
            elif action == "set_input":
                return self._handle_set_input(params)
            elif action == "record_start":
                return self._handle_record_start(params)
            elif action == "record_stop":
                return self._handle_record_stop()
            elif action == "list_processes":
                return self._handle_list_processes()
            else:
                return False, f"Unknown action: {action}", {}
                
        except Exception as e:
            self.log.error(f"Error handling {action}: {e}")
            return False, str(e), {}

    def _handle_status(self) -> tuple[bool, None, dict]:
        """Get module status."""
        status = {
            "current_source": self.current_source,
            "processes": self.process_manager.get_status(),
            "config": {
                "ndi_path": self.cfg.get("ndi_path"),
                "log_file": self.cfg.get("log_file"),
            }
        }
        return True, None, status

    def _handle_start(self, params: Dict[str, Any]) -> tuple[bool, str | None, dict]:
        """Start NDI viewer."""
        source = params.get("source")
        stream = params.get("stream")
        pipeline = params.get("pipeline")
        
        if pipeline:
            # Use custom pipeline
            cmd = pipeline
        elif stream:
            # Build yuri_simple command
            cmd = f"yuri_simple {stream}"
        elif source:
            # Use configured template
            template = self.cfg.get("start_cmd_template", "ndi-viewer {source}")
            cmd = self._build_command(template, source=source)
        else:
            return False, "No source, stream, or pipeline specified", {}
        
        success = self.process_manager.start_process("viewer", cmd, self._get_env())
        if success:
            self.current_source = source or stream or "custom"
            return True, None, {"started": True, "command": cmd}
        else:
            return False, "Failed to start viewer", {}

    def _handle_stop(self) -> tuple[bool, None, dict]:
        """Stop NDI viewer."""
        self.process_manager.stop_process("viewer")
        self.current_source = None
        return True, None, {"stopped": True}

    def _handle_restart(self, params: Dict[str, Any]) -> tuple[bool, str | None, dict]:
        """Restart NDI viewer."""
        self._handle_stop()
        return self._handle_start(params)

    def _handle_set_input(self, params: Dict[str, Any]) -> tuple[bool, str | None, dict]:
        """Change NDI input source."""
        source = params.get("source")
        if not source:
            return False, "Source parameter required", {}
        
        if self.cfg.get("set_input_restart", True):
            # Restart with new source
            return self._handle_restart({"source": source})
        else:
            # Just update current source (for modules that support dynamic switching)
            self.current_source = source
            return True, None, {"source": source}

    def _handle_record_start(self, params: Dict[str, Any]) -> tuple[bool, str | None, dict]:
        """Start recording NDI stream."""
        source = params.get("source", self.current_source)
        output_path = params.get("output_path", f"/tmp/recording_{self.device_id}.mp4")
        
        if not source:
            return False, "No source available for recording", {}
        
        template = self.cfg.get("record_start_cmd_template", "ndi-recorder -i {source} -o {output_path}")
        cmd = self._build_command(template, source=source, output_path=output_path)
        
        success = self.process_manager.start_process("recorder", cmd, self._get_env())
        if success:
            return True, None, {"recording": True, "output": output_path}
        else:
            return False, "Failed to start recording", {}

    def _handle_record_stop(self) -> tuple[bool, None, dict]:
        """Stop recording NDI stream."""
        self.process_manager.stop_process("recorder")
        return True, None, {"recording": False}

    def _handle_list_processes(self) -> tuple[bool, None, dict]:
        """List all NDI processes."""
        return True, None, {"processes": self.process_manager.get_status()}

    def shutdown(self) -> None:
        """Shutdown the module and clean up processes."""
        self.log.info("Shutting down NDI module")
        self.process_manager.stop_all()