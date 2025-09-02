"""NDI Plugin for Lab Platform orchestrator."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List
import time
import sys
from pathlib import Path

# Import orchestrator plugin API
sys.path.append(str(Path(__file__).resolve().parents[3] / "infra" / "orchestrator" / "src"))
from lab_orchestrator.plugin_api import OrchestratorPlugin
from lab_orchestrator.services.events import ack


class NDIPlugin(OrchestratorPlugin):
    """NDI plugin for the Lab Platform orchestrator."""
    
    module_name = "ndi"

    def mqtt_topic_filters(self):
        """Return MQTT topics this plugin handles."""
        return [f"/lab/orchestrator/{self.module_name}/cmd"]

    def handle_mqtt(self, topic: str, payload: Dict[str, Any]) -> None:
        """Handle incoming MQTT messages."""
        req_id = payload.get("req_id", "no-req")
        action = payload.get("action")
        params = payload.get("params", {})
        device_id = params.get("device_id")
        actor = payload.get("actor", "app")

        # Passthrough actions - forward directly to device module
        passthrough = {"start", "stop", "set_input", "record_start", "record_stop"}
        if action in passthrough:
            dev_topic = f"/lab/device/{device_id}/{self.module_name}/cmd"
            self.ctx.mqtt.publish_json(dev_topic, payload, qos=1, retain=False)
            evt = ack(req_id, True, "DISPATCHED")
            self.ctx.mqtt.publish_json(f"/lab/orchestrator/{self.module_name}/evt", evt)
            return

        # Reserve device
        if action == "reserve":
            lease_s = int(params.get("lease_s", 60))
            key = f"{self.module_name}:{device_id}"
            ok = self.ctx.registry.lock(key, actor, lease_s)
            code = "OK" if ok else "IN_USE"
            err = None if ok else "in_use"
            self.ctx.mqtt.publish_json(
                f"/lab/orchestrator/{self.module_name}/evt", 
                ack(req_id, ok, code, err)
            )
            return

        # Release device
        if action == "release":
            key = f"{self.module_name}:{device_id}"
            ok = self.ctx.registry.release(key, actor)
            code = "OK" if ok else "NOT_OWNER"
            err = None if ok else "not_owner"
            self.ctx.mqtt.publish_json(
                f"/lab/orchestrator/{self.module_name}/evt", 
                ack(req_id, ok, code, err)
            )
            return

        # Schedule commands
        if action == "schedule":
            when = params.get("at")
            cron = params.get("cron")
            commands = params.get("commands", [])
            
            if when:
                from datetime import datetime
                run_date = datetime.fromisoformat(when.replace("Z", "+00:00"))
                self.ctx.scheduler.once(
                    run_date, 
                    self._run_commands, 
                    module=self.module_name, 
                    commands=commands, 
                    actor=actor
                )
            elif cron:
                self.ctx.scheduler.cron(
                    cron, 
                    self._run_commands, 
                    module=self.module_name, 
                    commands=commands, 
                    actor=actor
                )
            
            self.ctx.mqtt.publish_json(
                f"/lab/orchestrator/{self.module_name}/evt", 
                ack(req_id, True, "SCHEDULED")
            )
            return

        # Unknown action
        evt = ack(req_id, False, "BAD_ACTION", f"Unsupported action: {action}")
        self.ctx.mqtt.publish_json(f"/lab/orchestrator/{self.module_name}/evt", evt)

    def _run_commands(self, module: str, commands: list[Dict[str, Any]], actor: str):
        """Execute scheduled commands."""
        import uuid
        from lab_orchestrator.services.events import now_iso
        
        for c in commands:
            device_id = c.get("device_id")
            if not device_id:
                continue
            
            key = f"{module}:{device_id}"
            if not self.ctx.registry.can_use(key, actor):
                continue
            
            env = {
                "req_id": str(uuid.uuid4()),
                "actor": f"host:{actor}",
                "ts": now_iso(),
                "action": c.get("action"),
                "params": c.get("params", {})
            }
            env["params"]["device_id"] = device_id
            self.ctx.mqtt.publish_json(
                f"/lab/device/{device_id}/{module}/cmd", 
                env, 
                qos=1, 
                retain=False
            )

    def api_router(self):
        """Create FastAPI router for NDI endpoints."""
        r = APIRouter()

        class SendBody(BaseModel):
            device_id: str
            source: str
            action: str | None = None  # default to "start"

        @r.get("/status")
        def status():
            """Get plugin status."""
            reg = self.ctx.registry.snapshot()
            return reg

        @r.get("/sources")
        def sources() -> Dict[str, List[str]]:
            """Get available NDI sources."""
            # Return only dynamically discovered sources
            discovered: List[str] = []
            try:
                discovered = _discover_ndi_source_names(timeout=3.0)
            except Exception:
                # On discovery error, return empty list
                discovered = []
            return {"sources": discovered}

        @r.get("/devices")
        def devices() -> Dict[str, Any]:
            """Get devices with NDI capability."""
            reg = self.ctx.registry.snapshot()
            ndi_devices = {}
            
            for did, meta in reg.get("devices", {}).items():
                modules = meta.get("modules", [])
                if "ndi" in modules:
                    ndi_devices[did] = {
                        "device_id": did,
                        "online": meta.get("online", True),
                        "capabilities": meta.get("capabilities", {}).get("ndi", {}),
                    }
            
            return {"devices": ndi_devices}

        @r.post("/send")
        def send(body: SendBody):
            """Send command to NDI device."""
            device_id = body.device_id
            source = body.source
            action = body.action or "start"
            
            # Validate against dynamically discovered sources only
            try:
                discovered = set(_discover_ndi_source_names(timeout=3.0))
            except Exception:
                discovered = set()
            
            if discovered and source not in discovered:
                raise HTTPException(status_code=400, detail="unknown source")
            
            # Validate device exists
            reg = self.ctx.registry.snapshot()
            if device_id not in reg.get("devices", {}):
                raise HTTPException(status_code=404, detail="unknown device")

            import uuid
            from lab_orchestrator.services.events import now_iso
            
            payload = {
                "req_id": str(uuid.uuid4()),
                "actor": "api",
                "ts": now_iso(),
                "action": action,
                "params": {"device_id": device_id, "source": source},
            }
            
            dev_topic = f"/lab/device/{device_id}/{self.module_name}/cmd"
            self.ctx.mqtt.publish_json(dev_topic, payload, qos=1, retain=False)
            
            return {
                "ok": True, 
                "dispatched": True, 
                "device_id": device_id, 
                "source": source, 
                "action": action
            }

        return r

    def ui_mount(self):
        """Return UI mount configuration."""
        return {"path": f"/ui/{self.module_name}", "template": "ndi.html", "title": "NDI"}


def _discover_ndi_source_names(timeout: float = 3.0) -> List[str]:
    """Discover NDI sources and return a list of human-readable names.

    This function attempts to use NDI discovery to find available sources.
    Falls back to an empty list if discovery fails.
    """
    try:
        # Try to use cyndilib for NDI discovery
        from cyndilib.finder import Finder 
        
        finder = Finder()
        finder.open()
        
        try:
            end_time = time.time() + timeout
            while time.time() < end_time:
                changed = finder.wait_for_sources(timeout=end_time - time.time())
                if changed:
                    finder.update_sources()
                time.sleep(0.1)

            names: List[str] = []
            for src in finder.iter_sources():
                names.append(src.name)
            return names
        finally:
            finder.close()
    
    except Exception:
        # If NDI discovery fails, return empty list
        return []
