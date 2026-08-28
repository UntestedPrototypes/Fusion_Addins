# Fusion 360 Kinematics Exporter - Internal Architecture

This document provides a concise overview of how the custom Fusion 360 Add-in processes CAD assemblies, extracts kinematic data, and generates URDF and DH parameters.

## 1. Entry Point & UI (`Fusion360KinematicsExporter.py`)
- **Lifecycle:** Registers the command in the Fusion 360 toolbar (under `Utilities -> Utility`).
- **Command Execute:** Reads user inputs (names, export toggles, quality), spawns a progress dialog, and acts as the orchestrator by calling the core modules sequentially.

## 2. Assembly Parsing (`core/assembly_parser.py`)
This is the most mathematically complex module. It reads the Fusion 360 document and builds a `RobotModel` graph.
- **Tree Traversal:** It iterates through `rootComponent.allJoints` and `rootComponent.allOccurrences` to find all movable parts.
- **Rigid Joint Filtering:** If a joint is 'Rigid', it is ignored as a kinematic joint. Instead, the child occurrence is permanently merged into the parent's "URDF Link", treating them as a single rigid body.
- **Root Anchoring:** Any floating subassemblies not connected by joints are implicitly anchored to the root world origin via a simulated fixed joint to preserve absolute placement.
- **Coordinate System Mapping (CRITICAL):** 
  - **The Problem:** In Fusion 360, a component's origin is completely arbitrary. In URDF, a child link's origin *must* be exactly at its joint pivot. 
  - **The Solution:** The parser mathematically shifts the conceptual URDF Link origin to match the physical Fusion Joint Pivot (`P_joint`). To prevent the 3D meshes from moving, it applies an *inverse transform* to the visual `<origin>` offset, meaning the mesh renders perfectly in place while rotating correctly around the joint.
- **Unit Conversion:** Fusion's API natively returns Centimeters. The parser strictly multiplies all translations and bounding boxes by `0.01` to enforce URDF standard Meters.

## 3. STL Mesh Exporting (`core/stl_exporter.py`)
Handles extracting the 3D geometry from Fusion.
- **Visual Meshes:** Uses `exportManager.createSTLExportOptions(comp)` to export the full component (and its rigid sub-components) into a single high-quality binary STL file.
- **Optimized Collision Meshes:** 
  - If enabled, the exporter finds every individual physical body (`BRepBody`) in the component.
  - It evaluates their bounding boxes. If a body's bounding box is entirely encapsulated within another body's bounding box (e.g., an internal motor shaft or hidden screw), it is stripped out.
  - The remaining exterior bodies are exported as low-poly STLs.
  - A custom Python binary STL compiler (`merge_stls`) seamlessly stitches them together into a single `_col.stl` file, vastly improving physics simulation performance.

## 4. URDF Generation (`core/urdf_builder.py`)
Converts the parsed `RobotModel` graph into valid XML.
- **Inertial Data:** Extracts `centerOfMass`, `mass`, and the `inertia` tensor natively from Fusion's `PhysicalProperties` engine and writes it into the URDF `<inertial>` tags.
- **Visuals:** Points to the exported STL files, forcing `<mesh scale="0.001 0.001 0.001">` to convert the exported Millimeter STLs back into URDF Meters.
- **Collisions:** Uses either the optimized `_col.stl` mesh or a lightweight geometric `<box>` based on user preference.

## 5. Denavit-Hartenberg (DH) Calculation (`core/dh_calculator.py`)
Calculates the robotic kinematic chains for forward/inverse kinematics equations.
- Traces joint paths from the `base_link` to the end effectors.
- Projects the Z-axes (rotation axes) and X-axes (common normals) between successive joints.
- Calculates both **Standard DH** and **Modified DH** parameter tables (theta, d, a, alpha).

## 6. ESP32 C Header Generation (`core/esp_header_generator.py`)
Takes the computed DH parameters and formats them into a standard C struct array (`robot_kinematics.h`), ready to be compiled directly into embedded C++ firmware for motor controllers like the ESP32.
