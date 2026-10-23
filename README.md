# Fusion Add-ins - Installation & Usage Guide

These addons and guide were AI generated. It covers Three add-ins for Autodesk Fusion:

| Add-in | What it does |
|---|---|
| **Bodies Exporter** | Exports groups of components/bodies - per group as separate files (STEP, STL, 3MF, OBJ, IGES, SAT, or DXF flat patterns) or combined into one file (STEP, IGES, SAT) |
| **Quick Bodies Exporter** | Exports the current selection straight away as separate files or one combined file, without groups |
| **Quick Flat Pattern Exporter** | Quickly exports sheet-metal flat patterns from selected components to DXF (or the components to IGES, STEP, SAT) |
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
      RapidBatchExporter/
        RapidBatchExporter.py
        RapidBatchExporter.manifest
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
6. Browse to the add-in folder (e.g. `RapidBatchExporter`) and select it.
   Repeat for the second add-in.
7. Select each add-in in the list and click **Run**.

> To have an add-in load automatically every time Fusion starts,
> tick **Run on Startup** before clicking Run.

---

**Renamed:** the body and flat pattern exporters are one add-in, **Rapid Batch Exporter** (folder `RapidBatchExporter`, formerly `ExportBodies`). If you used the old version, remove the **ExportBodies** entry in **Scripts and Add-Ins** and add the `RapidBatchExporter` folder instead. Saved export groups and the last output folder carry over.

### Step 3 - Confirm they are running

The add-ins' commands appear in the **Utilities** panel in the toolbar once running:

- **Bodies Exporter**
- **Quick Bodies Exporter**
- **Quick Flat Pattern Exporter**

All three are also listed under **Export** on the Flat Pattern toolbar, where the Utilities panel is not shown.

If you do not see them, switch to the **Design** workspace -
the Utilities panel is workspace-dependent.

---

## Using Bodies Exporter

Exports **groups** of components and/or bodies. Each group is exported on its own,
either as **Separate** files (one file per body) or **Combined** into one file that
keeps the assembly structure and positions.

1. In the **Utilities** toolbar panel (or **Export** on the Flat Pattern toolbar), click **Bodies Exporter**.
2. Select components and/or bodies - one selection box takes both: clicking in the **canvas** selects the **body** under the cursor, clicking in the **browser** tree selects the **component**. Tick **Include sub-component bodies** to recurse into nested components.
3. Under **Export Groups**, enter a **Group / File Name**, choose the **New Group Output** (Separate / Combined) and **New Group Format**, then click **Add Group**. Repeat for as many groups as you need. **Only the ticked groups in the table are exported** - a selection that was not added as a group is ignored.
4. Each row of the table can be changed afterwards:
   - **Export** (first column, ticked by default) - untick a group to keep it in the list but skip it this time.
   - **Name** - the file name of a Combined group (and the subfolder name, see below).
   - **Output** - **Separate** (one file per body) or **Combined** (one file for the group).
   - **Format** - Separate: 3MF, STEP, STL, OBJ, IGES, SAT, DXF. Combined: STEP, IGES, SAT.
     **DXF** exports the sheet-metal **flat pattern** of each sheet-metal component in the group (one DXF per component, named after it; created automatically if missing). A **DXF Options** section (bend lines, extent lines, splines to polylines) appears while any group uses DXF.
   - **Subfolder** - Separate only, off by default: put the group's files in a subfolder named after the group.
   To change a group's items, select its row and click **Modify**: its components/bodies are loaded into the selection box. Add or remove items, then click **Update**. **Remove** / **Clear** drop groups.
5. Choose which body types to include (**Solid**, **Surface**, **Sheet metal**) and whether to **Export only visible bodies**. Bodies you selected directly are always included. These settings apply to every group.
6. Optionally tick **Include component name in filename** and set the **Naming Options** (prefix, document name as prefix, suffix, milestone `V#` as suffix) - applied to every group.
7. Click **OK** and choose the destination folder. It opens at the last folder you exported to, or your Documents folder the first time.
8. If any files already exist you are asked once whether to overwrite them all. A summary lists the exported files per group and anything skipped.

Bodies you create while editing a **flat pattern** can be exported too: run the exporter from **Export** on the Flat Pattern toolbar and select them there.

Separate groups export each body once, even if its component is used several times; with **Export only visible bodies** a body counts as visible when **any** selected instance of it is visible. Visibility is always that of the configuration that is active when you click **OK**. Combined groups keep every instance in its place: each source component becomes one component in the file, placed once per instance (configuration variants stay separate). The placement of every body is checked against the design before it is written.

**How STEP, IGES and SAT are exported:** Fusion's translator processes the whole component or design it is given, hidden parts included, which made exporting from large assemblies slow. These formats are therefore exported through a temporary document that contains only the bodies of the current file: it opens once as a tab, is reused for every file of the export, and is closed again without saving. Each body keeps its appearance (colour) and material, and each component its material, so STEP files carry the same colours and material names/densities as a direct Fusion export. Nothing in your design is hidden or changed. STL, 3MF, OBJ and DXF are exported directly.

**Name every body in STEP (slicer friendly)** (on by default, STEP only): slicers such as Bambu Studio name parts after the STEP *component*, so the bodies of a multi-body component show up as "Component-SOLID-1", "-SOLID-2". With this option each body becomes its own part named after the body ("Component_Body" inside sub-components). Geometry and positions are unchanged.

**Remembered settings:** when you click **OK**, the groups (with their Export tick, output, format and subfolder setting), filters, naming options and output folder are stored in the document. The next time you open the command in that document they are filled in again (save the document to keep them between sessions). Items that were deleted since are shown as "missing" in the group list. Groups saved by the older Combined Bodies Exporter load as Combined groups.

**Filename format:**

    Separate:  [Subfolder/][Prefix_][ComponentName_]BodyName[_Suffix].ext
    Combined:  [Prefix_][ComponentNames_]GroupName[_Suffix].ext

---

## Using Quick Bodies Exporter

The quick way when you just want to export what is selected, without setting up groups.

1. Click **Quick Bodies Exporter** (Utilities, or Export on the Flat Pattern toolbar).
2. Select bodies in the canvas and/or components in the browser tree (tick **Include sub-component bodies** to recurse).
3. Choose the **Output**: **Separate** (one file per body - 3MF, STEP, STL, OBJ, IGES, SAT, or DXF flat patterns) or **Combined** (one file - STEP, IGES, SAT, named by **File Name**).
4. Body Types, Export Options and Naming Options work as in the Bodies Exporter.
5. Click **OK** and choose the folder. The options (not the selection) are remembered per document.

---

## Using Quick Flat Pattern Exporter

Part of the Rapid Batch Exporter add-in (it replaces the separate FlatPatternExporter add-in - stop and unlink the old one in **Scripts and Add-Ins** if it is still listed). It uses the same **Naming Options** (prefix, document name, suffix, milestone) and remembered output folder as the body exporters, and is also listed under **Export** on the Flat Pattern toolbar.

1. In the **Utilities** toolbar panel, click **Quick Flat Pattern Exporter**.
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
