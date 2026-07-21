# Herfy Tracking System 2.18.0 Windows build

This repository builds the approved Windows client from the exact source archive in `source/`.

GitHub Actions validates the archive SHA-256, builds the PyInstaller runtime and the Inno Setup installer on a Windows x64 runner, then uploads:

- `HerfyTrackingSystem_2.18.0_Setup.exe`
- `HerfyTrackingSystem_2.18.0.exe`
- `HerfyTrackingSystem_2.18.0_Portable.zip`
- `client-update-manifest.json`
- `SHA256SUMS.txt`
