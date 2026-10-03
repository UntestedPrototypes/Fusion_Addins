# FusionLaserJoints ⚡

An Autodesk Fusion 360 Add-In that automatically generates interlocking joints for sheet materials, laser cutters, and CNC routers.

```
       [Tab & Slot / T-Joint]               [Corner Finger Joint]
          +---------------+                   +-+ +-+ +-+
          |   Tab Body    |                   | | | | | | Body 1
          +---+   +---+---+                   +-+-+-+-+-+
              |   |   |                       +-+-+-+-+-+
        ======+===+===+======                 | | | | | | Body 2
        |     Slot Body     |                 +-+ +-+ +-+
        =====================
```

---

## ✨ Features

- **3 Joint Styles**:
  - **Tab & Slot (Mortise & Tenon / T-Joint)**: One plate butts perpendicularly or at an angle into the face of another plate (dividers, shelves, structural ribs).
  - **Finger Joint (Box / Corner Joint)**: Two plates meet at a corner seam (overlapping or touching). Alternating fingers interlock seamlessly.
  - **Cross Joint (Halving / Slotted Grid)**: Intersecting plates slide into each other with matching half-depth slots (egg-crate dividers).
- **Dual Selection Workflow**:
  - **Edge & Face**: Click a specific linear mating edge and mating face for exact control.
  - **Body-to-Body**: Select two bodies directly; the add-in inspects the geometry and auto-detects the contact seam.
- **Dedicated Laser-Cutting Fit Engine**:
  - **Kerf & Assembly Clearance Offset ($+C$)**: Offsets slot width and thickness by $2 \times \text{clearance}$ so laser-cut parts fit together with desired friction/glue fit (default `0.15 mm`).
  - **Tab Lead-in Assembly Chamfers**: Trims leading tab corners with 45° bevels so parts slide together easily without binding or catching.
  - **Flush vs. Protruding Tab Height**: Choose flush tabs ($0\text{ mm}$) or extended tabs (e.g. $+1.0\text{ mm}$ for sanding flush after gluing).
  - **Edge Break Margins**: Keeps tabs inset from the ends of the edge to prevent fragile wood or acrylic corners from snapping.
- **Timeline Friendly**: Built with standard Fusion 360 B-Rep, BaseFeature, and Combine operations; completely undoable with a single `Ctrl+Z`.

---

## 🚀 Installation

### Automated (Recommended)
Run the included PowerShell installer:
```powershell
powershell -ExecutionPolicy Bypass -File "install_addon.ps1"
```
This automatically copies `FusionLaserJoints` to:
`%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\FusionLaserJoints`

### Manual Installation
1. Press `Win + R`, paste:
   `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns`
   and press Enter.
2. Copy the entire `FusionLaserJoints` directory into this folder.
3. Open Autodesk Fusion.
4. Go to **UTILITIES** > **ADD-INS** > **Scripts and Add-Ins** (shortcut: `Shift + S`).
5. Select the **Add-Ins** tab.
6. Select **FusionLaserJoints** and click **Run** (check *Run on Startup* if desired).

The **Laser Cut Joints** icon will appear on your **SOLID > MODIFY** toolbar and **UTILITIES** ribbon.

---

## 🛠️ Usage Guide

### 1. Tab & Slot (T-Joint)
1. In Fusion 360, click the **Laser Cut Joints** button in the **MODIFY** toolbar.
2. Set **Joint Style** to `Tab & Slot`.
3. In **Selection Mode**:
   - Pick the **Tab Edge** (the edge of the plate that butts into the mating plate).
   - Pick the **Mating Face** (the planar face of the other plate).
4. Configure layout:
   - **Distribution**: Choose `By Tab Count` (e.g. `3`) or `By Target Length` (e.g. `15 mm`).
   - **Edge Margin**: Set minimum end offset (e.g. `5 mm`).
   - **Clearance / Kerf**: Recommended `0.10 mm` to `0.20 mm` for laser cutting.
   - **Tab Protrusion**: `0 mm` for flush, or `1 mm` for sanding allowance.
   - **Lead-in Chamfers**: Check to bevel leading tab corners for smooth assembly.
5. Click **OK**.

### 2. Finger Joint (Corner Box Joint)
1. Select **Joint Style** -> `Finger Joint`.
2. Select the mating edge and mating face, or switch to `Body-to-Body` and select Plate 1 and Plate 2.
3. Enter desired **Finger Count** (e.g. `5` or `7`).
4. Set **Clearance / Kerf** offset (e.g. `0.15 mm`).
5. Click **OK**.

### 3. Cross Joint (Slotted Grid)
1. Select **Joint Style** -> `Cross Joint`.
2. Select the intersecting panels.
3. Set clearance tolerance.
4. Click **OK**.

---

## 🧪 Running Automated Tests
The mathematical engine has a standalone unit test suite that can run outside of Fusion:
```powershell
python -m unittest discover -s "tests" -p "test_*.py" -v
```

---

## 📂 Directory Structure

```
FusionLaserJoints/
├── FusionLaserJoints.manifest      # Fusion add-in metadata
├── FusionLaserJoints.py            # Main entry point, UI, and event handlers
├── config/
│   ├── __init__.py
│   └── defaults.py                 # Default tolerances and parameters
├── core/
│   ├── __init__.py
│   ├── geometry_math.py            # Vector math, interval distributions, clearance
│   ├── detection.py                # Contact detection & thickness calculation
│   ├── feature_builder.py          # BRep creation & combine Cut/Join features
│   ├── tab_slot_generator.py       # Mortise & Tenon generation
│   ├── finger_joint_generator.py   # Corner box joint generation
│   └── cross_joint_generator.py    # Slotted grid joint generation
├── resources/
│   ├── 16x16.png                   # Toolbar icons
│   ├── 32x32.png
│   └── 64x64.png
├── tests/
│   ├── __init__.py
│   └── test_geometry_math.py       # 12 automated test cases
├── install_addon.ps1               # One-click installer
└── README.md                       # This file
```

---

## 📜 License
MIT License. Built for makers, designers, and laser-cutting enthusiasts.
