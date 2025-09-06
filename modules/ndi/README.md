# NDI Module

The NDI (Network Device Interface) module enables video streaming capabilities for Lab Platform devices. This module supports various NDI streaming tools, including `yuri_simple` for simplified streaming workflows.

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- Lab Platform Device Agent
- NDI streaming tools (automatically installed)

### Installation

1. **Automatic Installation (Recommended)**:
   ```bash
   make install-deps
   ```
   This will automatically detect your system and install `yuri_simple` using the best available method.

2. **Manual Installation Methods**:
   ```bash
   # Ubuntu/Debian
   make install-yuri-apt
   
   # macOS with Homebrew
   make install-yuri-brew
   
   # Via pip (fallback)
   make install-yuri-pip
   
   # From source (advanced)
   make install-yuri-source
   ```

3. **Check Installation**:
   ```bash
   make check-yuri
   make check-readiness
   ```

### Readiness Check with Auto-Fix

The NDI module includes intelligent readiness checking with automatic dependency installation:

```bash
# Check if everything is ready
make check-readiness

# Check and automatically fix issues
make check-readiness-fix

# Verbose output for troubleshooting
make check-readiness-verbose
```

## 📋 Dependencies

### yuri_simple

The `yuri_simple` tool is the primary dependency for NDI streaming. It will be automatically installed when you run:

- `make install-deps`
- `make check-readiness-fix`
- `python3 install_yuri_simple.py`

### Manual Installation

If automatic installation fails, you can install `yuri_simple` manually:

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install yuri
```

**macOS with Homebrew:**
```bash
brew install yuri
```

**From Source:**
```bash
git clone https://github.com/iimachines/yuri.git
cd yuri
mkdir build && cd build
cmake ..
make
sudo make install
```

## ⚙️ Configuration

The NDI module can be configured through the device agent's `config.yaml`:

```yaml
modules:
  ndi:
    ndi_path: "/usr/local/lib/ndi"
    start_cmd_template: "ndi-viewer {source}"
    record_start_cmd_template: "ndi-recorder -i {source} -o /tmp/recording_{device_id}.mp4"
    set_input_restart: true
    log_file: "/var/log/ndi_{device_id}.log"
```

## 🎛️ Usage

### Available Actions

The NDI module supports the following actions via MQTT:

1. **start**: Start NDI viewer
   ```json
   {
     "action": "start",
     "params": {
       "source": "NDI_SOURCE_NAME",
       "stream": "stream_name",
       "pipeline": "custom_command"
     }
   }
   ```

2. **stop**: Stop NDI viewer
3. **restart**: Restart with new parameters
4. **status**: Get module status
5. **set_input**: Change input source
6. **record_start**: Start recording
7. **record_stop**: Stop recording

### Using yuri_simple

When using the `stream` parameter, the module automatically builds a `yuri_simple` command:

```json
{
  "action": "start",
  "params": {
    "stream": "my_ndi_stream"
  }
}
```

This generates: `yuri_simple my_ndi_stream`

### Custom Pipelines

For advanced use cases, use the `pipeline` parameter for full command control:

```json
{
  "action": "start",
  "params": {
    "pipeline": "yuri_simple input_stream | some_filter | output_destination"
  }
}
```

## 🔧 Troubleshooting

### Common Issues

1. **yuri_simple not found**:
   ```bash
   make install-yuri
   # or
   make check-readiness-fix
   ```

2. **Permission denied during installation**:
   - Ensure you have sudo privileges for system-wide installation
   - Try user-level installation with pip

3. **NDI libraries missing**:
   - Install NDI SDK from NewTek/Vizrt
   - Set `ndi_path` in module configuration

4. **MQTT connection issues**:
   - Check device agent configuration
   - Verify MQTT broker connectivity

### Debug Mode

Run the readiness check in verbose mode for detailed diagnostics:

```bash
make check-readiness-verbose
```

### Log Files

Module logs are written to the configured log file (default: `/tmp/ndi_{device_id}.log`):

```bash
tail -f /tmp/ndi_*.log
```

## 🧪 Testing

Test the module installation and functionality:

```bash
make test
```

This runs:
- Readiness checks
- Dependency verification
- Basic functionality tests

## 📚 Additional Resources

- [NDI Documentation](https://www.ndi.tv/)
- [yuri Project](https://github.com/iimachines/yuri)
- [Lab Platform Documentation](../../../docs/)

## 🤝 Contributing

When contributing to the NDI module:

1. Ensure all readiness checks pass
2. Test automatic installation on different platforms
3. Update this documentation for new features
4. Follow the Lab Platform coding standards

## 📄 License

This module is part of the Lab Platform project and follows the same license terms.
