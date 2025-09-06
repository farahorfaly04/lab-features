"""Simplified NDI Plugin for Lab Platform orchestrator."""

import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

try:
    from cyndilib.finder import Finder
except Exception:
    Finder = None  # type: ignore

from lab_orchestrator.plugin_api import OrchestratorPlugin
from lab_orchestrator.services.events import ack


class DeviceCommand(BaseModel):
    """Model for device commands."""
    device_id: str
    action: str
    params: Dict[str, Any] = {}


class NDISourcesResponse(BaseModel):
    """Response model for NDI sources."""
    sources: List[str]
    timestamp: str


class NDIPlugin(OrchestratorPlugin):
    """Simplified NDI plugin for the Lab Platform orchestrator."""
    
    module_name = "ndi"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.ndi_sources: List[str] = []
        self.last_discovery = 0.0
        self.discovery_timeout = 3.0

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
        return {"start", "stop", "restart", "status", "set_input", "record_start", "record_stop", "list_processes"}

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

    def _discover_ndi_sources(self, timeout: float = None) -> List[str]:
        """Discover available NDI sources."""
        if not Finder:
            return []
        
        timeout = timeout or self.discovery_timeout
        current_time = time.time()
        
        # Cache discovery results for a short time
        if current_time - self.last_discovery < 1.0 and self.ndi_sources:
            return self.ndi_sources
        
        try:
            finder = Finder()
            time.sleep(timeout)  # Wait for discovery
            
            sources = []
            for source in finder.get_sources():
                sources.append(f"{source.name} ({source.ip})")
            
            self.ndi_sources = sources
            self.last_discovery = current_time
            return sources
            
        except Exception as e:
            print(f"NDI discovery error: {e}")
            return []

    def _get_ndi_devices(self) -> List[Dict[str, Any]]:
        """Get devices with NDI capability."""
        devices = []
        for device_id, device_info in self.ctx.registry.devices.items():
            labels = device_info.get("labels", [])
            if "ndi" in labels:
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
                "devices": self._get_ndi_devices(),
                "registry_snapshot": self.ctx.registry.snapshot()
            }

        @router.get("/sources", response_model=NDISourcesResponse)
        def get_sources():
            """Get available NDI sources."""
            sources = self._discover_ndi_sources()
            return NDISourcesResponse(
                sources=sources,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            )

        @router.get("/sources/refresh", response_model=NDISourcesResponse)
        def refresh_sources():
            """Force refresh NDI sources with longer timeout."""
            sources = self._discover_ndi_sources(timeout=5.0)
            return NDISourcesResponse(
                sources=sources,
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            )

        @router.get("/devices")
        def get_devices():
            """Get devices with NDI capability."""
            return {"devices": self._get_ndi_devices()}

        @router.get("/devices/{device_id}")
        def get_device(device_id: str):
            """Get specific device information."""
            device_info = self.ctx.registry.devices.get(device_id)
            if not device_info:
                raise HTTPException(status_code=404, detail="Device not found")
            
            labels = device_info.get("labels", [])
            if "ndi" not in labels:
                raise HTTPException(status_code=400, detail="Device does not support NDI")
            
            return {"device": device_info}

        @router.post("/start")
        def start_ndi(cmd: DeviceCommand):
            """Start NDI viewer on device."""
            payload = {
                "req_id": f"api-{int(time.time() * 1000)}",
                "actor": "api",
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "action": "start",
                "params": {"device_id": cmd.device_id, **cmd.params}
            }
            
            dev_topic = f"/lab/device/{cmd.device_id}/{self.module_name}/cmd"
            self.ctx.mqtt.publish_json(dev_topic, payload, qos=1, retain=False)
            
            return {"status": "dispatched", "device_id": cmd.device_id, "action": "start"}

        @router.post("/stop")
        def stop_ndi(cmd: DeviceCommand):
            """Stop NDI viewer on device."""
            payload = {
                "req_id": f"api-{int(time.time() * 1000)}",
                "actor": "api",
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "action": "stop",
                "params": {"device_id": cmd.device_id, **cmd.params}
            }
            
            dev_topic = f"/lab/device/{cmd.device_id}/{self.module_name}/cmd"
            self.ctx.mqtt.publish_json(dev_topic, payload, qos=1, retain=False)
            
            return {"status": "dispatched", "device_id": cmd.device_id, "action": "stop"}

        @router.post("/input")
        def set_input(cmd: DeviceCommand):
            """Set NDI input source on device."""
            if "source" not in cmd.params:
                raise HTTPException(status_code=400, detail="source parameter required")
            
            payload = {
                "req_id": f"api-{int(time.time() * 1000)}",
                "actor": "api",
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "action": "set_input",
                "params": {"device_id": cmd.device_id, **cmd.params}
            }
            
            dev_topic = f"/lab/device/{cmd.device_id}/{self.module_name}/cmd"
            self.ctx.mqtt.publish_json(dev_topic, payload, qos=1, retain=False)
            
            return {"status": "dispatched", "device_id": cmd.device_id, "action": "set_input"}

        return router

    def ui_mount(self) -> Optional[Dict[str, str]]:
        """Return UI mount configuration."""
        return {
            "path": "/ui/ndi",
            "title": "NDI",
            "template": "ndi.html"
        }