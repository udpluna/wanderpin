<p align="center">
  <img src="static/img/icon.png" width="110" alt="WanderPin logo">
</p>

<h1 align="center">WanderPin</h1>

<p align="center">
  <b>Change your iPhone's GPS location from your computer. Free and open source.</b><br>
  Teleport anywhere, walk or drive real roads at any speed, steer with a joystick, and schedule moves.<br>
  No jailbreak, nothing to install on the phone, no subscription.
</p>

<p align="center">
  <a href="https://github.com/udpluna/wanderpin/releases/latest"><img src="https://img.shields.io/github/v/release/udpluna/wanderpin?label=download&color=7c5cff" alt="Download"></a>
  <img src="https://img.shields.io/badge/iOS-17.4%2B-22d3ee" alt="iOS 17.4+">
  <img src="https://img.shields.io/badge/Windows%20%7C%20macOS-supported-555" alt="Windows | macOS">
  <img src="https://img.shields.io/badge/license-GPL--3.0-green" alt="GPL-3.0">
</p>

<p align="center">
  <a href="https://buymeacoffee.com/YOUR_BMC_USERNAME"><img src="https://img.buymeacoffee.com/button-api/?text=Buy%20me%20a%20coffee&emoji=%E2%98%95&slug=YOUR_BMC_USERNAME&button_colour=FFDD00&font_colour=000000&font_family=Inter&outline_colour=000000&coffee_colour=ffffff" alt="Buy me a coffee" height="44"></a>
</p>

<!-- Add a screenshot: run start_demo.bat, take a screenshot, save it as docs/screenshot.png, then uncomment:
<p align="center"><img src="docs/screenshot.png" width="900" alt="WanderPin screenshot"></p>
-->

---

## ✨ Features

| | |
|---|---|
| 📍 **Teleport** | Search any address, paste coordinates, click the map, or right-click for quick actions |
| 🧭 **Travel** | Move from where you are to anywhere at your chosen speed, along real roads |
| 🛣️ **Routes** | Click stops on the map, follow roads or paths, and play once, repeat or back and forth. Save routes and import or export **GPX** |
| 🚗 **11 speed presets** | Stroll, Walk, Jog, Run, Bike, E-Scooter, **City Drive** (stops at lights), **Traffic** (stop-and-go), Highway, Train, Plane |
| 🎚️ **Any speed you want** | A slider from 1 to 1000 km/h, ±10% buttons, or type an exact number. mph or km/h. Changes apply live |
| 🌊 **Realistic movement** | Natural speed changes, smooth acceleration, a small GPS wobble, optional drift while parked |
| 🎮 **Joystick** | Walk with W A S D or the arrow keys, or drag the on-screen stick |
| ⏱️ **Cooldown timer** | After long jumps, shows the suggested wait (for location-based games) |
| ⭐ **Saved places and history** | Emoji icons, search, one-click teleport |
| 📅 **Schedules** | "Every weekday at 9:00, go to Work" or "play my walking route at 6pm" |
| 📱 **Phone control** | Scan a QR code and move yourself from your phone's browser on the same Wi-Fi |
| 🔌 **Auto-reconnect** | If the cable wiggles or the phone locks, it reconnects and puts you back where you were |
| 🎨 **Polished UI** | Dark and light themes, street, light, dark and satellite maps, a first-run setup guide |

## ⬇️ Download and install (Windows)

1. Download **WanderPin-Setup.exe** from the [latest release](https://github.com/udpluna/wanderpin/releases/latest) and run it.
   *Windows may say "Windows protected your PC" because the app isn't code-signed. Click **More info → Run anyway**.*
2. Install **Apple Devices** from the Microsoft Store (or iTunes). It gives Windows the iPhone driver.
3. Plug in your iPhone, unlock it, and tap **Trust This Computer**.
4. On the iPhone, go to **Settings › Privacy & Security › Developer Mode**, turn it on, and restart the phone. The app's setup guide can make this option appear if you don't see it.
5. Open WanderPin and click **Connect iPhone**. That's it! 🎉

When you're done, press **Real GPS** or close the app, and your phone goes back to its real location.

## 🛠️ Run from source

Requires Python 3.12.

```bash
git clone https://github.com/udpluna/wanderpin.git
cd wanderpin
```

- **Windows:** double-click `setup.bat` once, then `start.bat`. Use `start_debug.bat` to see errors, or `start_demo.bat` to try the app with a pretend iPhone.
- **macOS:** run `./setup_mac.sh` once, then `./start_mac.sh`.

Build the `.exe` yourself with `build\build_windows.bat`. For the installer too, install [Inno Setup 6](https://jrsoftware.org/isinfo.php).
Publishing a GitHub Release builds and attaches the Windows downloads automatically (see `.github/workflows/release.yml`).

## ❓ Troubleshooting

| Problem | Fix |
|---|---|
| "No iPhone found" | Install Apple Devices or iTunes. Use a data cable (not charge-only). Unlock the phone and tap Trust |
| Developer Mode error | Settings › Privacy & Security › Developer Mode → On, then restart the phone |
| Stuck on "Opening secure tunnel" | Run `advanced_admin_tunnel.bat` as administrator, then start the app with `WANDERPIN_TRANSPORT=tunneld` |
| Location snaps back | The fake location only lasts while WanderPin is running and connected |
| Anything else | Check `%APPDATA%\WanderPin\app.log` and [open an issue](https://github.com/udpluna/wanderpin/issues) |

## ⚠️ Use responsibly

WanderPin uses Apple's official Developer Mode location simulation, the same feature Xcode uses. Only use it on your own devices, and don't use it to mislead people in harmful ways. Many location-based games ban location changing and may suspend accounts, so use it at your own risk. See [EULA.txt](EULA.txt) and [PRIVACY.md](PRIVACY.md).

## ☕ Support the project

WanderPin is free, with no ads and no subscriptions. If it saves you money or time, please consider [buying me a coffee](https://buymeacoffee.com/YOUR_BMC_USERNAME). It keeps the app working with every new iOS update. Starring the repo ⭐ helps too!

## 🙏 Credits

Built on [pymobiledevice3](https://github.com/doronz88/pymobiledevice3), [Leaflet](https://leafletjs.com) and [MapLibre](https://maplibre.org).
Maps by [OpenFreeMap](https://openfreemap.org) and [OpenMapTiles](https://openmaptiles.org), map data © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), imagery © Esri.
Search by [Photon](https://photon.komoot.io), routing by [FOSSGIS OSRM](https://routing.openstreetmap.de). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Licensed under the [GNU GPL v3](LICENSE).
