"""NDI Module for Lab Platform device agents."""

from typing import Dict, Any
import subprocess, shlex, os, signal, time
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

# Import base module from device agent
sys.path.append(str(Path(__file__).resolve().parents[3] / "device-agent" / "src"))
from lab_agent.base import Module


class NDIModule(Module):
    """NDI (Network Device Interface) module for video streaming."""
    
    name = "ndi"

    def __init__(self, device_id: str, cfg: Dict[str, Any] | None = None):
        super().__init__(device_id, cfg)
        self.viewer_pid: int | None = None
        self.rec_pid: int | None = None
        self._setup_logger()

    def _setup_logger(self) -> None:
        """Setup module-specific logging."""
        self.log = logging.getLogger(f"ndi.{self.device_id}")
        if self.log.handlers:
            return
        
        self.log.setLevel(logging.INFO)
        # Allow config override; fallback to /tmp/ndi_<device>.log
        log_path = Path(self.cfg.get("log_file") or f"/tmp/ndi_{self.device_id}.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        handler = RotatingFileHandler(str(log_path), maxBytes=1_000_000, backupCount=3)
        fmt = logging.Formatter("%(asctime)sZ %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
        fmt.converter = time.gmtime  # UTC timestamps
        handler.setFormatter(fmt)
        self.log.addHandler(handler)
        self.log.propagate = False

    def on_agent_connect(self) -> None:
        """Export NDI_PATH and other environment variables."""
        ndi_path = self.cfg.get("ndi_path")
        ndi_env = self.cfg.get("ndi_env", self.cfg.get("env", {})) or {}
        
        if isinstance(ndi_path, str) and ndi_path:
            os.environ["NDI_PATH"] = ndi_path
        
        if isinstance(ndi_env, dict):
            for k, v in ndi_env.items():
                os.environ[str(k)] = str(v)
        
        self.log.info(
            "agent_connect: exported env NDI_PATH=%s extra=%s", 
            ndi_path, 
            list(ndi_env.keys()) if isinstance(ndi_env, dict) else None
        )

    def _env(self) -> Dict[str, str]:
        """Get environment variables for NDI processes."""
        env = os.environ.copy()
        ndi_path = self.cfg.get("ndi_path")
        if isinstance(ndi_path, str) and ndi_path:
            env["NDI_PATH"] = ndi_path
        return env

    def _spawn(self, cmd: str | list[str]) -> int:
        """Spawn a process and return its PID."""
        args = cmd if isinstance(cmd, list) else shlex.split(cmd)
        proc = subprocess.Popen(
            args,
            preexec_fn=os.setsid,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=self._env(),
        )
        return int(proc.pid)

    def _killpg(self, pid: int, sig: signal.Signals = signal.SIGTERM, grace: float = 2.0) -> None:
        """Kill a process group with graceful timeout."""
        if not pid:
            return
        
        try:
            pgid = os.getpgid(pid)
        except Exception:
            return
        
        try:
            os.killpg(pgid, sig)
            t0 = time.time()
            while time.time() - t0 < grace:
                try:
                    os.killpg(pgid, 0)
                except ProcessLookupError:
                    return
                time.sleep(0.1)
        except ProcessLookupError:
            return
        
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def shutdown(self) -> None:
        """Shutdown the module and clean up processes."""
        if self.rec_pid:
            self.log.info("shutdown: stopping recorder pid=%s", self.rec_pid)
            self._killpg(self.rec_pid, signal.SIGINT)
            self.rec_pid = None
        
        if self.viewer_pid:
            self.log.info("shutdown: stopping viewer pid=%s", self.viewer_pid)
            self._killpg(self.viewer_pid)
            self.viewer_pid = None
        
        self.state = "idle"
        self.fields.update({
            "input": None, 
            "pid": None, 
            "recording": False, 
            "record_pid": None
        })

    def handle_cmd(self, action: str, params: Dict[str, Any]) -> tuple[bool, str | None, dict]:
        """Handle module commands."""
        self.log.info(
            "handle_cmd: action=%s params=%s", 
            action, 
            {k: ("***" if k in {"password", "token"} else v) for k, v in (params or {}).items()}
        )

        if action == "start":
            src = params.get("source")
            if not src:
                self.log.error("start: missing source")
                return False, "missing source", {}
            
            if self.viewer_pid:
                self.log.info("start: stopping existing viewer pid=%s", self.viewer_pid)
                self._killpg(self.viewer_pid)
                self.viewer_pid = None
            
            cmd_t = self.cfg.get("start_cmd_template")
            if not cmd_t:
                self.log.error("start: start_cmd_template not set")
                return False, "start_cmd_template not set", {}
            
            cmd = cmd_t.format(source=src, device_id=self.device_id)
            self.log.info("start: launching cmd=%s", cmd)
            self.viewer_pid = self._spawn(cmd)
            self.state = "running"
            self.fields.update({"input": src, "pid": self.viewer_pid})
            self.log.info("start: spawned viewer pid=%s input=%s", self.viewer_pid, src)
            return True, None, {"pid": self.viewer_pid, "input": src}

        if action == "stop":
            if self.viewer_pid:
                self.log.info("stop: stopping viewer pid=%s", self.viewer_pid)
                self._killpg(self.viewer_pid)
                self.viewer_pid = None
            
            self.state = "idle"
            self.fields.update({"input": None, "pid": None})
            self.log.info("stop: viewer stopped")
            return True, None, {}

        if action == "set_input":
            src = params.get("source")
            if not src:
                self.log.error("set_input: missing source")
                return False, "missing source", {}
            
            self.log.info(
                "set_input: requested source=%s restart=%s", 
                src, 
                bool(self.cfg.get("set_input_restart", True))
            )
            self.fields["input"] = src
            
            if self.cfg.get("set_input_restart", True):
                if self.viewer_pid:
                    self.log.info("set_input: stopping existing viewer pid=%s", self.viewer_pid)
                    self._killpg(self.viewer_pid)
                    self.viewer_pid = None
                
                cmd_t = self.cfg.get("start_cmd_template")
                if not cmd_t:
                    self.log.error("set_input: start_cmd_template not set")
                    return False, "start_cmd_template not set", {}
                
                cmd = cmd_t.format(source=src, device_id=self.device_id)
                self.log.info("set_input: launching cmd=%s", cmd)
                self.viewer_pid = self._spawn(cmd)
                self.fields["pid"] = self.viewer_pid
                self.state = "running"
                self.log.info("set_input: spawned viewer pid=%s input=%s", self.viewer_pid, src)
            
            return True, None, {"input": src, "pid": self.viewer_pid}

        if action == "record_start":
            src = params.get("source", self.fields.get("input"))
            if not src:
                self.log.error("record_start: no source to record")
                return False, "no source to record", {}
            
            if self.rec_pid:
                self.log.info("record_start: already recording pid=%s", self.rec_pid)
                return True, None, {"recording": True, "record_pid": self.rec_pid}
            
            cmd_t = self.cfg.get("record_start_cmd_template")
            if not cmd_t:
                self.log.error("record_start: record_start_cmd_template not set")
                return False, "record_start_cmd_template not set", {}
            
            cmd = cmd_t.format(source=src, device_id=self.device_id)
            self.log.info("record_start: launching cmd=%s", cmd)
            self.rec_pid = self._spawn(cmd)
            self.fields.update({"recording": True, "record_pid": self.rec_pid})
            self.log.info("record_start: spawned recorder pid=%s", self.rec_pid)
            return True, None, {"recording": True, "record_pid": self.rec_pid}

        if action == "record_stop":
            if self.rec_pid:
                self.log.info("record_stop: stopping recorder pid=%s", self.rec_pid)
                self._killpg(self.rec_pid, signal.SIGINT)
                self.rec_pid = None
            
            self.fields.update({"recording": False, "record_pid": None})
            self.log.info("record_stop: stopped")
            return True, None, {"recording": False}

        self.log.error("handle_cmd: unknown action=%s", action)
        return False, f"unknown action: {action}", {}
