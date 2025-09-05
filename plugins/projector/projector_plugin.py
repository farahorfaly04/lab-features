"""Projector Plugin for Lab Platform orchestrator."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List
import sys
from pathlib import Path

# Import orchestrator plugin API
from lab_orchestrator.plugin_api import OrchestratorPlugin
from lab_orchestrator.services.events import ack


class ProjectorPlugin(OrchestratorPlugin):
    """Projector plugin for the Lab Platform orchestrator."""
    
    module_name = "projector"

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
        passthrough = {
            "power_on", "power_off", "set_input", "set_aspect_ratio", 
            "navigate", "adjust_image", "send_raw_command"
        }
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
        """Create FastAPI router for projector endpoints."""
        r = APIRouter()

        class PowerBody(BaseModel):
            device_id: str
            power: str  # "on" or "off"

        class InputBody(BaseModel):
            device_id: str
            input: str  # "HDMI1" or "HDMI2"

        class AspectBody(BaseModel):
            device_id: str
            ratio: str  # "4:3" or "16:9"

        class NavigateBody(BaseModel):
            device_id: str
            direction: str  # "UP", "DOWN", "LEFT", "RIGHT", "ENTER", "MENU", "BACK"

        class AdjustBody(BaseModel):
            device_id: str
            adjustment: str  # "H-IMAGE-SHIFT", "V-IMAGE-SHIFT", "H-KEYSTONE", "V-KEYSTONE"
            value: int

        class RawCommandBody(BaseModel):
            device_id: str
            command: str

        @r.get("/status")
        def status():
            """Get plugin status."""
            reg = self.ctx.registry.snapshot()
            return reg

        @r.get("/devices")
        def devices() -> Dict[str, Any]:
            """Get devices with projector capability."""
            reg = self.ctx.registry.snapshot()
            projector_devices = {}
            
            for did, meta in reg.get("devices", {}).items():
                modules = meta.get("modules", [])
                if "projector" in modules:
                    projector_devices[did] = {
                        "device_id": did,
                        "online": meta.get("online", True),
                        "capabilities": meta.get("capabilities", {}).get("projector", {}),
                        "current_state": meta.get("state", {}),
                    }
            
            return {"devices": projector_devices}

        @r.post("/power")
        def power(body: PowerBody):
            """Control projector power."""
            device_id = body.device_id
            power_state = body.power.lower()
            
            if power_state not in ["on", "off"]:
                raise HTTPException(status_code=400, detail="Power must be 'on' or 'off'")
            
            # Validate device exists
            reg = self.ctx.registry.snapshot()
            if device_id not in reg.get("devices", {}):
                raise HTTPException(status_code=404, detail="Unknown device")

            import uuid
            from lab_orchestrator.services.events import now_iso
            
            action = "power_on" if power_state == "on" else "power_off"
            payload = {
                "req_id": str(uuid.uuid4()),
                "actor": "api",
                "ts": now_iso(),
                "action": action,
                "params": {"device_id": device_id},
            }
            
            dev_topic = f"/lab/device/{device_id}/{self.module_name}/cmd"
            self.ctx.mqtt.publish_json(dev_topic, payload, qos=1, retain=False)
            
            return {
                "ok": True, 
                "dispatched": True, 
                "device_id": device_id, 
                "action": action
            }

        @r.post("/input")
        def set_input(body: InputBody):
            """Set projector input source."""
            device_id = body.device_id
            input_source = body.input
            
            if input_source not in ["HDMI1", "HDMI2"]:
                raise HTTPException(status_code=400, detail="Input must be 'HDMI1' or 'HDMI2'")
            
            # Validate device exists
            reg = self.ctx.registry.snapshot()
            if device_id not in reg.get("devices", {}):
                raise HTTPException(status_code=404, detail="Unknown device")

            import uuid
            from lab_orchestrator.services.events import now_iso
            
            payload = {
                "req_id": str(uuid.uuid4()),
                "actor": "api",
                "ts": now_iso(),
                "action": "set_input",
                "params": {"device_id": device_id, "input": input_source},
            }
            
            dev_topic = f"/lab/device/{device_id}/{self.module_name}/cmd"
            self.ctx.mqtt.publish_json(dev_topic, payload, qos=1, retain=False)
            
            return {
                "ok": True, 
                "dispatched": True, 
                "device_id": device_id, 
                "input": input_source
            }

        @r.post("/aspect")
        def set_aspect(body: AspectBody):
            """Set projector aspect ratio."""
            device_id = body.device_id
            ratio = body.ratio
            
            if ratio not in ["4:3", "16:9"]:
                raise HTTPException(status_code=400, detail="Aspect ratio must be '4:3' or '16:9'")
            
            # Validate device exists
            reg = self.ctx.registry.snapshot()
            if device_id not in reg.get("devices", {}):
                raise HTTPException(status_code=404, detail="Unknown device")

            import uuid
            from lab_orchestrator.services.events import now_iso
            
            payload = {
                "req_id": str(uuid.uuid4()),
                "actor": "api",
                "ts": now_iso(),
                "action": "set_aspect_ratio",
                "params": {"device_id": device_id, "ratio": ratio},
            }
            
            dev_topic = f"/lab/device/{device_id}/{self.module_name}/cmd"
            self.ctx.mqtt.publish_json(dev_topic, payload, qos=1, retain=False)
            
            return {
                "ok": True, 
                "dispatched": True, 
                "device_id": device_id, 
                "aspect_ratio": ratio
            }

        @r.post("/navigate")
        def navigate(body: NavigateBody):
            """Send navigation command to projector."""
            device_id = body.device_id
            direction = body.direction.upper()
            
            valid_directions = ["UP", "DOWN", "LEFT", "RIGHT", "ENTER", "MENU", "BACK"]
            if direction not in valid_directions:
                raise HTTPException(status_code=400, detail=f"Direction must be one of: {valid_directions}")
            
            # Validate device exists
            reg = self.ctx.registry.snapshot()
            if device_id not in reg.get("devices", {}):
                raise HTTPException(status_code=404, detail="Unknown device")

            import uuid
            from lab_orchestrator.services.events import now_iso
            
            payload = {
                "req_id": str(uuid.uuid4()),
                "actor": "api",
                "ts": now_iso(),
                "action": "navigate",
                "params": {"device_id": device_id, "direction": direction},
            }
            
            dev_topic = f"/lab/device/{device_id}/{self.module_name}/cmd"
            self.ctx.mqtt.publish_json(dev_topic, payload, qos=1, retain=False)
            
            return {
                "ok": True, 
                "dispatched": True, 
                "device_id": device_id, 
                "direction": direction
            }

        @r.post("/adjust")
        def adjust_image(body: AdjustBody):
            """Adjust projector image settings."""
            device_id = body.device_id
            adjustment = body.adjustment.upper()
            value = body.value
            
            valid_adjustments = ["H-IMAGE-SHIFT", "V-IMAGE-SHIFT", "H-KEYSTONE", "V-KEYSTONE"]
            if adjustment not in valid_adjustments:
                raise HTTPException(status_code=400, detail=f"Adjustment must be one of: {valid_adjustments}")
            
            # Validate value ranges
            if adjustment in ["H-IMAGE-SHIFT", "V-IMAGE-SHIFT"]:
                if not (-100 <= value <= 100):
                    raise HTTPException(status_code=400, detail="Image shift value must be between -100 and 100")
            elif adjustment in ["H-KEYSTONE", "V-KEYSTONE"]:
                if not (-40 <= value <= 40):
                    raise HTTPException(status_code=400, detail="Keystone value must be between -40 and 40")
            
            # Validate device exists
            reg = self.ctx.registry.snapshot()
            if device_id not in reg.get("devices", {}):
                raise HTTPException(status_code=404, detail="Unknown device")

            import uuid
            from lab_orchestrator.services.events import now_iso
            
            payload = {
                "req_id": str(uuid.uuid4()),
                "actor": "api",
                "ts": now_iso(),
                "action": "adjust_image",
                "params": {"device_id": device_id, "adjustment": adjustment, "value": value},
            }
            
            dev_topic = f"/lab/device/{device_id}/{self.module_name}/cmd"
            self.ctx.mqtt.publish_json(dev_topic, payload, qos=1, retain=False)
            
            return {
                "ok": True, 
                "dispatched": True, 
                "device_id": device_id, 
                "adjustment": adjustment,
                "value": value
            }

        @r.post("/raw")
        def raw_command(body: RawCommandBody):
            """Send raw command to projector."""
            device_id = body.device_id
            command = body.command
            
            if not command.strip():
                raise HTTPException(status_code=400, detail="Command cannot be empty")
            
            # Validate device exists
            reg = self.ctx.registry.snapshot()
            if device_id not in reg.get("devices", {}):
                raise HTTPException(status_code=404, detail="Unknown device")

            import uuid
            from lab_orchestrator.services.events import now_iso
            
            payload = {
                "req_id": str(uuid.uuid4()),
                "actor": "api",
                "ts": now_iso(),
                "action": "send_raw_command",
                "params": {"device_id": device_id, "command": command},
            }
            
            dev_topic = f"/lab/device/{device_id}/{self.module_name}/cmd"
            self.ctx.mqtt.publish_json(dev_topic, payload, qos=1, retain=False)
            
            return {
                "ok": True, 
                "dispatched": True, 
                "device_id": device_id, 
                "command": command
            }

        return r

    def ui_mount(self):
        """Return UI mount configuration."""
        return {"path": f"/ui/{self.module_name}", "template": "projector.html", "title": "Projector Control"}
