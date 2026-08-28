# Fusion Add-ins - Installation & Usage Guide

These addons and guide were AI generated. It covers Three add-ins for Autodesk Fusion:

| Add-in | What it does |
|---|---|
| **Batch Bodies Exporter** | Exports individual bodies from selected components to STEP, STL, 3MF, OBJ, IGES, or SAT |
| **Export Flat Patterns** | Exports sheet-metal flat patterns from selected components to DXF, IGES, STEP, or SAT |
| **HoleToSlot** | Creates a slot from a hole perpendicular to a reference edge. Used to add tolerances. |
| **Fusion360KinematicsExporter** | Exports assemblies as URDF file. |
---

## Requirements

- Autodesk Fusion (any current subscription)
- Windows 10/11 or macOS

---

## Installation

### Step 1 - Copy the add-in folders

Copy the two add-in folders to Fusion's AddIns directory.

**Windows:**

    C:\Users\<YourUsername>\AppData\Roaming\Autodesk\Autodesk Fusion 360\API\AddIns\

**macOS:**

    ~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns/

After copying, the directory should look like this:

    AddIns/
      ExportBodies/
        ExportBodies.py
        ExportBodies.manifest
      FlatPatternExporter/
        FlatPatternExporter.py
        FlatPatternExporter.manifest
        resources/
          cmd/
            16x16-normal.png
            32x32-normal.png

> **Tip - Finding the AppData folder on Windows:**
> Press `Win + R`, type `%AppData%` and press Enter. This opens the Roaming folder directly.

---

### Step 2 - Load the add-ins in Fusion

1. Open Autodesk Fusion.
2. Go to the **Utilities** tab in the toolbar.
3. Click **Add-Ins** (or press `Shift + S`).
4. In the **Scripts and Add-Ins** dialog, select the **Add-Ins** tab.
5. Click the **+** (green plus) button next to *My Add-Ins*.
6. Browse to the add-in folder (e.g. `ExportBodies`) and select it.
   Repeat for the second add-in.
7. Select each add-in in the list and click **Run**.

> To have an add-in load automatically every time Fusion starts,
> tick **Run on Startup** before clicking Run.

---

### Step 3 - Confirm they are running

Both add-ins appear in the **Utilities** panel in the toolbar once running:

- **Batch Bodies Exporter**
- **Export Flat Patterns**

If you do not see them, switch to the **Design** workspace -
the Utilities panel is workspace-dependent.

---

## Using Batch Bodies Exporter

1. In the **Utilities** toolbar panel, click **Batch Bodies Exporter**.
2. **Select** one or more components from the canvas or browser.
3. Choose which body types to include: **Solid**, **Surface**, and/or **Sheet metal**.
4. Pick an **Export Format** (STEP, STL, 3MF, OBJ, IGES, SAT).
5. Optionally:
   - Tick **Include component name in filename** to prefix the body name with its component name.
   - Tick **Include sub-component bodies** to recurse into nested components.
   - Enter a **Filename Prefix** and/or **Filename Suffix** to add to every exported filename.
6. Click **OK**.
7. A folder picker appears - choose the destination folder.
8. If any files already exist you will be asked whether to overwrite them.
9. A summary dialog lists every exported file and any skipped bodies.

**Filename format:**

    [Prefix_]BodyName[_Suffix].ext
    [Prefix_]ComponentName_BodyName[_Suffix].ext   (when component name is included)

---

## Using Export Flat Patterns

1. In the **Utilities** toolbar panel, click **Export Flat Patterns**.
2. **Select** one or more sheet-metal component occurrences from the canvas or browser.
3. Optionally tick **Include sub-components (recursive)** to also process nested sheet-metal components.
4. Choose a **File format** (DXF, IGES, STEP, SAT).
5. When **DXF** is selected, expand **DXF options** to control:
   - Include bend lines
   - Include extent lines
   - Convert splines to polylines
6. Enter a **Filename Prefix** and/or **Filename Suffix** if needed.
7. Click **OK**.
8. A folder picker appears - choose the destination folder.
9. If any files already exist you will be asked whether to overwrite them.
10. A summary dialog lists every exported file and any skipped components.

> **Note:** If a component does not yet have a flat pattern, the add-in will
> attempt to create one automatically. If it cannot (e.g. a complex multi-body
> part), the component is listed as skipped with a prompt to create the flat
> pattern manually in the Sheet Metal workspace.

**Filename format:**

    [Prefix_]ComponentName[_Suffix].dxf

---

## Uninstalling

1. Go to **Utilities > Add-Ins** (`Shift + S`).
2. Select the add-in in the list.
3. Click **Stop** if it is running.
4. Untick **Run on Startup** if it was enabled.
5. Delete the add-in folder from the AddIns directory.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| Add-in does not appear in the list after copying | Make sure the `.py` and `.manifest` files are directly inside the named folder, not in a subfolder |
| Add-in runs but button is not visible | Switch to the **Design** workspace and check the **Utilities** panel |
| Export produces no files | Confirm the selected components contain bodies matching the chosen body-type filters |
| "Locked by another program" error | Close the file in any other application (e.g. CAD viewer, Windows Explorer preview) and try again |
| Flat pattern cannot be created automatically | Open the component in the **Sheet Metal** workspace, use **Create Flat Pattern** manually, then run the export again |

---
