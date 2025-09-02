# Lab Platform Features

Pluggable features for the Lab Platform. Contains modules (device-side) and plugins (orchestrator-side) that extend platform functionality.

## Structure

```
features/
├── modules/           # Device-side functionality
│   └── ndi/          # NDI video streaming module
└── plugins/          # Orchestrator-side functionality
    └── ndi/          # NDI control plugin
```

## Features

### NDI (Network Device Interface)
Complete NDI video streaming solution:
- **Module**: Device-side NDI viewer and recording control
- **Plugin**: Orchestrator web UI and API for NDI management

## Creating New Features

### 1. Device Module

Create `modules/your_feature/`:

```yaml
# manifest.yaml
name: "your_feature"
version: "0.1.0"
description: "Your feature description"
module_file: "your_module.py"
class_name: "YourModule"
```

```python
# your_module.py
from lab_agent.base import Module

class YourModule(Module):
    name = "your_feature"
    
    def handle_cmd(self, action, params):
        # Implement your commands
        return True, None, {}
```

### 2. Orchestrator Plugin

Create `plugins/your_feature/`:

```yaml
# manifest.yaml
name: "your_feature"
version: "0.1.0"
description: "Your feature description"
plugin_class: "your_plugin.YourPlugin"
```

```python
# your_plugin.py
from lab_orchestrator.plugin_api import OrchestratorPlugin

class YourPlugin(OrchestratorPlugin):
    module_name = "your_feature"
    
    def mqtt_topic_filters(self):
        return [f"/lab/orchestrator/{self.module_name}/cmd"]
    
    def handle_mqtt(self, topic, payload):
        # Handle MQTT messages
        pass
```

## Manifest Schema

### Module Manifest
```yaml
name: string           # Module name
version: string        # Semantic version
description: string    # Description
module_file: string    # Python file name
class_name: string     # Module class name
config_schema: object  # Configuration schema
default_config: object # Default configuration
actions: array         # Supported actions
```

### Plugin Manifest
```yaml
name: string           # Plugin name
version: string        # Semantic version
description: string    # Description
plugin_class: string   # Plugin class path
settings: object       # Plugin settings
api_endpoints: array   # API endpoints
ui: object            # UI configuration
mqtt_topics: array    # MQTT topics handled
actions: array        # Supported actions
```

## Development

Features are automatically discovered by:
1. **Device Agent**: Scans `modules/` for manifest files
2. **Orchestrator**: Scans `plugins/` for manifest files

No registration required - just add the files and restart the services.

## Examples

See the NDI feature for complete examples:
- `modules/ndi/` - Device-side NDI control
- `plugins/ndi/` - Orchestrator-side NDI management
