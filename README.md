# Basis Smart Panel

A Home Assistant integration for Basis Smart panels by [Basis NZ Ltd](https://wearebasis.com/).

## Features

- **Real-time Power Monitoring** - Track current power consumption, import/export power, and primary current at the panel level
- **Circuit-level Insights** - Monitor power, current, and voltage for each individual circuit
- **Energy Statistics** - View daily and monthly energy import/export totals
- **Circuit Control** - Remotely control circuit standby states through Home Assistant
- **Connectivity Status** - Binary sensor showing panel connection status
- **Multi-panel Support** - Manage multiple Basis panels from a single integration

## Requirements

- Home Assistant 2025.1.0 or newer
- A Basis Smart Panel with an active cloud connection
- Basis account credentials

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click on "Integrations"
3. Click the three dots in the top right corner and select "Custom repositories"
4. Add this repository URL and select "Integration" as the category
5. Click "Add"
6. Search for "Basis Smart Panel" and install it
7. Restart Home Assistant

### Manual Installation

1. Download the `basis_smart_panel` folder from this repository
2. Copy it to your `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

1. Go to **Settings** > **Devices & Services**
2. Click **Add Integration**
3. Search for "Basis Smart Panel"
4. Follow the OAuth2 authentication flow to link your Basis account

## Entities

### Sensors

| Entity | Description | Update Interval |
|--------|-------------|-----------------|
| Current Power | Net power consumption (W) | 30 seconds |
| Import Power | Power drawn from grid (W) | 30 seconds |
| Export Power | Power exported to grid (W) | 30 seconds |
| Primary Current | Main current draw (A) | 30 seconds |
| Today's Import | Energy imported today (kWh) | 5 minutes |
| Today's Export | Energy exported today (kWh) | 5 minutes |
| This Month's Import | Energy imported this month (kWh) | 5 minutes |
| This Month's Export | Energy exported this month (kWh) | 5 minutes |

### Circuit Sensors

For each circuit in your panel:

- Power (W)
- Current (A)
- Voltage (V)

### Binary Sensors

- **Connected** - Shows whether the panel is currently connected to the Basis cloud

### Switches

- **Circuit Standby** - Control the standby state of individual circuits (where supported)

## Support

For issues with this integration, please open an issue on GitHub.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
