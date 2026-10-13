# MusicSync v0.1.3: Qt6 Kvantum AppImage integration

This is a narrowly scoped packaging correction for v0.1.2. No synchronization,
ReplayGain, device-management or Qt Widgets interface redesign was made.

## Cause and reproduction

On Fedora/Hyprland, `qt6ct` selects `style=kvantum` and the external
Kvantum theme is `LiquidGlass`. The v0.1.2 AppImage carried
`libqt6ct.so` and `libqt6ct-style.so`, **but not `libkvantum.so`**.
The `Qt6CTProxyStyle` loaded anyway and the previous acceptance test incorrectly
treated that as proof that the actual selected style engine was present.
Native MusicSync, Dolphin and Qmmp all mapped the Fedora-hosted Kvantum plugin.

The new Wayland test first ran against the installed v0.1.2 AppImage and
**failed as intended**: `Kvantum selected by qt6ct but absent from running AppImage`.

## Implementation

- Builds the **Kvantum 1.1.6** Qt6 style plugin from the checksum-pinned upstream
  commit `ce2438af4c573856882eadca320b9a89eb8522b3`.
- Links against the actual PySide6 6.11.2 Qt wheel used inside the AppImage.
  It does not inject the host's Fedora Qt or Kvantum binaries.
- Builds only the style plugin with `WITHOUT_KF=ON`, not Kvantum Manager or the
  upstream themes. The style is bundled at
  `PySide6/qt-plugins/styles/libkvantum.so`.
- Keeps the external `qt6ct`, Kvantum and theme files in control; no personal
  LiquidGlass colors, assets, or style overrides are embedded in the application.
- Adds Kvantum to bundled component provenance, license notices, and exact
  corresponding source archive. The plugin is GPLv3, not MIT.
- Changes the acceptance test to inspect actual loaded libraries. When Kvantum
  is selected it additionally copies the user's Kvantum theme to a **temporary**
  XDG tree, changes only that copy, and confirms that the new palette takes
  effect on next launch.

## Results

- 161/161 offline release tests passed; 0 failures, errors or skips.
- v0.1.3 AppImage build completed successfully from the project container.
- AppImage artifact runtime, isolated tagging/rsync fixtures and GUI smoke test
  passed.
- `test_appimage_theme.py` passed native Wayland, bundled
  `libqt6ct.so`, `libqt6ct-style.so`, and `libkvantum.so`,
  external Kvantum theme A/B, fallback behavior, relocatable ELF paths,
  and confirmation that the real Qt configuration remained unchanged.
- The live v0.1.3 AppImage process mapped its **own** `libkvantum.so` inside
  the AppImage, and its Hyprland `grim` screenshot was visually inspected.
  The translucent blue-gray material matched the intended native appearance,
  unlike the v0.1.2 opaque/fallback rendering.
- All four SHA256SUMS entries passed local verification.
- Real phone file synchronization **not tested** during this packaging fix.
  No real phone music data was modified by the tests or inspection.

Private logs, screenshots and test evidence remain under ignored `build/`
and the project-specific `/home/reason/Temporary/MusicSync/` area; they are
not published to GitHub.
