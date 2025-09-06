"""Simplified Projector Plugin for Lab Platform orchestrator."""

import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from lab_orchestrator.plugin_api import OrchestratorPlugin
from lab_orchestrator.services.events import ack


class DeviceCommand(BaseModel):
    """Model for device commands."""
    device_id: str
    action: str
    params: Dict[str, Any] = {}


class ProjectorPlugin(OrchestratorPlugin):
    """Simplified projector plugin for the Lab Platform orchestrator."""
    
    module_name = "projector"

    def mqtt_topic_filters(self) -> List[str]:
        """Return MQTT topics this plugin handles."""
        return [f"/lab/orchestrator/{self.module_name}/cmd"]

    def handle_mqtt(self, topic: str, payload: Dict[str, Any]) -> None:
        """Handle incoming MQTT messages."""
        req_id = payload.get("req_id", "no-req")
        action = payload.get("action")
        params = payload.get("params", {})
        device_id = params.get("device_id")
        actor = payload.get("actor", "app")

        try:
            # Handle different actions
            if action in self._get_passthrough_actions():
                self._handle_passthrough(action, device_id, payload, req_id)
            elif action == "reserve":
                self._handle_reserve(device_id, params, actor, req_id)
            elif action == "release":
                self._handle_release(device_id, actor, req_id)
            else:
                self._send_error(req_id, f"Unknown action: {action}")
                
        except Exception as e:
            self._send_error(req_id, str(e))

    def _get_passthrough_actions(self) -> set:
        """Get actions that are passed through to devices."""
        return {"status", "power", "input", "command", "navigate", "adjust"}

    def _handle_passthrough(self, action: str, device_id: str, payload: Dict[str, Any], req_id: str) -> None:
        """Forward action to device module."""
        if not device_id:
            self._send_error(req_id, "device_id required")
            return
        
        dev_topic = f"/lab/device/{device_id}/{self.module_name}/cmd"
        self.ctx.mqtt.publish_json(dev_topic, payload, qos=1, retain=False)
        
        evt = ack(req_id, True, "DISPATCHED")
        self.ctx.mqtt.publish_json(f"/lab/orchestrator/{self.module_name}/evt", evt)

    def _handle_reserve(self, device_id: str, params: Dict[str, Any], actor: str, req_id: str) -> None:
        """Reserve a device for exclusive use."""
        if not device_id:
            self._send_error(req_id, "device_id required")
            return
        
        lease_s = int(params.get("lease_s", 60))
        key = f"{self.module_name}:{device_id}"
        success = self.ctx.registry.lock(key, actor, lease_s)
        
        code = "OK" if success else "IN_USE"
        error = None if success else "Device is already in use"
        
        evt = ack(req_id, success, code, error)
        self.ctx.mqtt.publish_json(f"/lab/orchestrator/{self.module_name}/evt", evt)

    def _handle_release(self, device_id: str, actor: str, req_id: str) -> None:
        """Release device reservation."""
        if not device_id:
            self._send_error(req_id, "device_id required")
            return
        
        key = f"{self.module_name}:{device_id}"
        success = self.ctx.registry.release(key, actor)
        
        code = "OK" if success else "NOT_OWNER"
        error = None if success else "You don't own this device"
        
        evt = ack(req_id, success, code, error)
        self.ctx.mqtt.publish_json(f"/lab/orchestrator/{self.module_name}/evt", evt)

    def _send_error(self, req_id: str, error_message: str) -> None:
        """Send error response."""
        evt = ack(req_id, False, "ERROR", error_message)
        self.ctx.mqtt.publish_json(f"/lab/orchestrator/{self.module_name}/evt", evt)

    def _get_projector_devices(self) -> List[Dict[str, Any]]:
        """Get devices with projector capability."""
        devices = []
        for device_id, device_info in self.ctx.registry.devices.items():
            labels = device_info.get("labels", [])
            if "projector" in labels:
                devices.append({
                    "device_id": device_id,
                    "status": device_info.get("status", "unknown"),
                    "labels": labels
                })
        return devices

    def api_router(self) -> Optional[APIRouter]:
        """Create API router for HTTP endpoints."""
        router = APIRouter()

        @router.get("/status")
        def get_status():
            """Get plugin status."""
            return {
                "plugin": self.module_name,
                "devices": self._get_projector_devices(),
                "registry_snapshot": self.ctx.registry.snapshot()
            }

        @router.get("/devices")
        def get_devices():
            """Get devices with projector capability."""
            return {"devices": self._get_projector_devices()}

        @router.get("/devices/{device_id}")
        def get_device(device_id: str):
            """Get specific device information."""
            device_info = self.ctx.registry.devices.get(device_id)
            if not device_info:
                raise HTTPException(status_code=404, detail="Device not found")
            
            labels = device_info.get("labels", [])
            if "projector" not in labels:
                raise HTTPException(status_code=400, detail="Device does not support projector control")
            
            return {"device": device_info}

        @router.post("/power")
        def set_power(cmd: DeviceCommand):
            """Set projector power state."""
            if "state" not in cmd.params:
                raise HTTPException(status_code=400, detail="state parameter required (on/off)")
            
            state = cmd.params["state"].lower()
            if state not in ["on", "off"]:
                raise HTTPException(status_code=400, detail="state must be 'on' or 'off'")
            
            payload = {
                "req_id": f"api-{int(time.time() * 1000)}",
                "actor": "api",
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "action": "power",
                "params": {"device_id": cmd.device_id, **cmd.params}
            }
            
            dev_topic = f"/lab/device/{cmd.device_id}/{self.module_name}/cmd"
            self.ctx.mqtt.publish_json(dev_topic, payload, qos=1, retain=False)
            
            return {"status": "dispatched", "device_id": cmd.device_id, "action": "power", "state": state}

        @router.post("/input")
        def set_input(cmd: DeviceCommand):
            """Set projector input source."""
            if "source" not in cmd.params:
                raise HTTPException(status_code=400, detail="source parameter required (hdmi1/hdmi2)")
            
            source = cmd.params["source"].lower()
            if source not in ["hdmi1", "hdmi2"]:
                raise HTTPException(status_code=400, detail="source must be 'hdmi1' or 'hdmi2'")
            
            payload = {
                "req_id": f"api-{int(time.time() * 1000)}",
                "actor": "api",
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "action": "input",
                "params": {"device_id": cmd.device_id, **cmd.params}
            }
            
            dev_topic = f"/lab/device/{cmd.device_id}/{self.module_name}/cmd"
            self.ctx.mqtt.publish_json(dev_topic, payload, qos=1, retain=False)
            
            return {"status": "dispatched", "device_id": cmd.device_id, "action": "input", "source": source}

        @router.post("/command")
        def send_command(cmd: DeviceCommand):
            """Send raw command to projector."""
            if "cmd" not in cmd.params:
                raise HTTPException(status_code=400, detail="cmd parameter required")
            
            payload = {
                "req_id": f"api-{int(time.time() * 1000)}",
                "actor": "api",
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "action": "command",
                "params": {"device_id": cmd.device_id, **cmd.params}
            }
            
            dev_topic = f"/lab/device/{cmd.device_id}/{self.module_name}/cmd"
            self.ctx.mqtt.publish_json(dev_topic, payload, qos=1, retain=False)
            
            return {"status": "dispatched", "device_id": cmd.device_id, "action": "command"}

        @router.post("/navigate")
        def navigate(cmd: DeviceCommand):
            """Send navigation command to projector."""
            if "direction" not in cmd.params:
                raise HTTPException(status_code=400, detail="direction parameter required")
            
            direction = cmd.params["direction"].lower()
            valid_directions = ["up", "down", "left", "right", "enter", "menu", "back"]
            if direction not in valid_directions:
                raise HTTPException(status_code=400, detail=f"direction must be one of: {valid_directions}")
            
            payload = {
                "req_id": f"api-{int(time.time() * 1000)}",
                "actor": "api",
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "action": "navigate",
                "params": {"device_id": cmd.device_id, **cmd.params}
            }
            
            dev_topic = f"/lab/device/{cmd.device_id}/{self.module_name}/cmd"
            self.ctx.mqtt.publish_json(dev_topic, payload, qos=1, retain=False)
            
            return {"status": "dispatched", "device_id": cmd.device_id, "action": "navigate", "direction": direction}

        @router.post("/adjust")
        def adjust(cmd: DeviceCommand):
            """Send adjustment command to projector."""
            if "type" not in cmd.params or "value" not in cmd.params:
                raise HTTPException(status_code=400, detail="type and value parameters required")
            
            adjustment_type = cmd.params["type"].lower()
            valid_types = ["h-image-shift", "v-image-shift", "h-keystone", "v-keystone"]
            if adjustment_type not in valid_types:
                raise HTTPException(status_code=400, detail=f"type must be one of: {valid_types}")
            
            try:
                value = int(cmd.params["value"])
            except ValueError:
                raise HTTPException(status_code=400, detail="value must be an integer")
            
            payload = {
                "req_id": f"api-{int(time.time() * 1000)}",
                "actor": "api",
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "action": "adjust",
                "params": {"device_id": cmd.device_id, **cmd.params}
            }
            
            dev_topic = f"/lab/device/{cmd.device_id}/{self.module_name}/cmd"
            self.ctx.mqtt.publish_json(dev_topic, payload, qos=1, retain=False)
            
            return {"status": "dispatched", "device_id": cmd.device_id, "action": "adjust", "type": adjustment_type, "value": value}

        return router

    def ui_mount(self) -> Optional[Dict[str, str]]:
        """Return UI mount configuration."""
        return {
            "path": "/ui/projector",
            "title": "Projector",
            "template": "projector.html"
        }