# Basis Smart Panel

A Home Assistant integration for Basis Smart panels by [Basis NZ Ltd](https://wearebasis.com/).

## Features

- **Live power monitoring**: net power, import power, export power and primary current of each panel.
- **Circuit monitoring**: power, current, voltage and daily import energy of each circuit.
- **Energy statistics**: daily and monthly import and export energy of each panel, for the Energy dashboard.
- **Circuit control**: put a circuit in standby, or make it live again.
- **Connectivity status**: a binary sensor that shows if the panel is connected to the Basis cloud.
- **More than one panel**: all panels of your Basis account appear in one integration entry.

## Requirements

- Home Assistant 2025.4.0 or newer
- A Basis Smart Panel with an active cloud connection
- A Basis account

## Installation

### HACS (recommended)

1. Open HACS in Home Assistant.
2. Select the three-dot menu in the top-right corner, then select **Custom repositories**.
3. Enter the URL of this repository, select the type **Integration**, then select **Add**.
4. Search for "Basis Smart Panel" and select it.
5. Select **Download**.
6. Restart Home Assistant.

### Manual installation

1. Download the `custom_components/basis_smart_panel` folder from this repository.
2. Copy it to your `config/custom_components/` directory.
3. Restart Home Assistant.

## Configuration

1. Go to **Settings** > **Devices & services**.
2. Select **Add integration**.
3. Search for "Basis Smart Panel".
4. Sign in with your Basis account.

If your sign-in expires, Home Assistant asks you to sign in again. Sign in with the same Basis account. The integration rejects a different account.

New panels in your Basis account appear automatically. A panel that is no longer in your account is removed after it is missing for 10 to 15 minutes.

## Entities

Each panel is a device with the name that the panel has in the Basis app. When you rename the panel in the app, the device name follows. A panel without a name is named "Basis Panel" with its serial. The device page shows the panel serial as the serial number.

### Panel sensors

| Entity | Description | Update interval |
|--------|-------------|-----------------|
| Current Power | Net power of the panel (W) | 5 seconds |
| House Consumption Power | Power that the circuits import (W) | 5 seconds |
| Generation Power | Power that the circuits export, for example from solar (W) | 5 seconds |
| Primary Current | Current at the main supply (A) | 5 seconds |
| Consumption Energy Today | Energy imported since midnight (kWh) | 5 minutes |
| Generation Energy Today | Energy exported since midnight (kWh) | 5 minutes |
| Consumption Energy This Month | Energy imported since the first day of the month (kWh) | 5 minutes |
| Generation Energy This Month | Energy exported since the first day of the month (kWh) | 5 minutes |

### Circuit sensors

Each circuit that is not marked as spare gets these sensors:

| Entity | Description | Update interval |
|--------|-------------|-----------------|
| [NN] Name · Power | Power of the circuit (W) | 5 seconds |
| [NN] Name · Current | Current of the circuit (A) | 5 seconds |
| [NN] Name · Voltage | Voltage of the circuit (V) | 5 seconds |
| [NN] Name · Import Energy Today | Energy that the circuit imported since midnight (kWh) | 5 minutes |

NN is the position of the circuit in the panel. Name is the name that you gave the circuit in the Basis app. If you did not give it a name, the integration uses the circuit label, for example "Lights".

The integration identifies a circuit by its panel and position. If an electrician replaces the module in a position, the entities and their history stay. When the circuits of a panel change, the integration reloads and updates the entities:

- A new circuit gets entities.
- A circuit that is no longer spare gets entities.
- The entities of a circuit that no longer exists are removed.

### Energy dashboard

The energy sensors restart at midnight, and the monthly sensors restart on the first day of the month. Home Assistant records each reset as the start of a new cycle, so you can add these sensors to the Energy dashboard.

Add the "Today" sensor or the "This Month" sensor of a value, not both. If you add both, the dashboard counts the energy two times.

### Binary sensor

| Entity | Description |
|--------|-------------|
| Connectivity | On when the panel is connected to the Basis cloud. While the panel is disconnected, the attributes `last_seen` and `disconnect_reason` show the last contact and the reason. This is a diagnostic entity. |

### Switches

Each circuit that is not spare and not locked for standby gets a switch named "[NN] Name".

- On: the circuit is live.
- Off: the circuit is in standby.
- Unknown: the circuit is in a different state, for example a fault.
- Unavailable: the panel is not connected.

**Warning:** turning a switch off removes power from everything on that circuit. Home Assistant can include these switches in voice commands, and in actions that target an area, a device or all switches. Make sure that you know which circuits these commands reach.

A circuit that becomes locked for standby loses its switch. If the Basis cloud rejects a command, Home Assistant shows the reason.

## Upgrading from version 1.1 or earlier

- Earlier versions recorded the daily and monthly energy sensors incorrectly. At each reset, they wrote a large negative value into the long-term statistics. This version records the sensors correctly, but it does not repair the old statistics. To correct them, open **Developer tools** > **Statistics** and adjust the sum at each reset.
- At the first start, the circuit entities move from the module serial to the circuit position. Their entity IDs and history stay.
- The circuit sensors are now named "[NN] Name · Power", "[NN] Name · Current", "[NN] Name · Voltage" and "[NN] Name · Import Energy Today". Existing entities keep their entity ID.

## Support

For issues with this integration, open an issue on GitHub.

## Trademarks

This project may contain trademarks or logos for Basis NZ Ltd. products or services. See [TRADEMARKS.md](TRADEMARKS.md) for details.

## License

This project is licensed under the Apache License 2.0. See the [LICENSE](LICENSE) file for details.
